"""Single source of truth for the nightly cron job table.

Both ``app.py:_start_digest_scheduler`` (the live scheduler) and
``scripts/run_missed_crons.py`` (the manual replay path) iterate over
the same four midnight maintenance jobs. Keeping the table here — and
imported by both — guarantees the two paths can't drift.

Schema::

    (job_id, hour, minute, "module:function")

The 07:00 ``daily_digest`` is intentionally NOT in this table:

* The scheduler wires it directly in ``_start_digest_scheduler`` because
  its time is operator-configurable (``DIGEST_TIME`` env var) — fixing
  it in this table would freeze that config.
* The manual replay script (#168, #169) skips it deliberately —
  ``POST /api/digest/send`` is the documented manual trigger and
  bundling it here risks an accidental double-send.

The 45-second ``scheduler_heartbeat`` is also out — it's not a
maintenance cron, it's a liveness probe.
"""
from __future__ import annotations

# (job_id, hour, minute, "module:function") — order matches APScheduler
# fire order (00:01 → 00:02 → 00:03 → 00:05). The board is reconciled
# in this exact sequence so recurring spawn sees a stable section
# placement when it materialises today's tasks.
JOB_ORDER: list[tuple[str, int, int, str]] = [
    ("tomorrow_roll", 0, 1, "task_service:roll_tomorrow_to_today"),
    ("promote_due_today", 0, 2, "task_service:promote_due_today_tasks"),
    ("realign_tiers_with_due_dates", 0, 3, "task_service:realign_tiers_with_due_dates"),
    ("recurring_spawn", 0, 5, "recurring_service:spawn_today_tasks"),
]

VALID_JOB_IDS = frozenset(j[0] for j in JOB_ORDER)
