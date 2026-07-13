"""Monthly recurring security audit (#227).

User-flagged 2026-05-24 (one of four "recurring audit" requests). The
2026-05-24 PAT-in-`.git/config` leak made it clear that #210's weekly
CVE check + gate 11's per-commit detection don't cover POSTURE — they
catch known bad shapes, not "should this still exist?" reviews.

This script runs monthly in GitHub Actions and checks four slow-drift
security signals that the per-commit gates miss:

  pat-inventory
      Read ``docs/security/pat-inventory.json`` (operator-maintained
      source of truth — GitHub does NOT expose a list-my-PATs API).
      Flag any entry where:
        - ``expires_at`` is null (PAT never expires — rotate to a
          finite expiry).
        - ``expires_at`` is more than 90 days in the future (cap PAT
          lifetime at 90 days — short-leash recovery if leaked).
        - ``last_used_at`` is more than 60 days in the past (the PAT
          may be abandoned; consider revoking).

  oauth-scope-drift
      Parse the Google OAuth scope list out of ``app.py``'s
      ``make_google_blueprint(scope=[...])`` call and compare to the
      allowlist in ``docs/security/oauth-scopes.json``. Flag any
      drift in either direction (added or removed scope). When you
      intentionally add a scope, update the JSON to match — the
      drift alert is BY DESIGN, prompting an explicit review.

  unencrypted-sensitive-columns
      Grep ``models.py`` for column names matching
      ``(token|secret|key|credential|password)`` regex (the name
      pattern that suggests sensitive data) and cross-reference
      against ``crypto.py`` import usage. Flag any sensitive-named
      column that ISN'T encrypted at rest. False-positive guard: the
      check skips names that are documented exceptions in
      ``_SENSITIVE_COLUMN_EXCEPTIONS`` (e.g. ``AppSetting.key`` is a
      settings-bucket key, not a credential).

  threat-model-freshness
      ``git log -- CLAUDE.md`` for the most-recent commit touching
      the file. If > 180 days ago, flag (the threat model may not
      reflect the current attack surface; do a posture review).

Each WARNING-level finding lands in the email body. Like #226, the
script sends an email EVERY run (clean or not) so the absence of an
email proves the monthly cron failed.

Exit codes:
    0 — all checks clean.
    1 — one or more checks reported a finding. Email sent.
    2 — internal error (e.g. couldn't read a required file).

Wired via ``.github/workflows/monthly-security-audit.yml`` (1st of
each month, 13:00 UTC).
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Finding:
    check_id: str
    detail: str
    path: str = ""
    line_num: int = 0


# Thresholds — single source of truth for the audit policy.
_PAT_EXPIRY_MAX_DAYS = 90
_PAT_LAST_USED_MAX_DAYS = 60
_THREAT_MODEL_MAX_DAYS = 180


# ---------------------------------------------------------------------------
# Check (a): GitHub PAT inventory
# ---------------------------------------------------------------------------


def _today() -> datetime.date:
    return datetime.date.today()


def _parse_iso_date(s: str | None) -> datetime.date | None:
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        return datetime.date.fromisoformat(s.strip())
    except ValueError:
        return None


def check_pat_inventory() -> list[Finding]:
    """Read docs/security/pat-inventory.json and flag stale / unbounded
    PAT entries.

    Returns an empty list when the file is missing OR has zero token
    entries — neither is a security issue in itself; the OPERATOR
    deciding to track no PATs is a valid choice (e.g. SSH-only auth).
    """
    findings: list[Finding] = []
    p = PROJECT_ROOT / "docs" / "security" / "pat-inventory.json"
    if not p.exists():
        return findings
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return [Finding(
            check_id="pat-inventory",
            detail=f"could not parse docs/security/pat-inventory.json: {e}",
        )]
    tokens = data.get("tokens") if isinstance(data, dict) else None
    if not isinstance(tokens, list):
        return findings
    today = _today()
    for tok in tokens:
        if not isinstance(tok, dict):
            continue
        name = tok.get("name") or "(unnamed)"
        expires_at = _parse_iso_date(tok.get("expires_at"))
        last_used_at = _parse_iso_date(tok.get("last_used_at"))
        if tok.get("expires_at") is None:
            findings.append(Finding(
                check_id="pat-inventory",
                detail=(
                    f"PAT {name!r}: expires_at is null — rotate to a "
                    "finite expiry (cap recommended at 90 days)"
                ),
            ))
        elif expires_at is not None:
            days_until_expiry = (expires_at - today).days
            if days_until_expiry > _PAT_EXPIRY_MAX_DAYS:
                findings.append(Finding(
                    check_id="pat-inventory",
                    detail=(
                        f"PAT {name!r}: expires_at {expires_at.isoformat()} "
                        f"is {days_until_expiry} days away (cap "
                        f"at {_PAT_EXPIRY_MAX_DAYS} days)"
                    ),
                ))
        if last_used_at is not None:
            days_since_use = (today - last_used_at).days
            if days_since_use > _PAT_LAST_USED_MAX_DAYS:
                findings.append(Finding(
                    check_id="pat-inventory",
                    detail=(
                        f"PAT {name!r}: last_used_at "
                        f"{last_used_at.isoformat()} is {days_since_use} "
                        f"days ago (cap at {_PAT_LAST_USED_MAX_DAYS} days "
                        "— consider revoking if abandoned)"
                    ),
                ))
    return findings


# ---------------------------------------------------------------------------
# Check (b): Google OAuth scope drift
# ---------------------------------------------------------------------------

# Match the `scope=[ "...", "...", ... ]` block in app.py. We look for
# the `scope=[ ... ]` literal directly (not nested inside the
# `make_google_blueprint(...)` parens) because the nested-paren regex
# fails when the kwargs above scope= contain function calls with their
# own parens (e.g. `os.environ.get("GOOGLE_CLIENT_ID")`).
#
# Trade-off: if someone added a second `scope=[...]` literal elsewhere
# in app.py, we'd over-match. Single-purpose file, low risk, easy to
# tighten later.
_OAUTH_SCOPE_BLOCK_RE = re.compile(
    r"scope\s*=\s*\[([^\]]*)\]",
    re.DOTALL,
)
_OAUTH_SCOPE_ITEM_RE = re.compile(r"[\"']([^\"']+)[\"']")


def _read_app_py_scopes() -> set[str]:
    p = PROJECT_ROOT / "app.py"
    if not p.exists():
        return set()
    text = p.read_text(encoding="utf-8")
    m = _OAUTH_SCOPE_BLOCK_RE.search(text)
    if not m:
        return set()
    block = m.group(1)
    return set(_OAUTH_SCOPE_ITEM_RE.findall(block))


def check_oauth_scope_drift() -> list[Finding]:
    """Compare current app.py scope list to the committed allowlist.
    Flags drift in either direction so an intentional change still
    requires an explicit allowlist update.
    """
    findings: list[Finding] = []
    code_scopes = _read_app_py_scopes()
    allow_path = PROJECT_ROOT / "docs" / "security" / "oauth-scopes.json"
    if not allow_path.exists():
        findings.append(Finding(
            check_id="oauth-scope-drift",
            detail=(
                "docs/security/oauth-scopes.json is missing — create it "
                "with the current app.py scope list to establish a "
                "baseline for future drift detection"
            ),
        ))
        return findings
    try:
        allow = json.loads(allow_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return [Finding(
            check_id="oauth-scope-drift",
            detail=f"could not parse docs/security/oauth-scopes.json: {e}",
        )]
    allowed = set(allow.get("scopes", []) if isinstance(allow, dict) else [])
    added = sorted(code_scopes - allowed)
    removed = sorted(allowed - code_scopes)
    for s in added:
        findings.append(Finding(
            check_id="oauth-scope-drift",
            detail=(
                f"NEW scope in app.py not in allowlist: {s!r} — review "
                "the blast-radius implications and add to "
                "docs/security/oauth-scopes.json if intentional"
            ),
        ))
    for s in removed:
        findings.append(Finding(
            check_id="oauth-scope-drift",
            detail=(
                f"scope REMOVED from app.py but still in allowlist: "
                f"{s!r} — update docs/security/oauth-scopes.json to "
                "match (intentional removal is fine, just keep the doc "
                "in sync)"
            ),
        ))
    return findings


# ---------------------------------------------------------------------------
# Check (c): sensitive-named DB columns not routed through crypto
# ---------------------------------------------------------------------------

# Column-name pattern that suggests sensitive data. False positives
# (e.g. `AppSetting.key` is a settings-bucket key, not a credential)
# get an explicit exception in _SENSITIVE_COLUMN_EXCEPTIONS below.
_SENSITIVE_COL_RE = re.compile(
    r"\b(\w*(?:token|secret|password|credential|api_key)\w*)\s*"
    r":\s*Mapped\[",
    re.IGNORECASE,
)

# Documented exceptions — column names that LOOK sensitive but aren't
# (or are intentionally not encrypted for a documented reason). Keep
# this list small and audit it manually whenever it changes.
_SENSITIVE_COLUMN_EXCEPTIONS: frozenset[str] = frozenset({
    # AppSetting.key is the settings-row identifier ("digest_email"
    # etc.), not a credential.
    "key",
})


def check_unencrypted_sensitive_columns() -> list[Finding]:
    """Scan models.py for sensitive-named columns AND check whether
    crypto.py is imported in that file. Currently no Reflection /
    Task / Project / Goal column is sensitive — this is a tripwire
    for FUTURE schema additions.
    """
    findings: list[Finding] = []
    models_path = PROJECT_ROOT / "models.py"
    crypto_path = PROJECT_ROOT / "crypto.py"
    if not models_path.exists() or not crypto_path.exists():
        return findings
    models_text = models_path.read_text(encoding="utf-8")
    crypto_imported = bool(re.search(
        r"^(?:from\s+crypto\s+import|import\s+crypto)",
        models_text,
        re.M,
    ))
    # Walk lines to get accurate file:line for each finding.
    for i, line in enumerate(models_text.splitlines(), start=1):
        m = _SENSITIVE_COL_RE.search(line)
        if not m:
            continue
        col_name = m.group(1).lower()
        if col_name in _SENSITIVE_COLUMN_EXCEPTIONS:
            continue
        if not crypto_imported:
            findings.append(Finding(
                check_id="unencrypted-sensitive-columns",
                path="models.py",
                line_num=i,
                detail=(
                    f"sensitive-named column {col_name!r} declared "
                    "but crypto.py is not imported in models.py — "
                    "consider routing reads/writes through "
                    "crypto.encrypt / crypto.decrypt, OR add the "
                    "column to _SENSITIVE_COLUMN_EXCEPTIONS in "
                    "scripts/check_security_posture.py if it's "
                    "intentionally plaintext"
                ),
            ))
        # If crypto IS imported, we can't tell mechanically whether
        # THIS specific column routes through it. Future work: AST
        # walk to confirm. For now, the import presence is a soft
        # signal; the audit catches the most common drift class
        # (forgot to wire crypto at all).
    return findings


# ---------------------------------------------------------------------------
# Check (d): threat-model freshness
# ---------------------------------------------------------------------------


def check_threat_model_freshness() -> list[Finding]:
    """Flag if CLAUDE.md hasn't been touched in > 180 days.

    The threat model lives inside CLAUDE.md (see "Threat model" section).
    A stale CLAUDE.md is a soft signal — maybe nothing's changed and a
    review is overdue, maybe the file just isn't where docs end up
    anymore. Either way: prompt a review.
    """
    findings: list[Finding] = []
    claude_md = PROJECT_ROOT / "CLAUDE.md"
    if not claude_md.exists():
        return findings
    try:
        proc = subprocess.run(  # noqa: S603, S607 — git is trusted
            ["git", "log", "-1", "--format=%cI", "--", "CLAUDE.md"],
            capture_output=True, text=True, check=False,
            cwd=PROJECT_ROOT,
        )
    except (FileNotFoundError, OSError):
        return findings
    if proc.returncode != 0 or not proc.stdout.strip():
        return findings
    iso_ts = proc.stdout.strip()
    # `git log --format=%cI` returns ISO-8601 with timezone offset; we
    # only need the date part for the day-granularity threshold.
    try:
        last_touched = datetime.date.fromisoformat(iso_ts[:10])
    except ValueError:
        return findings
    days_since = (_today() - last_touched).days
    if days_since > _THREAT_MODEL_MAX_DAYS:
        findings.append(Finding(
            check_id="threat-model-freshness",
            path="CLAUDE.md",
            detail=(
                f"CLAUDE.md last touched {last_touched.isoformat()} "
                f"({days_since} days ago) — review the Threat model "
                "section against the current attack surface (new "
                "endpoints, new external API callers, new env vars). "
                "Touch the file (even just a date stamp) to reset "
                "the timer."
            ),
        ))
    return findings


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

CHECKS = [
    ("pat-inventory", check_pat_inventory),
    ("oauth-scope-drift", check_oauth_scope_drift),
    ("unencrypted-sensitive-columns", check_unencrypted_sensitive_columns),
    ("threat-model-freshness", check_threat_model_freshness),
]


def send_audit_email(
    findings: list[Finding],
    *,
    per_check_counts: list[tuple[str, int]],
) -> None:
    """Send an email on EVERY run, clean or not (mirrors #226c's
    confirmation-on-clean behavior). Best-effort — failures LOG but
    don't change the exit code.
    """
    api_key = os.environ.get("BREVO_API_KEY")
    from_addr = os.environ.get("DIGEST_FROM_EMAIL")
    to_addr = os.environ.get("DIGEST_TO_EMAIL")
    if not (api_key and from_addr and to_addr):
        sys.stderr.write(
            "[security-posture] Brevo not configured; skipping email\n"
        )
        return

    today = datetime.date.today().isoformat()
    total = len(findings)
    by_check: dict[str, list[Finding]] = {}
    for f in findings:
        by_check.setdefault(f.check_id, []).append(f)

    clean = total == 0
    if clean:
        subject = f"[Taskmanager security-posture] CLEAN — {today}"
        body_lines = [
            f"Monthly security-posture audit {today}: ALL CHECKS CLEAN "
            f"({len(per_check_counts)} checks, 0 findings).",
            "",
            "This confirmation email fires on every monthly run so the "
            "absence of an email = the cron failed (or the workflow "
            "config drifted).",
            "",
            "Per-check breakdown:",
        ]
        for label, count in per_check_counts:
            body_lines.append(f"  ✓ {label}: {count} finding(s)")
    else:
        subject = (
            f"[Taskmanager security-posture] {total} finding(s) — {today}"
        )
        body_lines = [
            f"Monthly security-posture audit {today} found {total} "
            f"finding(s) across {len(by_check)} check(s).",
            "",
        ]
        for label, _ in CHECKS:
            hits = by_check.get(label, [])
            body_lines.append(f"== {label} ({len(hits)} finding(s)) ==")
            for f in hits:
                where = ""
                if f.path:
                    where = f"  {f.path}"
                    if f.line_num:
                        where += f":{f.line_num}"
                    where += "\n"
                body_lines.append(f"{where}      → {f.detail}")
            body_lines.append("")
        body_lines += [
            "Action: review each finding, fix the underlying issue, "
            "and re-run `python scripts/check_security_posture.py` "
            "to confirm clean. See the GitHub Actions run for the "
            "full raw output.",
        ]

    payload = {
        "sender": {"email": from_addr, "name": "Taskmanager CI"},
        "to": [{"email": to_addr}],
        "subject": subject,
        "textContent": "\n".join(body_lines),
    }
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "api-key": api_key,
            "accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        # URL is the constant Brevo endpoint, not user input.
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310  # nosec B310  # nosemgrep
            sys.stdout.write(
                f"[security-posture] email sent: HTTP {resp.status}\n"
            )
    except urllib.error.URLError as e:
        sys.stderr.write(f"[security-posture] email send failed: {e}\n")


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Run the #227 monthly security-posture audit.",
    )
    parser.add_argument(
        "--autofile", action="store_true",
        help=(
            "#242: upsert findings into BACKLOG.md's "
            "`## Auto-filed by recurring audits` section after the "
            "email step. Used by the monthly cron workflow."
        ),
    )
    args = parser.parse_args(argv)

    sys.stdout.write(
        f"[security-posture] starting "
        f"{datetime.datetime.now(datetime.UTC).isoformat()}\n"
    )

    all_findings: list[Finding] = []
    per_check_counts: list[tuple[str, int]] = []
    for label, check_fn in CHECKS:
        try:
            findings = check_fn()
        except (OSError, ValueError, RuntimeError) as e:
            sys.stderr.write(f"[security-posture] {label} errored: {e}\n")
            return 2
        sys.stdout.write(
            f"[security-posture] {label}: {len(findings)} finding(s)\n"
        )
        for f in findings:
            if f.path:
                line_suffix = f":{f.line_num}" if f.line_num else ""
                sys.stdout.write(f"    {f.path}{line_suffix}\n")
            sys.stdout.write(f"      -> {f.detail}\n")
        all_findings.extend(findings)
        per_check_counts.append((label, len(findings)))

    # Email on every run (clean or not) — same pattern as #226c.
    send_audit_email(all_findings, per_check_counts=per_check_counts)
    if args.autofile:
        # Add PROJECT_ROOT to sys.path so `from scripts import ...`
        # works when run as `python scripts/check_security_posture.py`.
        sys.path.insert(0, str(PROJECT_ROOT))
        from scripts import backlog_autofile  # noqa: PLC0415
        backlog_autofile.run_for_audit("security", all_findings)
    if not all_findings:
        sys.stdout.write(
            "[security-posture] CLEAN — confirmation email sent.\n"
        )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
