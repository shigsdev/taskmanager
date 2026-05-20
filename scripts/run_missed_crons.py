"""Manually re-run the four midnight cron jobs after a scheduler outage.

When Railway drops a midnight cron fire (container restart at the
wrong second, a deploy that overlapped 00:00, an outage), the four
midnight jobs silently skip until the next 24h cycle. This script
replays them in the same order the APScheduler runs them:

    00:01  tomorrow_roll        roll_tomorrow_to_today
    00:02  promote_due_today    promote_due_today_tasks
    00:03  realign_tiers        realign_tiers_with_due_dates
    00:05  recurring_spawn      spawn_today_tasks

The 07:00 ``daily_digest`` is intentionally NOT included — the
existing ``POST /api/digest/send`` endpoint already covers that path,
and bundling it here would risk an accidental second digest.

Usage
-----
    railway run python scripts/run_missed_crons.py
    railway run python scripts/run_missed_crons.py --dry-run
    railway run python scripts/run_missed_crons.py --only recurring_spawn
    railway run python scripts/run_missed_crons.py --only tomorrow_roll,recurring_spawn
    railway run python scripts/run_missed_crons.py --date 2026-05-19

Notes
-----
* ``--dry-run`` monkey-patches ``Session.commit`` to roll back for the
  duration of each helper, so rowcounts are reported without writes
  landing. Useful for a "what would happen" pass before the real run.
* ``--date`` only affects ``recurring_spawn``; the other three jobs
  operate on the current calendar day by design (they reconcile *now*).
* Per-job ``try/except`` so one failure does not block the rest. The
  exit code is non-zero if any job raised.
* Every start/finish/failure logs at WARNING through the standard
  ``logging`` chain so the run lands in ``/api/debug/logs`` alongside
  real scheduler firings.
"""
from __future__ import annotations

import argparse
import importlib
import logging
import os
import sys
import time
from contextlib import contextmanager, nullcontext
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("run_missed_crons")


JOB_ORDER: list[tuple[str, str, str, str]] = [
    ("tomorrow_roll",     "task_service",      "roll_tomorrow_to_today",       "00:01"),
    ("promote_due_today", "task_service",      "promote_due_today_tasks",      "00:02"),
    ("realign_tiers",     "task_service",      "realign_tiers_with_due_dates", "00:03"),
    ("recurring_spawn",   "recurring_service", "spawn_today_tasks",            "00:05"),
]

VALID_JOB_IDS = frozenset(j[0] for j in JOB_ORDER)


def _parse_only(value: str | None) -> set[str]:
    if not value:
        return set(VALID_JOB_IDS)
    requested = {tok.strip() for tok in value.split(",") if tok.strip()}
    unknown = requested - VALID_JOB_IDS
    if unknown:
        raise SystemExit(
            f"unknown job id(s): {sorted(unknown)}. "
            f"valid: {sorted(VALID_JOB_IDS)}"
        )
    return requested


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"--date must be ISO YYYY-MM-DD: {exc}") from None


@contextmanager
def _dry_run_guard():
    """Swap Session.commit for a rollback for the duration of the block.

    The four helpers each open their own ``Session(db.engine)`` and
    ``commit()`` inside — there is no single outer transaction to
    rollback. Monkey-patching at the class level catches every commit
    invoked from any of them.
    """
    from sqlalchemy.orm import Session

    original = Session.commit

    def _commit_as_rollback(self):
        self.rollback()

    Session.commit = _commit_as_rollback
    try:
        yield
    finally:
        Session.commit = original


def _invoke(module_name: str, fn_name: str, date_override: date | None) -> int:
    module = importlib.import_module(module_name)
    fn = getattr(module, fn_name)
    kwargs = {}
    if fn_name == "spawn_today_tasks" and date_override is not None:
        kwargs["target_date"] = date_override
    result = fn(**kwargs)
    if isinstance(result, list):
        return len(result)
    return int(result)


def _print_summary(rows: list[tuple[str, str, str, int, float]], *, dry_run: bool) -> None:
    header = "Manual cron run report" + (" (DRY-RUN)" if dry_run else "")
    print(header)
    print("─" * max(len(header), 56))
    print(f"{'job_id':<22} {'cron':<6} {'status':<8} {'rows':>6} {'elapsed_ms':>12}")
    for job_id, sched_time, status, count, elapsed_ms in rows:
        print(f"{job_id:<22} {sched_time:<6} {status:<8} {count:>6} {elapsed_ms:>12.1f}")
    n_ok = sum(1 for r in rows if r[2] in {"OK", "DRY-RUN"})
    n_err = sum(1 for r in rows if r[2] == "ERROR")
    print(f"\nResult: {n_ok} succeeded, {n_err} failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_missed_crons",
        description="Manually re-run the four midnight cron jobs (replays a missed fire).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run each helper inside a rollback guard — no writes persist.",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help=f"Comma-separated subset of job ids. Default = all. Valid: {sorted(VALID_JOB_IDS)}",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Override the spawn date for recurring_spawn (YYYY-MM-DD). Other jobs ignore this.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    selected_ids = _parse_only(args.only)
    date_override = _parse_date(args.date)
    jobs = [j for j in JOB_ORDER if j[0] in selected_ids]

    from app import create_app

    app = create_app()
    summary: list[tuple[str, str, str, int, float]] = []
    exit_code = 0

    with app.app_context():
        for job_id, module_name, fn_name, sched_time in jobs:
            tag = " [DRY-RUN]" if args.dry_run else ""
            logger.warning("run_missed_crons start %s (cron %s)%s", job_id, sched_time, tag)
            t0 = time.perf_counter()
            ctx = _dry_run_guard() if args.dry_run else nullcontext()
            try:
                with ctx:
                    rows = _invoke(module_name, fn_name, date_override)
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                logger.error(
                    "run_missed_crons FAILED %s after %.1fms: %s",
                    job_id, elapsed_ms, exc,
                    exc_info=True,
                )
                summary.append((job_id, sched_time, "ERROR", 0, elapsed_ms))
                exit_code = 1
                continue
            elapsed_ms = (time.perf_counter() - t0) * 1000
            status = "DRY-RUN" if args.dry_run else "OK"
            logger.warning(
                "run_missed_crons done %s status=%s rows=%d elapsed_ms=%.1f",
                job_id, status, rows, elapsed_ms,
            )
            summary.append((job_id, sched_time, status, rows, elapsed_ms))

    _print_summary(summary, dry_run=args.dry_run)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
