"""Weekly bug-pattern scan (#226).

Runs in GitHub Actions on a weekly cron — the drift-over-time complement
to the per-commit gates in ``scripts/run_all_gates.sh``. The on-commit
gates catch NEW instances of known-bad shapes as code is being written;
this scan watches for OLD instances of patterns we LEARNED about after
the code was originally written and may have left behind.

Five mechanical checks ship in the first cut:

  bare-1fr-grids
      ``grid-template-columns: ... 1fr`` in ``static/style.css`` without
      a ``minmax(0, ...)`` wrapper. The #138 / #216 / #217 D-B1 class
      we shipped 7 fixes for during the 2026-05-24 audit. A bare ``1fr``
      track sizes to ``max-content`` when its row contains an
      unbreakable element (long URL, ``flex-shrink: 0`` button cluster),
      blowing the parent past its container width on narrow viewports.

  embedded-url-credentials
      ``https://user[:token]@host/...`` in any committed source file.
      Gate 11 in ``run_all_gates.sh`` covers ``.git/config`` only;
      gitleaks scans the tree but its default rules miss this shape.
      Catches the 2026-05-24 PAT leak class re-surfacing in source.

  string-match-only-prod-tests
      Belt-and-braces re-run of ``scripts/check_no_string_match_only_tests.py``
      (gate 8d). In case a developer locally bypasses the on-commit gate.
      A weekly heartbeat that the anti-pattern #3 guard is still healthy.

  state-mutating-get-routes
      ``@app.route(..., methods=["GET", "POST"...])`` patterns that
      accept GET alongside any of POST/PATCH/PUT/DELETE — the #190 CSRF
      surface. Flask routes that genuinely mix verbs should use the
      explicit ``@bp.get`` + ``@bp.post`` decorators instead.

  raw-tier-string-compare
      ``tier == "today"`` style string comparisons in Python source
      (outside tests) — bug #57's case-typo cascade. Should go through
      ``Tier.TODAY`` enum members. Tests intentionally compare strings
      to enum values; only non-test Python is scanned.

  unbalanced-type-work (#226b, 2026-05-26)
      ``.type === "work"`` (or ``!==``) in JS source without any
      ``"personal"`` reference within ±20 lines — bug #57's other
      cascade row. Heuristic windowed scan (not pure regex) because
      legitimate if/else blocks must NOT flag.

Pipeline::

    for each check_fn in CHECKS:
        findings += check_fn()
        ↓
    no findings? → exit 0 silently (no email)
    any finding? → Brevo email with file:line list + exit 1

Exit codes (so the GitHub Actions UI shows red on findings):
    0 — all checks clean.
    1 — one or more checks reported a finding. Email sent if Brevo
        is configured.
    2 — internal error (e.g. couldn't read style.css at all).

Email-send failures DO NOT change the exit code — same convention as
``scripts/check_advisories.py`` and ``scripts/backup_to_github.py``.

Wired via ``.github/workflows/weekly-bug-pattern-scan.yml`` (Sundays
13:00 UTC — lands before Monday so findings are first-thing-Monday
context). Manual trigger via the Actions UI ("workflow_dispatch") for
one-off verification.
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
    """One offending location.

    Attributes:
        check_id: stable id of the check that emitted this (e.g.
            ``"bare-1fr-grids"``). Used to group the email.
        path: project-relative path of the offending file.
        line_num: 1-based line number.
        line: literal source line (stripped of trailing newline; LEFT
            indentation preserved so the operator sees context shape).
        message: short human-readable explanation of why this line
            tripped the check.
    """

    check_id: str
    path: str
    line_num: int
    line: str
    message: str


# ---------------------------------------------------------------------------
# Check (a): bare ``1fr`` grids in style.css (#138 / #216 / #217 D-B1 class).
# ---------------------------------------------------------------------------

# Match a `grid-template-columns:` declaration whose RHS contains the
# token ``1fr`` (word-boundary on both sides so ``11fr`` doesn't match).
# We then separately confirm the same logical declaration is NOT wrapped
# in ``minmax(0, ...)``.
_GRID_TEMPLATE_DECL_RE = re.compile(
    r"grid-template-columns\s*:\s*([^;]+);?",
    re.IGNORECASE,
)
_BARE_1FR_TOKEN_RE = re.compile(r"\b1fr\b")
# A `minmax(...)` chunk, tolerant of ONE level of nested parens in the min
# slot (e.g. `minmax(min(300px, 100%), 1fr)`). CSS grid track functions
# don't nest deeper than this in practice.
_MINMAX_RE = re.compile(r"minmax\((?:[^()]|\([^()]*\))*\)", re.IGNORECASE)


def _track_uses_bare_1fr(rhs: str) -> bool:
    """Return True iff ``rhs`` has a ``1fr`` track OUTSIDE a ``minmax(...)``.

    A ``1fr`` inside ``minmax(<min>, 1fr)`` is the harmless MAX slot — the
    min slot bounds how far the track shrinks, so ``minmax(0, 1fr)``,
    ``minmax(200px, 1fr)`` and ``minmax(min(300px, 100%), 1fr)`` are all
    safe. Only a bare ``1fr`` track (``1fr``, ``repeat(3, 1fr)``) has an
    implicit ``auto`` (= max-content) min that can blow the grid past its
    container (#138 D-B1). So strip every ``minmax(...)`` chunk — mixed
    declarations like ``1fr minmax(0, 1fr)`` keep the bare first track — then
    look for any surviving ``1fr`` token.

    #302: the strip must tolerate a nested function in the min slot. The old
    ``minmax([^)]+)`` strip stopped at the inner ``)`` of ``min(300px, 100%)``,
    left the outer ``1fr`` exposed, and false-flagged the safe responsive card
    grids (``repeat(auto-fill, minmax(min(300px, 100%), 1fr))``).
    """
    stripped = _MINMAX_RE.sub("", rhs)
    return bool(_BARE_1FR_TOKEN_RE.search(stripped))


def check_bare_1fr_grids() -> list[Finding]:
    """Scan static/style.css for ``grid-template-columns`` rules that use
    a bare ``1fr`` track without ``minmax(0, ...)``.
    """
    findings: list[Finding] = []
    css_path = PROJECT_ROOT / "static" / "style.css"
    if not css_path.exists():
        return findings
    text = css_path.read_text(encoding="utf-8")
    # Walk line-by-line because grid-template-columns is almost always
    # written on a single line in this codebase; reading the whole file
    # as a string would lose line numbers without re.finditer + offset
    # math, and line-walk is plenty fast at <10k lines.
    for i, line in enumerate(text.splitlines(), start=1):
        m = _GRID_TEMPLATE_DECL_RE.search(line)
        if not m:
            continue
        rhs = m.group(1)
        if _track_uses_bare_1fr(rhs):
            findings.append(Finding(
                check_id="bare-1fr-grids",
                path="static/style.css",
                line_num=i,
                line=line.rstrip(),
                message=(
                    "bare `1fr` track on grid-template-columns — wrap "
                    "in `minmax(0, 1fr)` to let the track shrink past "
                    "max-content (#138 D-B1)"
                ),
            ))
    return findings


# ---------------------------------------------------------------------------
# Check (b): embedded URL credentials anywhere in committed source.
# ---------------------------------------------------------------------------

# ``https://user@host`` or ``https://user:token@host`` — username
# optionally followed by ``:password``, then ``@host``. We exclude
# whitespace + ``/`` from the username and credential characters so a
# benign in-prose mention like ``https://example.com/...`` doesn't match.
_URL_CRED_RE = re.compile(r"https?://[^@\s/]+(?::[^@\s/]+)?@[^\s]")

# Files where the pattern is documented for security/operator reference,
# NOT a real leak. The on-commit gate 11 + gitleaks already protect the
# rest of the tree from accidents. Anything outside this allowlist
# matching the pattern is a real finding.
_EMBEDDED_CRED_ALLOWLIST = frozenset({
    "README.md",
    "BACKLOG.md",
    "CLAUDE.md",
    "docs/security/git-credentials.md",
    "scripts/run_all_gates.sh",  # gate 11 documents the pattern in comments
    "scripts/check_bug_patterns.py",  # this script — regex literal
    "tests/test_bug_pattern_scan.py",  # tests for this script
    "templates/architecture.html",  # in-app docs reference
})


def _walk_tracked_files() -> list[Path]:
    """Return every file in the repo's working tree, excluding common
    binary / generated directories and gitignored paths.

    Uses ``git ls-files`` so generated files (node_modules, __pycache__,
    .venv) are naturally excluded — they're not tracked.
    """
    try:
        proc = subprocess.run(  # noqa: S603, S607 — git is trusted
            ["git", "ls-files"],
            capture_output=True,
            text=True,
            check=False,
            cwd=PROJECT_ROOT,
        )
    except (FileNotFoundError, OSError):
        return []
    if proc.returncode != 0:
        return []
    paths = []
    for rel in proc.stdout.splitlines():
        p = PROJECT_ROOT / rel
        if p.is_file():
            paths.append(p)
    return paths


def check_embedded_url_credentials() -> list[Finding]:
    """Scan every tracked file for ``https://user[:token]@host/`` shapes
    that aren't part of documentation explaining the pattern.
    """
    findings: list[Finding] = []
    for p in _walk_tracked_files():
        rel = p.relative_to(PROJECT_ROOT).as_posix()
        if rel in _EMBEDDED_CRED_ALLOWLIST:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable — skip silently
        for i, line in enumerate(text.splitlines(), start=1):
            if _URL_CRED_RE.search(line):
                findings.append(Finding(
                    check_id="embedded-url-credentials",
                    path=rel,
                    line_num=i,
                    # NEVER echo the full line — could leak the secret
                    # into the email / Actions log. Mask the
                    # credential portion before recording.
                    line=re.sub(
                        r"(://[^:/\s]+)(:[^@/\s]+)?@",
                        r"\1:****@",
                        line.rstrip(),
                    ),
                    message=(
                        "URL contains embedded user[:credential]@ — "
                        "rotate the credential NOW + move to a "
                        "credential helper or env var"
                    ),
                ))
    return findings


# ---------------------------------------------------------------------------
# Check (c): re-run the gate 8d string-match-only prod test guard.
# ---------------------------------------------------------------------------


def check_string_match_only_prod_tests() -> list[Finding]:
    """Belt-and-braces re-run of ``scripts/check_no_string_match_only_tests.py``.

    The on-commit gate 8d already runs this; the weekly cron heartbeat
    catches the case where someone bypassed the gate locally.
    """
    gate_script = PROJECT_ROOT / "scripts" / "check_no_string_match_only_tests.py"
    if not gate_script.exists():
        return []
    proc = subprocess.run(  # noqa: S603 — gate_script is a constant
        [sys.executable, str(gate_script)],
        capture_output=True,
        text=True,
        check=False,
        cwd=PROJECT_ROOT,
    )
    if proc.returncode == 0:
        return []
    # The gate prints offending lines on its stdout. Capture as a single
    # synthetic Finding pointing at the script — the email body will
    # contain the gate's raw output so the operator can act.
    return [Finding(
        check_id="string-match-only-prod-tests",
        path="tests/e2e-prod/",
        line_num=0,
        line=(proc.stdout + proc.stderr).strip()[:2000],
        message=(
            "scripts/check_no_string_match_only_tests.py (gate 8d) "
            "reported findings — a prod-smoke test only string-matches "
            "bundled source. Extract logic to a *_helpers.js dual-export "
            "and Jest-test the actual function (anti-pattern #3)."
        ),
    )]


# ---------------------------------------------------------------------------
# Check (d): state-mutating GET routes (#190 CSRF surface).
# ---------------------------------------------------------------------------

_METHODS_LIST_RE = re.compile(
    r"@\w+\.route\([^)]*methods\s*=\s*\[([^\]]+)\]",
    re.IGNORECASE,
)
_MUTATING_VERB_SET = {"POST", "PATCH", "PUT", "DELETE"}


def check_state_mutating_get_routes() -> list[Finding]:
    """Scan Python source for ``@bp.route(..., methods=[...])`` declarations
    that mix GET with any of POST/PATCH/PUT/DELETE.

    A state-mutating GET is a CSRF surface — ``SameSite=Lax`` does NOT
    block top-level cross-origin GETs, so a malicious page's
    ``<img src="https://app/that-route">`` silently fires it. Routes that
    genuinely need both behaviors should split into ``@bp.get`` +
    ``@bp.post`` decorators with separate handler functions.
    """
    findings: list[Finding] = []
    for p in _walk_tracked_files():
        if p.suffix != ".py":
            continue
        rel = p.relative_to(PROJECT_ROOT).as_posix()
        # Skip the bug-pattern script + its tests — they contain the
        # regex/example literals.
        if rel in ("scripts/check_bug_patterns.py", "tests/test_bug_pattern_scan.py"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            m = _METHODS_LIST_RE.search(line)
            if not m:
                continue
            inside = m.group(1)
            verbs = {
                v.strip().strip("'\"").upper()
                for v in inside.split(",")
                if v.strip()
            }
            if "GET" in verbs and (verbs & _MUTATING_VERB_SET):
                offenders = sorted(verbs & _MUTATING_VERB_SET)
                findings.append(Finding(
                    check_id="state-mutating-get-routes",
                    path=rel,
                    line_num=i,
                    line=line.rstrip(),
                    message=(
                        f"route declares methods=[..GET..{','.join(offenders)}..] — "
                        f"GET + state-mutating verb is a CSRF surface (#190). "
                        f"Split into @bp.get + @bp.{offenders[0].lower()} decorators."
                    ),
                ))
    return findings


# ---------------------------------------------------------------------------
# Check (e): unbalanced `.type === "work"` in JS without a personal branch.
# ---------------------------------------------------------------------------
# Bug #57's cascade row in CLAUDE.md: when a feature is extended from
# work-only to work+personal, code that hard-coded `task.type === "work"`
# (without a sibling `else if task.type === "personal"`) silently dropped
# personal-type behavior. The original incident was the task-detail
# save handler at static/app.js — a stale `type === "work"` conditional
# silently dropped `project_id` for personal tasks, no error raised,
# only caught by manual user testing.
#
# Deferred from #226's first cut as "fuzzy heuristic" — pure regex
# misfires on every legitimate if/else. Implemented here as a windowed
# scan: a `.type === "work"` reference is OK iff there's ANY mention of
# "personal" within ±20 lines (the typical if/else block fits in that
# window). Unbalanced uses get flagged.

_TYPE_WORK_RE = re.compile(r'\.type\s*[=!]==\s*["\']work["\']')
_PERSONAL_NEAR_RE = re.compile(r'["\']personal["\']')


def _strip_js_line_comment(line: str) -> str:
    """Return the non-comment portion of a JS line.

    Naive but sufficient for our regex-defense purpose: find the FIRST
    `//` that appears outside a quoted string (rough count) and chop
    everything after it. Block comments (``/* ... */``) are rare in
    this codebase and not worth a full lexer — those false-positives
    can be silenced via the cascade-comment heuristic below.
    """
    idx = line.find("//")
    if idx == -1:
        return line
    before = line[:idx]
    # Crude string-aware check: if quote counts are even, `//` is
    # outside any string and is a real comment start.
    if before.count('"') % 2 == 0 and before.count("'") % 2 == 0:
        return before
    return line


def check_unbalanced_type_work() -> list[Finding]:
    """Scan JS source for ``.type === "work"`` (or ``!==``) without a
    matching ``"personal"`` reference nearby — bug #57 class.

    Heuristic: for each ``.type === "work"`` line, look ±20 lines for
    the literal string ``"personal"`` (in any quoting style). If
    found, the check considers the branch balanced and skips. If not,
    emit a Finding so the developer can audit whether this is the
    next #57.

    Scope: ``static/*.js`` only. Tests live in ``tests/js/`` and
    intentionally compare against specific type values — skipped.
    Python source uses ``TaskType.WORK`` / ``TaskType.PERSONAL`` enum
    members instead of strings (per CLAUDE.md), so Python isn't scoped
    in this check.
    """
    findings: list[Finding] = []
    for p in _walk_tracked_files():
        if p.suffix != ".js":
            continue
        rel = p.relative_to(PROJECT_ROOT).as_posix()
        # Skip tests — they intentionally assert specific type values.
        if rel.startswith("tests/"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines, start=1):
            code = _strip_js_line_comment(line)
            if not _TYPE_WORK_RE.search(code):
                continue
            # ±20 line window around the match.
            start = max(0, i - 1 - 20)
            end = min(len(lines), i + 20)
            window = "\n".join(lines[start:end])
            if _PERSONAL_NEAR_RE.search(window):
                continue  # balanced — has a personal branch nearby
            findings.append(Finding(
                check_id="unbalanced-type-work",
                path=rel,
                line_num=i,
                line=line.rstrip(),
                message=(
                    "`.type === \"work\"` (or `!==`) check has no "
                    '"personal" reference within 20 lines — extend '
                    "to handle both types (bug #57 class) or use "
                    "the TaskType enum"
                ),
            ))
    return findings


# ---------------------------------------------------------------------------
# Check (f): raw tier-string comparisons in Python source.
# ---------------------------------------------------------------------------

# Match patterns like:
#   tier == "today"
#   t.tier == "tomorrow"
#   task.tier == 'backlog'
#   "today" == task.tier
# but NOT:
#   Tier.TODAY == "today"   (legitimate enum value-side comparison)
#   request.args.get("tier")  (querystring read, not a tier compare)
_TIER_VALUES = ("today", "tomorrow", "this_week", "next_week", "backlog", "freezer", "inbox")
_TIER_VALUES_GROUP = "|".join(_TIER_VALUES)

# `tier` (bare OR as an attribute like `task.tier` / `self.tier`)
# followed by ==/!=, then a literal string matching a known tier value.
# Use two regexes so we can capture both sides of the comparison.
#
# Word-boundary `\b` correctly matches between `.` (non-word) and `t`
# (word), so `task.tier` is caught. `\b` also rejects `tiered` (no
# boundary between `r` and `e`) and `_tier` (no boundary between `_`
# and `t` — both word chars).
_TIER_COMPARE_LHS_RE = re.compile(
    rf"\btier\s*(?:==|!=)\s*[\"']({_TIER_VALUES_GROUP})[\"']",
)
_TIER_COMPARE_RHS_RE = re.compile(
    rf"[\"']({_TIER_VALUES_GROUP})[\"']\s*(?:==|!=)\s*(?:\w+\.)?\btier\b",
)


def check_raw_tier_string_compare() -> list[Finding]:
    """Scan non-test Python source for ``tier == \"today\"`` style
    comparisons that bypass the ``Tier`` enum.

    A typo like ``tier == \"Today\"`` is silent at runtime — Python
    happily returns False — but ``Tier.TODAY`` would NameError at import
    time. The enum is the safe path for non-querystring tier checks.
    """
    findings: list[Finding] = []
    for p in _walk_tracked_files():
        if p.suffix != ".py":
            continue
        rel = p.relative_to(PROJECT_ROOT).as_posix()
        # Skip the bug-pattern script + its tests — they reference the
        # patterns intentionally. Skip the test tree generally because
        # test code legitimately compares strings to enum.value.
        if rel == "scripts/check_bug_patterns.py":
            continue
        if rel.startswith("tests/"):
            continue
        # Skip migrations — they're frozen historical schema mutations
        # and may compare to literal string values that match old enum
        # shapes. We never want to "fix" a migration after it has run.
        if rel.startswith("migrations/"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if _TIER_COMPARE_LHS_RE.search(line) or _TIER_COMPARE_RHS_RE.search(line):
                findings.append(Finding(
                    check_id="raw-tier-string-compare",
                    path=rel,
                    line_num=i,
                    line=line.rstrip(),
                    message=(
                        "tier compared to a raw string literal — use "
                        "Tier.TODAY / Tier.TOMORROW / etc. so a typo "
                        "becomes a NameError instead of a silent False"
                    ),
                ))
    return findings


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

# Each entry: (label, callable). Order is the report order.
CHECKS = [
    ("bare-1fr-grids", check_bare_1fr_grids),
    ("embedded-url-credentials", check_embedded_url_credentials),
    ("string-match-only-prod-tests", check_string_match_only_prod_tests),
    ("state-mutating-get-routes", check_state_mutating_get_routes),
    ("raw-tier-string-compare", check_raw_tier_string_compare),
    ("unbalanced-type-work", check_unbalanced_type_work),
]

# Plain-English, one-line "what this check looks for" — surfaced in the
# alert email so a finding is self-explanatory without opening the source
# (#302: the email used to print only the terse check id).
CHECK_DESCRIPTIONS = {
    "bare-1fr-grids":
        "CSS grid columns that can overflow sideways on narrow screens (#138).",
    "embedded-url-credentials":
        "A username or token baked into a URL in committed source (secret-leak risk).",
    "string-match-only-prod-tests":
        "Prod-smoke tests that only string-match source instead of exercising behavior.",
    "state-mutating-get-routes":
        "A route that accepts GET for a state change — a CSRF surface (#190).",
    "raw-tier-string-compare":
        'Tier compared as a raw string instead of the Tier enum (bug #57 class).',
    "unbalanced-type-work":
        'JS `.type === "work"` with no "personal" branch nearby (bug #57 class).',
}


def send_scan_email(findings: list[Finding], *, per_check_counts: list[tuple[str, int]]) -> None:
    """Best-effort Brevo email — sent on EVERY weekly run, clean or
    not. User-requested 2026-05-26: "an email should go out every week
    with the run regardless if it is clean so I know it is happening."

    On clean runs the subject is ``[Taskmanager bug-pattern] CLEAN``
    and the body lists each check + 0 findings. On findings runs the
    subject reports the count and the body lists each offender. Same
    Brevo pattern as `scripts/check_advisories.py`; failures here
    LOG but do NOT change the exit code.
    """
    api_key = os.environ.get("BREVO_API_KEY")
    from_addr = os.environ.get("DIGEST_FROM_EMAIL")
    to_addr = os.environ.get("DIGEST_TO_EMAIL")
    if not (api_key and from_addr and to_addr):
        sys.stderr.write("[bug-pattern-scan] Brevo not configured; skipping email\n")
        return

    today = datetime.date.today().isoformat()
    # Group findings for the shared renderer: (loc, [code, FIX]) per check.
    findings_by_check: dict[str, list[tuple[str, list[str]]]] = {}
    for f in findings:
        loc = f"{f.path}:{f.line_num}" if f.line_num else f.path
        findings_by_check.setdefault(f.check_id, []).append(
            (loc, [f.line.strip(), f"FIX: {f.message}"]))

    sys.path.insert(0, str(PROJECT_ROOT))
    from scripts import audit_email  # noqa: PLC0415
    subject, body = audit_email.render(
        today=today,
        tag="bug-pattern",
        title="Weekly bug-pattern scan",
        unit_word="scan",
        cadence_adj="weekly",
        scope_blurb="code patterns that have caused bugs before",
        per_check_counts=per_check_counts,
        findings_by_check=findings_by_check,
        descriptions=CHECK_DESCRIPTIONS,
        todo_steps=[
            "Open each file:line above and apply its FIX (or, if it's a "
            "false positive, tune the check in scripts/check_bug_patterns.py).",
            "Re-run `python scripts/check_bug_patterns.py` locally to confirm "
            "it goes clean.",
        ],
    )

    payload = {
        "sender": {"email": from_addr, "name": "Taskmanager CI"},
        "to": [{"email": to_addr}],
        "subject": subject,
        "textContent": body,
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
            sys.stdout.write(f"[bug-pattern-scan] email sent: HTTP {resp.status}\n")
    except urllib.error.URLError as e:
        sys.stderr.write(f"[bug-pattern-scan] email send failed: {e}\n")


# Back-compat shim — `send_findings_email` was the pre-#236 name; keep
# a wrapper so any external caller / test patch that still uses the
# old name keeps working (and so test mocks can target either name).
def send_findings_email(findings: list[Finding]) -> None:  # noqa: D401
    """Deprecated alias for ``send_scan_email``. Sends with no per-check
    count detail (use ``send_scan_email`` directly for the full
    confirm-on-clean message)."""
    send_scan_email(findings, per_check_counts=[])


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Run the #226 weekly bug-pattern scan.",
    )
    parser.add_argument(
        "--autofile", action="store_true",
        help=(
            "#242: upsert findings into BACKLOG.md's "
            "`## Auto-filed by recurring audits` section after the "
            "email step. Used by the weekly cron workflow."
        ),
    )
    args = parser.parse_args(argv)

    sys.stdout.write(
        f"[bug-pattern-scan] starting "
        f"{datetime.datetime.now(datetime.UTC).isoformat()}\n"
    )

    all_findings: list[Finding] = []
    per_check_counts: list[tuple[str, int]] = []
    for label, check_fn in CHECKS:
        try:
            findings = check_fn()
        except (OSError, ValueError, RuntimeError) as e:
            sys.stderr.write(f"[bug-pattern-scan] {label} errored: {e}\n")
            return 2
        sys.stdout.write(f"[bug-pattern-scan] {label}: {len(findings)} finding(s)\n")
        for f in findings:
            if f.line_num:
                sys.stdout.write(f"    {f.path}:{f.line_num}  {f.line}\n")
            else:
                sys.stdout.write(f"    {f.path}  {f.line}\n")
        all_findings.extend(findings)
        per_check_counts.append((label, len(findings)))

    # User-requested 2026-05-26: send an email EVERY run, clean or not,
    # so the absence of an email proves the cron failed (or the
    # workflow drifted). Pre-#236 behavior was silent-on-clean — which
    # left "is the cron actually running?" as a latent question.
    send_scan_email(all_findings, per_check_counts=per_check_counts)
    if args.autofile:
        # Import via sys.path so the script works either as
        # `python scripts/check_bug_patterns.py` (cwd=PROJECT_ROOT,
        # scripts/ on sys.path[0] which does NOT see `scripts` as a
        # package) or via `python -m scripts.check_bug_patterns`.
        sys.path.insert(0, str(PROJECT_ROOT))
        from scripts import backlog_autofile  # noqa: PLC0415
        backlog_autofile.run_for_audit("bug-pattern", all_findings)
    if not all_findings:
        sys.stdout.write(
            "[bug-pattern-scan] CLEAN — confirmation email sent.\n"
        )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
