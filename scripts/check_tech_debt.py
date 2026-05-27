"""Weekly recurring tech-debt audit (#228).

User-flagged 2026-05-24 (one of four "recurring audit" requests).
Different from the bug-pattern scanner (#226) and security-posture
audit (#227): this watches CODE QUALITY drift signals over time.

Three mechanical checks ship in the first cut:

  todo-fixme-accumulation
      Walk all tracked source files (`*.py`, `*.js`, `*.html`),
      count `TODO`/`FIXME`/`XXX`/`HACK` markers via word-boundary
      regex. Flag when (a) the total exceeds the soft threshold
      (default 25) OR (b) any single file holds > 5 markers (a
      hotspot worth refactoring). Tests + markdown docs are
      excluded — they legitimately discuss the patterns.

  dependency-drift
      Run `pip list --outdated --format=json` and `npm outdated
      --json` to find dependencies stuck behind newer releases.
      Flag any package whose `latest_version` is a MAJOR-version
      bump ahead of the installed `version`. This is lighter than
      #210's CVE check — it catches "we're 3 majors behind" hygiene
      drift before it becomes a forced migration.

  stale-tests
      For each `tests/test_*.py`, run `git log -1 --format=%cI` and
      flag any whose last commit was > 180 days ago. Stale tests
      often reflect old behavior; a still-passing test that hasn't
      been touched in 6 months while its source module churns is a
      signal the test isn't asserting what you think.

  code-duplication (#228b, 2026-05-27)
      Run `npx jscpd --reporters json` against the Python + JS
      source tree (HTML excluded — Jinja2-included partials
      generate noisy false positives at the template level).
      Flag any duplication of 30+ lines. The duplication detector
      catches "copy-pasted helper" hotspots before they entrench
      into divergent forks of the same logic.

Same email pattern as #226 + #227: sends an email EVERY run (clean
or not) so the absence of one proves the cron failed. Exit 0 on
clean, 1 on findings, 2 on internal error.

Wired via ``.github/workflows/weekly-tech-debt-audit.yml`` (Saturdays
13:00 UTC — sits BETWEEN the bug-pattern Sun and advisory-check Mon,
spreading the audit email cadence across the week).
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


# --- Thresholds (single source of truth for the audit policy) ---------------

# Check (a) — TODO/FIXME accumulation.
_TODO_TOTAL_THRESHOLD = 25       # flag when grand total exceeds this
_TODO_PER_FILE_THRESHOLD = 5     # flag any file holding more than this

# Check (b) — dependency drift.
# (No numeric threshold — flag every major-version-behind dep.)

# Check (c) — stale tests.
_STALE_TEST_DAYS = 180

# Check (d) — code duplication via jscpd (#228b, 2026-05-27).
# Only flag duplications of this many or more lines. Below this
# threshold the noise (boilerplate imports, similar dict literals,
# repeated test fixtures) overwhelms the real signal.
_JSCPD_MIN_LINES = 30
# Globs jscpd ignores. node_modules, tests, migrations, docs are
# the obvious exclusions. coverage-js + .venv + __pycache__ are
# generated. HTML is excluded via `--formats` rather than `--ignore`
# because Jinja2 `{% include %}` partials get detected as duplicates
# in every parent template — semantic-false-positive noise.
_JSCPD_IGNORE_GLOBS = (
    "node_modules/**", "tests/**", "migrations/**", "docs/**",
    "coverage-js/**", ".venv/**", "__pycache__/**",
)


# ---------------------------------------------------------------------------
# Check (a): TODO / FIXME accumulation
# ---------------------------------------------------------------------------

_TODO_MARKER_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")

# Production-code globs. Docs (`.md`), JSON, and tests are excluded —
# they legitimately reference the pattern (CLAUDE.md threat model
# discussion, BACKLOG.md item references, etc.).
_TODO_SCAN_SUFFIXES = (".py", ".js", ".html", ".css")
_TODO_SKIP_DIRS = ("tests/", "node_modules/", ".venv/", "__pycache__/",
                   "migrations/")
# Skip the audit script itself + its tests (they contain the regex
# literal "TODO" in comments / docstrings).
_TODO_SKIP_PATHS = frozenset({
    "scripts/check_tech_debt.py",
    "tests/test_tech_debt_audit.py",
})


def _walk_tracked_files() -> list[Path]:
    try:
        proc = subprocess.run(  # noqa: S603, S607 — git is trusted
            ["git", "ls-files"],
            capture_output=True, text=True, check=False,
            cwd=PROJECT_ROOT,
        )
    except (FileNotFoundError, OSError):
        return []
    if proc.returncode != 0:
        return []
    out = []
    for rel in proc.stdout.splitlines():
        p = PROJECT_ROOT / rel
        if p.is_file():
            out.append(p)
    return out


def check_todo_fixme_accumulation() -> list[Finding]:
    """Walk tracked production source files for TODO/FIXME markers.
    Flag when the total crosses ``_TODO_TOTAL_THRESHOLD`` OR any single
    file holds more than ``_TODO_PER_FILE_THRESHOLD`` markers.
    """
    findings: list[Finding] = []
    per_file: dict[str, int] = {}
    grand_total = 0

    for p in _walk_tracked_files():
        if p.suffix not in _TODO_SCAN_SUFFIXES:
            continue
        rel = p.relative_to(PROJECT_ROOT).as_posix()
        if any(rel.startswith(d) for d in _TODO_SKIP_DIRS):
            continue
        if rel in _TODO_SKIP_PATHS:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        count = len(_TODO_MARKER_RE.findall(text))
        if count > 0:
            per_file[rel] = count
            grand_total += count

    # File-level hotspots get one finding each.
    for rel, count in sorted(per_file.items(), key=lambda kv: -kv[1]):
        if count > _TODO_PER_FILE_THRESHOLD:
            findings.append(Finding(
                check_id="todo-fixme-accumulation",
                path=rel,
                detail=(
                    f"{count} TODO/FIXME markers in this file — refactor "
                    f"the hotspot (threshold: {_TODO_PER_FILE_THRESHOLD} "
                    "per file)"
                ),
            ))

    # Grand-total ceiling — separate finding so the operator sees both
    # axes (hot files AND overall debt level).
    if grand_total > _TODO_TOTAL_THRESHOLD:
        # List the top 5 contributors in the detail for context.
        top = sorted(per_file.items(), key=lambda kv: -kv[1])[:5]
        top_str = "; ".join(f"{f} ({n})" for f, n in top)
        findings.append(Finding(
            check_id="todo-fixme-accumulation",
            detail=(
                f"{grand_total} TODO/FIXME markers across the tree "
                f"(threshold: {_TODO_TOTAL_THRESHOLD}). Top: {top_str}"
            ),
        ))
    return findings


# ---------------------------------------------------------------------------
# Check (b): dependency drift
# ---------------------------------------------------------------------------


def _semver_major(v: str) -> int | None:
    """Return the integer major version, or None if unparseable.
    Trims any leading 'v' and ignores anything after the first dot."""
    if not isinstance(v, str):
        return None
    s = v.strip().lstrip("v")
    try:
        return int(s.split(".", 1)[0])
    except (ValueError, IndexError):
        return None


def check_dependency_drift() -> list[Finding]:
    """Flag major-version-behind dependencies via `pip list --outdated`
    and `npm outdated`. Skips when the tooling isn't available
    (returns []) — the GitHub Actions workflow installs both, so the
    cron always exercises the full path.
    """
    findings: list[Finding] = []

    # --- pip ---
    try:
        proc = subprocess.run(  # noqa: S603, S607
            [sys.executable, "-m", "pip", "list", "--outdated",
             "--format=json"],
            capture_output=True, text=True, check=False,
            cwd=PROJECT_ROOT,
            timeout=120,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                packages = json.loads(proc.stdout)
            except json.JSONDecodeError:
                packages = []
            for pkg in packages:
                name = pkg.get("name", "?")
                installed = pkg.get("version", "?")
                latest = pkg.get("latest_version", "?")
                cur_major = _semver_major(installed)
                lat_major = _semver_major(latest)
                if (cur_major is not None and lat_major is not None
                        and lat_major > cur_major):
                    findings.append(Finding(
                        check_id="dependency-drift",
                        detail=(
                            f"pip dep {name!r} stuck at {installed} — "
                            f"latest is {latest} ({lat_major - cur_major} "
                            "major version(s) behind)"
                        ),
                    ))
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        pass

    # --- npm ---
    try:
        proc = subprocess.run(  # noqa: S603, S607
            ["npm", "outdated", "--json"],
            capture_output=True, text=True, check=False,
            cwd=PROJECT_ROOT,
            timeout=120,
        )
        # `npm outdated` exits 1 when there ARE outdated packages; that's
        # not an error from our POV. Parse stdout regardless of rc.
        if proc.stdout.strip():
            try:
                packages = json.loads(proc.stdout)
            except json.JSONDecodeError:
                packages = {}
            for name, info in packages.items():
                installed = info.get("current") or info.get("wanted") or "?"
                latest = info.get("latest") or "?"
                cur_major = _semver_major(installed)
                lat_major = _semver_major(latest)
                if (cur_major is not None and lat_major is not None
                        and lat_major > cur_major):
                    findings.append(Finding(
                        check_id="dependency-drift",
                        detail=(
                            f"npm dep {name!r} stuck at {installed} — "
                            f"latest is {latest} ({lat_major - cur_major} "
                            "major version(s) behind)"
                        ),
                    ))
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        pass

    return findings


# ---------------------------------------------------------------------------
# Check (c): stale tests
# ---------------------------------------------------------------------------


def _last_commit_date(rel_path: str) -> datetime.date | None:
    try:
        proc = subprocess.run(  # noqa: S603, S607
            ["git", "log", "-1", "--format=%cI", "--", rel_path],
            capture_output=True, text=True, check=False,
            cwd=PROJECT_ROOT,
        )
    except (FileNotFoundError, OSError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return datetime.date.fromisoformat(proc.stdout.strip()[:10])
    except ValueError:
        return None


def check_stale_tests() -> list[Finding]:
    """Flag test files (``tests/test_*.py``, ``tests/**/test_*.js``)
    whose last commit was > ``_STALE_TEST_DAYS`` days ago.
    """
    findings: list[Finding] = []
    today = datetime.date.today()
    tests_dir = PROJECT_ROOT / "tests"
    if not tests_dir.exists():
        return findings
    for p in tests_dir.rglob("test_*.py"):
        rel = p.relative_to(PROJECT_ROOT).as_posix()
        last = _last_commit_date(rel)
        if last is None:
            continue
        days_since = (today - last).days
        if days_since > _STALE_TEST_DAYS:
            findings.append(Finding(
                check_id="stale-tests",
                path=rel,
                detail=(
                    f"last touched {last.isoformat()} "
                    f"({days_since} days ago) — likely doesn't reflect "
                    "current behavior. Audit + refresh."
                ),
            ))
    return findings


# ---------------------------------------------------------------------------
# Check (d): code duplication via jscpd (#228b)
# ---------------------------------------------------------------------------


def check_code_duplication() -> list[Finding]:
    """Run `npx jscpd --reporters json` over the Python + JS source
    tree and flag any duplication of ``_JSCPD_MIN_LINES`` lines or
    more.

    Returns empty list when:
      - jscpd / npx isn't on the runner (missing tooling — skip silent
        rather than emit a confusing finding)
      - jscpd returns no JSON (parse error)
      - jscpd hits a non-zero exit but doesn't produce a report file

    The GitHub Actions workflow installs npm + jscpd so the CI path
    always exercises the full check; the silent-skip is defense-in-
    depth for a developer running the audit locally without the
    Node dep.
    """
    findings: list[Finding] = []

    # jscpd writes to <output-dir>/jscpd-report.json. Use a per-run
    # tempdir so concurrent runs (or stale state from a prior run)
    # can't poison the result.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="jscpd-") as tmpdir:
        ignore_arg = ",".join(_JSCPD_IGNORE_GLOBS)
        # Use `npm exec --no --` (cross-platform) instead of `npx`
        # directly. npx on Windows resolves to a `.cmd` wrapper that
        # subprocess can't invoke without shell=True (security finding
        # from bandit). `npm exec` is just a Node script — same exe
        # name on Windows + Linux + macOS, no shell needed.
        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        try:
            subprocess.run(  # noqa: S603
                [
                    npm_cmd, "exec", "--no", "--",
                    "jscpd",
                    "--reporters", "json",
                    "--silent",
                    "--min-lines", str(_JSCPD_MIN_LINES),
                    # Restrict to Python + JS — HTML duplicates via
                    # Jinja2 `{% include %}` are semantic false
                    # positives (the partial isn't actually inlined;
                    # jscpd matches structural shape).
                    "--formats-exts", "python:py;javascript:js",
                    "--output", tmpdir,
                    "--ignore", ignore_arg,
                    ".",
                ],
                capture_output=True, text=True, check=False,
                cwd=PROJECT_ROOT,
                timeout=180,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return findings
        report = Path(tmpdir) / "jscpd-report.json"
        if not report.exists():
            return findings
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return findings

    for dup in data.get("duplicates") or []:
        if not isinstance(dup, dict):
            continue
        lines = int(dup.get("lines") or 0)
        if lines < _JSCPD_MIN_LINES:
            continue
        a = dup.get("firstFile") or {}
        b = dup.get("secondFile") or {}
        a_name = a.get("name") or "?"
        b_name = b.get("name") or "?"
        a_start = a.get("start")
        a_end = a.get("end")
        b_start = b.get("start")
        b_end = b.get("end")
        findings.append(Finding(
            check_id="code-duplication",
            path=a_name,
            detail=(
                f"{lines}-line duplicate block: "
                f"{a_name}:{a_start}-{a_end} <-> "
                f"{b_name}:{b_start}-{b_end} — extract to a shared "
                "helper or rationalise the divergence."
            ),
        ))
    return findings


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

CHECKS = [
    ("todo-fixme-accumulation", check_todo_fixme_accumulation),
    ("dependency-drift", check_dependency_drift),
    ("stale-tests", check_stale_tests),
    ("code-duplication", check_code_duplication),
]


def send_audit_email(
    findings: list[Finding],
    *,
    per_check_counts: list[tuple[str, int]],
) -> None:
    """Always-email (clean or not) — mirrors #226c / #227."""
    sg_key = os.environ.get("SENDGRID_API_KEY")
    from_addr = os.environ.get("DIGEST_FROM_EMAIL")
    to_addr = os.environ.get("DIGEST_TO_EMAIL")
    if not (sg_key and from_addr and to_addr):
        sys.stderr.write(
            "[tech-debt] SendGrid not configured; skipping email\n"
        )
        return

    today = datetime.date.today().isoformat()
    total = len(findings)
    by_check: dict[str, list[Finding]] = {}
    for f in findings:
        by_check.setdefault(f.check_id, []).append(f)

    if total == 0:
        subject = f"[Taskmanager tech-debt] CLEAN — {today}"
        body_lines = [
            f"Weekly tech-debt audit {today}: ALL CHECKS CLEAN "
            f"({len(per_check_counts)} checks, 0 findings).",
            "",
            "This confirmation email fires on every weekly run so the "
            "absence of an email = the cron failed.",
            "",
            "Per-check breakdown:",
        ]
        for label, count in per_check_counts:
            body_lines.append(f"  ✓ {label}: {count} finding(s)")
    else:
        subject = f"[Taskmanager tech-debt] {total} finding(s) — {today}"
        body_lines = [
            f"Weekly tech-debt audit {today} found {total} finding(s) "
            f"across {len(by_check)} check(s).",
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
            "and re-run `python scripts/check_tech_debt.py` to confirm "
            "clean. See the GitHub Actions run for the full raw output.",
        ]

    payload = {
        "personalizations": [{"to": [{"email": to_addr}]}],
        "from": {"email": from_addr},
        "subject": subject,
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
            sys.stdout.write(
                f"[tech-debt] email sent: HTTP {resp.status}\n"
            )
    except urllib.error.URLError as e:
        sys.stderr.write(f"[tech-debt] email send failed: {e}\n")


def main() -> int:
    sys.stdout.write(
        f"[tech-debt] starting "
        f"{datetime.datetime.now(datetime.UTC).isoformat()}\n"
    )

    all_findings: list[Finding] = []
    per_check_counts: list[tuple[str, int]] = []
    for label, check_fn in CHECKS:
        try:
            findings = check_fn()
        except (OSError, ValueError, RuntimeError) as e:
            sys.stderr.write(f"[tech-debt] {label} errored: {e}\n")
            return 2
        sys.stdout.write(
            f"[tech-debt] {label}: {len(findings)} finding(s)\n"
        )
        for f in findings:
            if f.path:
                line_suffix = f":{f.line_num}" if f.line_num else ""
                sys.stdout.write(f"    {f.path}{line_suffix}\n")
            sys.stdout.write(f"      -> {f.detail}\n")
        all_findings.extend(findings)
        per_check_counts.append((label, len(findings)))

    send_audit_email(all_findings, per_check_counts=per_check_counts)
    if not all_findings:
        sys.stdout.write(
            "[tech-debt] CLEAN — confirmation email sent.\n"
        )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
