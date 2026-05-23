"""Weekly dependency-advisory check (#210).

Runs in GitHub Actions on a weekly cron (separate from
``scripts/run_all_gates.sh``, which only fires on commit). Re-runs the
same ``pip-audit`` + ``npm audit`` checks the on-commit gate runs — so
a CVE published against an unchanged dependency between commits gets
caught proactively instead of whenever someone next ships.

Pipeline::

    pip-audit -r requirements-dev.txt --format json  →  findings
    npm audit --audit-level=high --json              →  findings
                                ↓
        any findings? → send SendGrid email (reusing the daily-backup
                        / digest pattern) + exit 1
        clean?        → exit 0 silently (no email)

Exit codes (so the GitHub Actions UI shows red on findings):
    0 — both audits clean.
    1 — one or both reported a vulnerability. Email sent if SendGrid
        is configured.
    2 — internal error (e.g. couldn't run pip-audit at all).

Email-send failures DO NOT change the exit code — same convention as
``scripts/backup_to_github.py``.

Wired via ``.github/workflows/weekly-advisory-check.yml`` (Mondays
13:00 UTC). Manual trigger via the Actions UI ("workflow_dispatch")
for one-off verification.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys

# ``-r requirements-dev.txt`` itself ``-r``-includes ``requirements.txt``
# so this single audit covers both the runtime and the dev/test manifest
# — same set the on-commit pip-audit gate scans.
_PIP_AUDIT_CMD = [
    sys.executable, "-m", "pip_audit",
    "-r", "requirements-dev.txt",
    # PYSEC-2026-89 (markdown false positive — fixed in 3.8.1, we run
    # 3.10.2). Mirrors run_all_gates.sh.
    "--ignore-vuln", "PYSEC-2026-89",
    "--format", "json",
]

# npm audit exits non-zero for ANY vuln including low/moderate;
# `--audit-level=high` makes its exit reflect only high/critical, but
# the JSON output still includes everything — we filter ourselves.
_NPM_AUDIT_CMD = ["npm", "audit", "--audit-level=high", "--json"]


def run_pip_audit() -> tuple[bool, list[dict], str]:
    """Run pip-audit. Return ``(clean, findings, raw_stdout)``.

    ``clean`` is True iff exit-zero AND no findings.
    ``findings`` is a list of dicts: ``{name, version, id, fix_versions, description}``.
    """
    proc = subprocess.run(  # noqa: S603 — _PIP_AUDIT_CMD is a constant
        _PIP_AUDIT_CMD, capture_output=True, text=True, check=False,
    )
    raw_text = (proc.stdout or "") + (proc.stderr or "")
    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return False, [], raw_text
    # pip-audit JSON shape: {"dependencies": [{"name", "version", "vulns": [...]}, ...]}
    findings = []
    for dep in data.get("dependencies", []) or []:
        for v in dep.get("vulns", []) or []:
            findings.append({
                "name": dep.get("name"),
                "version": dep.get("version"),
                "id": v.get("id"),
                "fix_versions": v.get("fix_versions") or [],
                "description": (v.get("description") or "")[:200],
            })
    clean = proc.returncode == 0 and not findings
    return clean, findings, raw_text


def run_npm_audit() -> tuple[bool, list[dict], str]:
    """Run npm audit. Return ``(clean, findings, raw_stdout)`` — HIGH and
    CRITICAL severities count as findings (mirrors the on-commit gate)."""
    proc = subprocess.run(  # noqa: S603 — _NPM_AUDIT_CMD is a constant
        _NPM_AUDIT_CMD, capture_output=True, text=True, check=False,
    )
    raw_text = (proc.stdout or "") + (proc.stderr or "")
    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return False, [], raw_text
    # npm audit JSON shape: {"vulnerabilities": {<pkg>: {"severity": ..., ...}}, ...}
    findings = []
    for pkg, info in (data.get("vulnerabilities") or {}).items():
        severity = (info or {}).get("severity") or "unknown"
        if severity in ("high", "critical"):
            findings.append({"name": pkg, "severity": severity})
    return (not findings), findings, raw_text


def send_advisory_email(pip_findings: list[dict], npm_findings: list[dict]) -> None:
    """Send a plain-text summary email via SendGrid. Best-effort —
    failures here are LOGGED but DO NOT change the script's exit code."""
    sg_key = os.environ.get("SENDGRID_API_KEY")
    from_addr = os.environ.get("DIGEST_FROM_EMAIL")
    to_addr = os.environ.get("DIGEST_TO_EMAIL")
    if not (sg_key and from_addr and to_addr):
        sys.stderr.write("[advisory-check] SendGrid not configured; skipping email\n")
        return

    today = datetime.date.today().isoformat()
    n_total = len(pip_findings) + len(npm_findings)
    body_lines = [
        f"Weekly dependency-advisory scan {today} found {n_total} new finding(s).",
        "",
        f"pip-audit (-r requirements-dev.txt): {len(pip_findings)} vulnerability/ies",
    ]
    for f in pip_findings:
        fix = ", ".join(f.get("fix_versions") or []) or "(no fix listed)"
        body_lines.append(
            f"  - {f.get('name')} {f.get('version')} — {f.get('id')} (fix: {fix})"
        )
    body_lines += [
        "",
        f"npm audit (--audit-level=high): {len(npm_findings)} high/critical finding(s)",
    ]
    for f in npm_findings:
        body_lines.append(f"  - {f.get('name')} ({f.get('severity')})")
    body_lines += [
        "",
        "Action: bump the affected package(s) in requirements-dev.txt / "
        "package.json, then re-run `bash scripts/run_all_gates.sh` to "
        "confirm. See the GitHub Actions run for the full raw output.",
    ]

    payload = {
        "personalizations": [{"to": [{"email": to_addr}]}],
        "from": {"email": from_addr},
        "subject": f"[Taskmanager advisory] {n_total} new CVE(s) — {today}",
        "content": [{"type": "text/plain", "value": "\n".join(body_lines)}],
    }
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {sg_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        # URL is the constant SendGrid endpoint, not user input.
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310  # nosec B310  # nosemgrep
            sys.stdout.write(f"[advisory-check] email sent: HTTP {resp.status}\n")
    except urllib.error.URLError as e:
        sys.stderr.write(f"[advisory-check] email send failed: {e}\n")


def main() -> int:
    sys.stdout.write(
        f"[advisory-check] starting {datetime.datetime.now(datetime.UTC).isoformat()}\n"
    )

    pip_clean, pip_findings, pip_raw = run_pip_audit()
    npm_clean, npm_findings, npm_raw = run_npm_audit()

    sys.stdout.write(
        f"[advisory-check] pip-audit: {len(pip_findings)} finding(s); "
        f"npm audit: {len(npm_findings)} high/critical finding(s)\n"
    )
    # Always print raw output to the Actions log — keeps the email
    # short while leaving the full detail one click away.
    sys.stdout.write("\n--- pip-audit raw ---\n")
    sys.stdout.write(pip_raw[:4000] + "\n")
    sys.stdout.write("\n--- npm audit raw ---\n")
    sys.stdout.write(npm_raw[:4000] + "\n")

    if pip_clean and npm_clean:
        sys.stdout.write("[advisory-check] CLEAN — no email sent.\n")
        return 0
    send_advisory_email(pip_findings, npm_findings)
    return 1


if __name__ == "__main__":
    sys.exit(main())
