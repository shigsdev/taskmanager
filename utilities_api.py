"""JSON API for the /utilities page (#222, 2026-05-24).

Surfaces one-shot data cleanups as OAuth-gated endpoints so the
single-user owner can trigger them from the UI without needing to
curl `/api/debug/backfill/*` with an admin token. The admin-token
split (debug_api.py) protects writes from a leaked READ token —
that risk doesn't apply here because every endpoint is gated by
`@login_required` which already enforces `AUTHORIZED_EMAIL` (the
ONLY user authorized to mutate this app's data).

Endpoints:
    GET  /api/utilities/clear-stale-next-week-due-dates/count
         — preview: how many tasks would the backfill clean up?
    POST /api/utilities/clear-stale-next-week-due-dates
         — run the backfill; returns {updated: N}

Each utility action gets a GET-count preview + POST-run pair so
the UI can show "X tasks will be cleaned" before the user clicks
Run. New utilities should follow the same shape.
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify
from sqlalchemy import select

from auth import login_required
from models import Task, TaskStatus, Tier, db
from utils import local_today_date

bp = Blueprint("utilities_api", __name__, url_prefix="/api/utilities")

logger = logging.getLogger(__name__)


@bp.get("/clear-stale-next-week-due-dates/count")
@login_required
def clear_stale_next_week_due_dates_count(email: str):  # noqa: ARG001
    """Preview: how many active NEXT_WEEK tasks have a stale (today
    or earlier) due_date that the backfill would clear? Read-only —
    safe to call repeatedly. The UI uses this to display the count
    before the user clicks Run.
    """
    today = local_today_date()
    count = db.session.scalar(
        select(db.func.count()).select_from(Task).where(
            Task.tier == Tier.NEXT_WEEK,
            Task.due_date.is_not(None),
            Task.due_date <= today,
            Task.status == TaskStatus.ACTIVE,
        )
    )
    return jsonify({"count": count or 0})


@bp.post("/clear-stale-next-week-due-dates")
@login_required
def clear_stale_next_week_due_dates_run(email: str):  # noqa: ARG001
    """#220 follow-up: clear stale today/past due_date on tasks
    stuck in tier=NEXT_WEEK from pre-#220 tier-button punts. Wraps
    `task_service.backfill_clear_stale_next_week_due_dates()` —
    identical logic to the admin-token-gated
    `/api/debug/backfill/clear-stale-next-week-due-dates` endpoint,
    but OAuth-only so the UI can trigger it.

    Returns {updated: N}. Idempotent (re-running after clean = 0).
    """
    from task_service import backfill_clear_stale_next_week_due_dates
    n = backfill_clear_stale_next_week_due_dates()
    logger.info(
        "utilities: clear_stale_next_week_due_dates triggered via UI, updated=%d",
        n,
    )
    return jsonify({"updated": n})
