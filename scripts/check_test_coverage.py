"""Weekly recurring test-coverage audit (#229).

User-flagged 2026-05-24 as the fourth recurring audit (after #226
bug-pattern, #227 security-posture, #228 tech-debt). The per-commit
pytest gate enforces an 80% floor but offers no view of which lines
are uncovered, where coverage is dropping, or which CRITICAL paths
have no tests at all.

Three checks ship in scripts/check_test_coverage.py:

  overall-coverage-drift
      Compares the current overall coverage percentage to the
      committed baseline in ``docs/audit/coverage-baseline.json``.
      Flags when current < baseline - 1pp. Catches gradual decline
      that the 80% floor wouldn't notice (e.g. 89% → 81% slide).

  per-file-coverage-drift
      Compares each file's coverage to its committed baseline. Flags
      any file where current < baseline - 5pp. Catches "one file
      went from 95% → 70%" while overall barely moves. New files
      (not in baseline) are NOT flagged here — those land in the
      operator's first baseline-refresh pass.

  critical-path-floor
      File-level floor (NOT line-level — line-level needs AST mapping
      and adds zero signal over file-level for our risk profile).
      The ``_CRITICAL_PATH_FLOORS`` map below is the policy: each
      entry is a file path → minimum percent. Any file below its
      floor fires a finding. These are the files where silent
      regression hurts: auth, task mutations, encryption, recurring
      spawn, reflection apply.

Mirrors #226 / #227 / #228 patterns: always emails (clean or not),
exit 0 on clean / 1 on findings / 2 on internal error.

Wired via ``.github/workflows/weekly-coverage-audit.yml`` — Fridays
13:00 UTC.

Maintaining the baseline:
  Run ``python scripts/check_test_coverage.py --write-baseline`` to
  regenerate ``docs/audit/coverage-baseline.json`` from the current
  coverage state. Commit the regenerated file when you've
  intentionally improved coverage so future regressions are
  measured against the new high-water mark.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
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


# --- Policy ----------------------------------------------------------------

_OVERALL_DRIFT_TOLERANCE_PP = 1.0   # flag when current < baseline - 1pp
_PER_FILE_DRIFT_TOLERANCE_PP = 5.0  # flag when file < baseline - 5pp

# Critical-path file-level floors. Each file MUST stay above its
# floor; dropping below = WARNING in /api/debug/logs + email finding.
# Refine the list when a regression hurts somewhere new — keep it
# narrow so the floor stays meaningful.
_CRITICAL_PATH_FLOORS: dict[str, float] = {
    "auth.py": 90.0,                # OAuth + AUTHORIZED_EMAIL gate
    "task_service.py": 85.0,         # central mutation path
    "crypto.py": 95.0,               # Fernet encrypt/decrypt — tiny + critical
    "recurring_service.py": 80.0,    # spawn cron correctness
    "reflection_service.py": 80.0,   # Claude apply pipeline (#174 audit fix)
    # voice_service.py: floor bumped 70 → 90 by #239 (2026-05-27).
    # Direct unit tests on `_call_whisper_api` (egress shape + cost
    # calc + EgressError translation + iOS-Safari MIME quirks)
    # brought file coverage to 100%. Setting floor at 90% leaves
    # headroom for incidental regressions while still flagging real
    # drift — Whisper-mocked tests aren't cheap to write per LOC, so
    # 90 (not 95) is the pragmatic high-water-mark anchor.
    "voice_service.py": 90.0,
}

_BASELINE_PATH = PROJECT_ROOT / "docs" / "audit" / "coverage-baseline.json"


# --- Coverage runner -------------------------------------------------------


def _run_pytest_with_coverage() -> dict | None:
    """Run pytest with JSON coverage report and return the parsed
    coverage data. Returns None on failure (test failed, pytest
    missing, etc.).

    The audit doesn't INTERPRET test failures — it only reads
    coverage. A failing test would also block the per-commit gate
    so the audit's job is just to surface the coverage drift.
    """
    coverage_json = PROJECT_ROOT / "coverage.json"
    if coverage_json.exists():
        coverage_json.unlink()
    try:
        # NOTE: `--no-cov-on-fail` was REMOVED 2026-05-27 because it
        # made the audit useless when ANY test failed — coverage.json
        # never landed, and the audit exited 2 ("internal error")
        # instead of giving us the coverage signal we ACTUALLY came
        # for. The audit doesn't care about test pass/fail; it just
        # needs the coverage data. Test failures are caught by the
        # per-commit gate; the audit's job is the drift signal.
        proc = subprocess.run(  # noqa: S603
            [
                sys.executable, "-m", "pytest",
                "--cov=.",
                "--cov-report=json:coverage.json",
                "--cov-report=term",
                "-q",
            ],
            capture_output=True, text=True, check=False,
            cwd=PROJECT_ROOT,
            timeout=600,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as e:
        sys.stderr.write(f"[coverage-audit] pytest failed to launch: {e}\n")
        return None
    # pytest exits non-zero on test failures; we don't care here.
    # What matters is whether coverage.json was produced.
    if not coverage_json.exists():
        sys.stderr.write(
            "[coverage-audit] coverage.json not produced — "
            "pytest may have crashed before coverage could write:\n"
            f"{proc.stdout[-500:]}\n{proc.stderr[-500:]}\n",
        )
        return None
    try:
        return json.loads(coverage_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        sys.stderr.write(f"[coverage-audit] coverage.json unparseable: {e}\n")
        return None


def _extract_per_file_and_total(cov_data: dict) -> tuple[dict[str, float], float]:
    """Extract `{file_path: percent}` + overall percent from the
    pytest-cov JSON shape.

    pytest-cov JSON shape::

        {
          "files": {
            "auth.py": {"summary": {"percent_covered": 92.5, ...}},
            ...
          },
          "totals": {"percent_covered": 84.3, ...}
        }
    """
    per_file: dict[str, float] = {}
    for path, info in (cov_data.get("files") or {}).items():
        summary = (info or {}).get("summary") or {}
        pct = summary.get("percent_covered")
        if isinstance(pct, int | float):
            per_file[path] = float(pct)
    total = float(
        (cov_data.get("totals") or {}).get("percent_covered") or 0.0,
    )
    return per_file, total


# --- Baseline I/O ----------------------------------------------------------


def _read_baseline() -> dict | None:
    """Returns ``{overall: float, per_file: {path: percent}}`` or None
    if the baseline file is missing/unparseable."""
    if not _BASELINE_PATH.exists():
        return None
    try:
        data = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _write_baseline(overall: float, per_file: dict[str, float]) -> None:
    """Regenerate the baseline JSON from the current coverage state.
    Called from the --write-baseline CLI flag."""
    _BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_doc": [
            "Coverage baseline for the #229 weekly test-coverage audit.",
            "",
            "Regenerate this file when you've intentionally improved",
            "coverage and want future regressions measured against the",
            "new high-water mark:",
            "",
            "    python scripts/check_test_coverage.py --write-baseline",
            "",
            "Drift thresholds:",
            "  overall: 1 percentage point (current < baseline - 1pp = flag)",
            "  per file: 5 percentage points",
            "Critical-path floors live in scripts/check_test_coverage.py",
            "and are NOT baseline-relative — they're absolute minimums.",
        ],
        "overall": round(overall, 2),
        "per_file": {p: round(v, 2) for p, v in sorted(per_file.items())},
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    _BASELINE_PATH.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8",
    )


# --- Checks ----------------------------------------------------------------


def check_overall_drift(
    overall_pct: float, baseline: dict,
) -> list[Finding]:
    """Overall coverage dropped below baseline - tolerance."""
    if not isinstance(baseline.get("overall"), int | float):
        return []
    baseline_pct = float(baseline["overall"])
    diff = baseline_pct - overall_pct
    if diff > _OVERALL_DRIFT_TOLERANCE_PP:
        return [Finding(
            check_id="overall-coverage-drift",
            detail=(
                f"overall coverage dropped {diff:.1f}pp "
                f"({baseline_pct:.1f}% baseline → {overall_pct:.1f}% "
                f"current; tolerance {_OVERALL_DRIFT_TOLERANCE_PP:.1f}pp)"
            ),
        )]
    return []


def check_per_file_drift(
    per_file: dict[str, float], baseline: dict,
) -> list[Finding]:
    """Per-file coverage dropped below baseline - tolerance for any
    file that EXISTS in the baseline. New files don't fire (they
    haven't established a baseline yet — operator's first
    --write-baseline pass covers them)."""
    findings: list[Finding] = []
    baseline_files = baseline.get("per_file") or {}
    if not isinstance(baseline_files, dict):
        return findings
    for path, baseline_pct in baseline_files.items():
        if not isinstance(baseline_pct, int | float):
            continue
        if path not in per_file:
            continue  # file disappeared (deleted/moved); not our problem
        current = per_file[path]
        diff = float(baseline_pct) - current
        if diff > _PER_FILE_DRIFT_TOLERANCE_PP:
            findings.append(Finding(
                check_id="per-file-coverage-drift",
                path=path,
                detail=(
                    f"coverage dropped {diff:.1f}pp "
                    f"({baseline_pct:.1f}% → {current:.1f}%; "
                    f"tolerance {_PER_FILE_DRIFT_TOLERANCE_PP:.1f}pp)"
                ),
            ))
    return findings


def check_critical_path_floors(
    per_file: dict[str, float],
) -> list[Finding]:
    """Any critical-path file below its absolute floor. Independent
    of the baseline — these floors are policy, not drift."""
    findings: list[Finding] = []
    for path, floor_pct in _CRITICAL_PATH_FLOORS.items():
        if path not in per_file:
            continue  # file doesn't exist — can't audit; skip
        current = per_file[path]
        if current < floor_pct:
            findings.append(Finding(
                check_id="critical-path-floor",
                path=path,
                detail=(
                    f"critical-path file at {current:.1f}% "
                    f"(floor: {floor_pct:.1f}%)"
                ),
            ))
    return findings


# --- Driver ----------------------------------------------------------------


def _audit(per_file: dict[str, float], overall: float) -> tuple[
    list[Finding], list[tuple[str, int]],
]:
    """Run all checks and return ``(findings, per_check_counts)``.
    Pulled out so tests can call it directly without going through
    main() + pytest invocation."""
    baseline = _read_baseline()
    if baseline is None:
        # First-run / missing-baseline case: surface as a single
        # warning finding so the operator sees the message + can run
        # --write-baseline. NOT flagged as critical (avoid false
        # alarms on fresh forks).
        finding = Finding(
            check_id="overall-coverage-drift",
            detail=(
                "docs/audit/coverage-baseline.json is missing — run "
                "`python scripts/check_test_coverage.py --write-baseline` "
                "to create it. The audit will be clean after the first "
                "commit of the baseline."
            ),
        )
        return [finding], [
            ("overall-coverage-drift", 1),
            ("per-file-coverage-drift", 0),
            ("critical-path-floor", 0),
        ]
    o = check_overall_drift(overall, baseline)
    p = check_per_file_drift(per_file, baseline)
    c = check_critical_path_floors(per_file)
    return (
        o + p + c,
        [
            ("overall-coverage-drift", len(o)),
            ("per-file-coverage-drift", len(p)),
            ("critical-path-floor", len(c)),
        ],
    )


# Plain-English "what this check looks for" — surfaced in the alert email
# (#302) so a finding is self-explanatory without opening the source.
CHECK_DESCRIPTIONS = {
    "overall-coverage-drift":
        "Overall test coverage dropped more than 1pp below the committed baseline.",
    "per-file-coverage-drift":
        "A single file's coverage fell 5+pp below its baseline.",
    "critical-path-floor":
        "A critical-path file dropped below its minimum coverage floor.",
}


def send_audit_email(
    findings: list[Finding],
    *,
    per_check_counts: list[tuple[str, int]],
    overall: float,
) -> None:
    """Always-email (clean or not) — mirrors #226c / #227 / #228."""
    api_key = os.environ.get("BREVO_API_KEY")
    from_addr = os.environ.get("DIGEST_FROM_EMAIL")
    to_addr = os.environ.get("DIGEST_TO_EMAIL")
    if not (api_key and from_addr and to_addr):
        sys.stderr.write(
            "[coverage-audit] Brevo not configured; skipping email\n"
        )
        return

    today = datetime.date.today().isoformat()
    findings_by_check: dict[str, list[tuple[str, list[str]]]] = {}
    for f in findings:
        findings_by_check.setdefault(f.check_id, []).append(
            (f.path or "", [f.detail]))

    sys.path.insert(0, str(PROJECT_ROOT))
    from scripts import audit_email  # noqa: PLC0415
    subject, body = audit_email.render(
        today=today,
        tag="coverage",
        title="Weekly test-coverage audit",
        unit_word="audit",
        cadence_adj="weekly",
        scope_blurb="test-coverage drift against the committed baseline",
        per_check_counts=per_check_counts,
        findings_by_check=findings_by_check,
        descriptions=CHECK_DESCRIPTIONS,
        subject_extra=f" ({overall:.1f}%)",
        header_extra=[f"Overall coverage: {overall:.1f}%"],
        todo_steps=[
            "Close each coverage gap above (add tests for the uncovered lines).",
            "If a drop is intentional (you removed a feature), regenerate the "
            "baseline: `python scripts/check_test_coverage.py --write-baseline`.",
            "Re-run `python scripts/check_test_coverage.py` to confirm it goes clean.",
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
            sys.stdout.write(
                f"[coverage-audit] email sent: HTTP {resp.status}\n"
            )
    except urllib.error.URLError as e:
        sys.stderr.write(f"[coverage-audit] email send failed: {e}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help=(
            "Regenerate docs/audit/coverage-baseline.json from the "
            "current coverage state. Use when you've intentionally "
            "improved coverage and want future regressions measured "
            "against the new high-water mark."
        ),
    )
    parser.add_argument(
        "--json-only",
        metavar="OUTPUT_PATH",
        default=None,
        help=(
            "#229b (2026-05-27): write the audit result as JSON to "
            "OUTPUT_PATH and skip sending the Brevo confirmation "
            "email. Used by the /utilities inline-scan card — the UI "
            "POST spawns the script with this flag and polls for the "
            "result file. Same exit code semantics (0/1/2) so the UI "
            "can distinguish CLEAN / findings / internal-error runs."
        ),
    )
    parser.add_argument(
        "--autofile", action="store_true",
        help=(
            "#242 (2026-05-27): upsert findings into BACKLOG.md's "
            "`## Auto-filed by recurring audits` section after the "
            "email step. Used by the weekly cron workflow."
        ),
    )
    args = parser.parse_args(argv)

    sys.stdout.write(
        f"[coverage-audit] starting "
        f"{datetime.datetime.now(datetime.UTC).isoformat()}\n"
    )

    cov_data = _run_pytest_with_coverage()
    if cov_data is None:
        return 2
    per_file, overall = _extract_per_file_and_total(cov_data)
    sys.stdout.write(
        f"[coverage-audit] pytest done; overall {overall:.1f}%, "
        f"{len(per_file)} files\n"
    )

    if args.write_baseline:
        _write_baseline(overall, per_file)
        rel = _BASELINE_PATH.relative_to(PROJECT_ROOT)
        sys.stdout.write(
            f"[coverage-audit] baseline written -> {rel} "
            f"(overall {overall:.1f}%, {len(per_file)} files). "
            "Commit when ready.\n"
        )
        return 0

    findings, per_check_counts = _audit(per_file, overall)
    for label, count in per_check_counts:
        sys.stdout.write(
            f"[coverage-audit] {label}: {count} finding(s)\n"
        )
    for f in findings:
        line = "      -> "
        if f.path:
            sys.stdout.write(f"    {f.path}\n")
        sys.stdout.write(f"{line}{f.detail}\n")

    # #229b: JSON-only mode skips the email and writes the result to
    # the requested path. Used by /utilities inline-scan polling.
    if args.json_only:
        # Match the shape the inline-scan UI expects (from #236's
        # _run_audit_script_checks helper): {total, per_check,
        # findings: [dict, ...]}. Convert Finding dataclasses to
        # dicts so the JSON survives the subprocess round-trip.
        import dataclasses
        payload = {
            "total": len(findings),
            "per_check": [
                {"label": label, "count": count}
                for label, count in per_check_counts
            ],
            "findings": [dataclasses.asdict(f) for f in findings],
            "overall": overall,
        }
        Path(args.json_only).write_text(
            json.dumps(payload), encoding="utf-8",
        )
        sys.stdout.write(
            f"[coverage-audit] JSON-only mode: result written to "
            f"{args.json_only} (no email sent).\n"
        )
        return 0 if not findings else 1

    send_audit_email(
        findings, per_check_counts=per_check_counts, overall=overall,
    )
    if args.autofile:
        # Add PROJECT_ROOT to sys.path so `from scripts import ...`
        # works when run as `python scripts/check_test_coverage.py`.
        sys.path.insert(0, str(PROJECT_ROOT))
        from scripts import backlog_autofile  # noqa: PLC0415
        backlog_autofile.run_for_audit("coverage", findings)
    if not findings:
        sys.stdout.write(
            "[coverage-audit] CLEAN — confirmation email sent.\n"
        )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
