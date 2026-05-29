"""Scheduler self-heal — record each cron fire + replay missed ones.

The four nightly midnight maintenance jobs (#167):

  - ``tomorrow_roll`` at 00:01
  - ``promote_due_today`` at 00:02
  - ``realign_tiers_with_due_dates`` at 00:03
  - ``recurring_spawn`` at 00:05

each get a single audit row in ``cron_audit`` keyed by ``job_id``.
``record()`` is called from inside the scheduler closure after every
real fire (success or error). ``replay_missed()`` is called once at
boot, after ``scheduler.start()`` — for each job, if today's
scheduled fire is in the past AND the audit row shows the last fire
predates today's scheduled time, the helper runs inline.

Edge cases handled:

  - **Empty table (fresh deploy)**: ``last_fire_at`` is treated as
    epoch-zero, so every job whose scheduled time is in the past runs.
  - **Deploy-during-fire-window**: if a deploy lands at 00:00:30 and
    the new container boots at 00:00:45, ``tomorrow_roll``'s 00:01
    scheduled time is in the FUTURE today — replay skips it, letting
    the real cron fire normally a few seconds later.
  - **Idempotency**: a second ``replay_missed()`` call on the same day
    is a no-op because the first call wrote ``last_fire_at = now()``,
    which is past today's scheduled time.
  - **Failure isolation**: each per-job invocation has its own
    try/except so a failure on (say) ``promote_due_today`` does NOT
    block ``realign_tiers_with_due_dates`` and ``recurring_spawn`` from
    running. Same shape as the manual script (#166).

All start/finish/failure events log at WARNING through the standard
logging chain so they land in ``app_logs`` via ``DBLogHandler`` and
surface on ``/api/debug/logs`` alongside real scheduler firings.

The replay loop is gated to **scheduler-worker-only** (called from
``_start_digest_scheduler`` which itself only runs in worker 1 via
APScheduler's ``post_worker_init`` hook). Other gunicorn workers
never trigger replay → no multi-worker race.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import importlib
import logging
import time
from typing import Any

from cron_jobs import JOB_ORDER, VALID_JOB_IDS
from models import CronAudit, db

logger = logging.getLogger(__name__)


def record(
    job_id: str,
    *,
    status: str,
    rowcount: int,
    elapsed_ms: float,
    when: _dt.datetime | None = None,
) -> None:
    """Upsert the audit row for ``job_id`` with the latest fire result.

    Idempotent: writes a new row on the first fire, updates the
    existing row on every subsequent fire. ``when`` lets callers pin
    a deterministic timestamp for tests; production callers omit it
    and get ``datetime.now(UTC)``.

    Never raises — audit-write failure must NOT crash the scheduler
    closure. On exception, logs at ERROR and returns silently so the
    actual cron work (which has already completed) is not rolled back.
    """
    if job_id not in VALID_JOB_IDS:
        logger.warning(
            "cron_audit.record called with unknown job_id=%r; valid=%s",
            job_id, sorted(VALID_JOB_IDS),
        )
        return

    fire_at = when if when is not None else _dt.datetime.now(_dt.UTC)

    try:
        row = db.session.get(CronAudit, job_id)
        if row is None:
            row = CronAudit(
                job_id=job_id,
                last_fire_at=fire_at,
                last_status=status,
                last_rowcount=int(rowcount),
                last_elapsed_ms=float(elapsed_ms),
            )
            db.session.add(row)
        else:
            row.last_fire_at = fire_at
            row.last_status = status
            row.last_rowcount = int(rowcount)
            row.last_elapsed_ms = float(elapsed_ms)
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        # Roll back the failed write but do not raise — the cron work
        # itself already succeeded / failed; the audit row is
        # diagnostic-only. Rollback may also fail (connection dead,
        # detached session); suppressing is correct here.
        with contextlib.suppress(Exception):
            db.session.rollback()
        logger.error(
            "cron_audit.record failed for job_id=%s: %s: %s",
            job_id, type(exc).__name__, exc,
        )


def _scheduled_today(hour: int, minute: int, *, now: _dt.datetime) -> _dt.datetime:
    """Return today's scheduled-fire timestamp in the same TZ as ``now``."""
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _invoke(spec: str) -> int:
    """Import ``module:function``, call it, return the rowcount.

    Same shape as the helper in ``scripts/run_missed_crons.py`` so
    both paths get identical accounting. A list return value (e.g.
    ``spawn_today_tasks`` returns a list of created task IDs) is
    converted to its length.
    """
    module_name, fn_name = spec.split(":")
    module = importlib.import_module(module_name)
    fn = getattr(module, fn_name)
    result = fn()
    if isinstance(result, list):
        return len(result)
    return int(result or 0)


def replay_missed(now: _dt.datetime | None = None) -> list[dict[str, Any]]:
    """Run any nightly cron whose last fire predates today's scheduled time.

    Walks ``JOB_ORDER`` in scheduler order. For each job:

      1. Compute ``scheduled_today = today at HH:MM`` in the now-TZ.
      2. If ``now < scheduled_today``: skip (cron hasn't been due yet
         today — let it fire normally; replay would double-fire it).
      3. Read the audit row. If ``last_fire_at >= scheduled_today``:
         skip (already ran today).
      4. Otherwise run the helper inline, then ``record()`` the result.

    Per-job try/except: a failure isolates to that job. The return
    value is a list of per-job result dicts (job_id, status, rows,
    elapsed_ms, skipped reason if applicable) for caller inspection
    + the boot-time WARNING log.

    Caller must be inside a Flask app context (we read+write ``db``).
    """
    now = now if now is not None else _dt.datetime.now(_dt.UTC)
    results: list[dict[str, Any]] = []

    for job_id, hour, minute, spec in JOB_ORDER:
        scheduled = _scheduled_today(hour, minute, now=now)
        if now < scheduled:
            logger.warning(
                "cron_audit.replay_missed skip %s reason=future_today scheduled=%s",
                job_id, scheduled.isoformat(),
            )
            results.append({
                "job_id": job_id, "status": "SKIPPED",
                "reason": "scheduled time is in the future today",
                "scheduled_today": scheduled.isoformat(),
            })
            continue

        row = db.session.get(CronAudit, job_id)
        last_fire = row.last_fire_at if row else None

        # An audit row could carry a TZ-naive timestamp if it was
        # inserted by an old code path; normalise to aware-UTC so the
        # comparison below doesn't raise.
        if last_fire is not None and last_fire.tzinfo is None:
            last_fire = last_fire.replace(tzinfo=_dt.UTC)

        if last_fire is not None and last_fire >= scheduled:
            logger.warning(
                "cron_audit.replay_missed skip %s reason=already_ran last_fire=%s",
                job_id, last_fire.isoformat(),
            )
            results.append({
                "job_id": job_id, "status": "SKIPPED",
                "reason": "already ran today",
                "last_fire_at": last_fire.isoformat(),
            })
            continue

        logger.warning(
            "cron_audit.replay_missed start %s scheduled=%s last_fire=%s",
            job_id, scheduled.isoformat(),
            last_fire.isoformat() if last_fire else "<never>",
        )
        t0 = time.perf_counter()
        try:
            rows = _invoke(spec)
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.error(
                "cron_audit.replay_missed FAILED %s after %.1fms: %s: %s",
                job_id, elapsed_ms, type(exc).__name__, exc,
                exc_info=True,
            )
            record(
                job_id,
                status="ERROR",
                rowcount=0,
                elapsed_ms=elapsed_ms,
                when=now,
            )
            results.append({
                "job_id": job_id, "status": "ERROR",
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "elapsed_ms": elapsed_ms,
            })
            continue

        elapsed_ms = (time.perf_counter() - t0) * 1000
        record(
            job_id,
            status="OK",
            rowcount=rows,
            elapsed_ms=elapsed_ms,
            when=now,
        )
        logger.warning(
            "cron_audit.replay_missed done %s rows=%d elapsed_ms=%.1f",
            job_id, rows, elapsed_ms,
        )
        results.append({
            "job_id": job_id, "status": "OK",
            "rows": rows, "elapsed_ms": elapsed_ms,
        })

    return results
