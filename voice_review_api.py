"""Voice Task Review API (#297, ADR-034).

A deliberately tiny blueprint — the ONLY surface the scoped voice-action
token (``voice_action_token.py``) can authenticate. An iOS Shortcut
driven by Siri/CarPlay reads the review queue and then completes / moves
/ cancels tasks hands-free while driving.

Security (ADR-034): every route here is ``@voice_action_or_login``. The
voice-action token is structurally rejected on every OTHER route in the
app (they use ``@login_required``, which never inspects the bearer
token), so a leaked token can ONLY:
  - read the today/overdue/tomorrow review queue (titles + ids), and
  - complete / move-to-{today,tomorrow,next_week,backlog} / cancel a task.
It cannot create, delete, bulk-edit, read settings/exports, or touch any
other entity. ``/move`` enforces the tier whitelist explicitly — that is
the load-bearing in-scope check.

These routes also accept normal OAuth (so the web app could call them),
but in practice the web app uses ``/api/tasks/*`` directly.
"""
from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request
from sqlalchemy import and_, or_

from auth import voice_action_or_login
from models import Task, TaskStatus, Tier
from rate_limit import limiter
from task_service import (
    ValidationError,
    cancel_parent_task,
    complete_parent_task,
    get_task,
    update_task,
)
from utils import local_today_date

bp = Blueprint("voice_review_api", __name__, url_prefix="/api/voice-review")

# The ONLY tiers a voice "move" may target (ADR-034 whitelist). Excludes
# this_week / freezer / inbox — a hands-free flow shouldn't bury a task
# anywhere the driver can't see it, and the tighter the set the smaller a
# leaked token's reach.
_MOVE_WHITELIST = frozenset(
    {Tier.TODAY.value, Tier.TOMORROW.value, Tier.NEXT_WEEK.value, Tier.BACKLOG.value}
)


def _slim(task: Task, bucket: str) -> dict:
    """Minimal shape the Shortcut needs — deliberately NOT the full task
    payload (ADR-034: grant no read beyond what the queue requires)."""
    return {
        "id": str(task.id),
        "title": task.title,
        "tier": task.tier.value,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "bucket": bucket,
    }


@bp.get("/queue")
@voice_action_or_login
@limiter.limit("60 per minute")
def queue(email: str):  # noqa: ARG001
    """Top-level active tasks to review, ordered overdue → today →
    tomorrow (the most commute-actionable first). One bucket per task."""
    today = local_today_date()
    candidates = (
        Task.query.filter(
            Task.status == TaskStatus.ACTIVE,
            Task.parent_id.is_(None),
            or_(
                and_(Task.due_date.isnot(None), Task.due_date < today),
                Task.tier == Tier.TODAY,
                Task.tier == Tier.TOMORROW,
            ),
        )
        .order_by(Task.due_date.asc().nullslast(), Task.sort_order.asc())
        .all()
    )

    overdue, today_b, tomorrow_b = [], [], []
    for t in candidates:
        if t.due_date is not None and t.due_date < today:
            overdue.append(_slim(t, "overdue"))
        elif t.tier == Tier.TODAY:
            today_b.append(_slim(t, "today"))
        elif t.tier == Tier.TOMORROW:
            tomorrow_b.append(_slim(t, "tomorrow"))

    items = overdue + today_b + tomorrow_b
    return jsonify(
        {
            "count": len(items),
            "counts": {
                "overdue": len(overdue),
                "today": len(today_b),
                "tomorrow": len(tomorrow_b),
            },
            "items": items,
        }
    )


@bp.post("/<uuid:task_id>/complete")
@voice_action_or_login
@limiter.limit("120 per minute")
def complete(email: str, task_id: uuid.UUID):  # noqa: ARG001
    """Complete a task. Auto-completes open subtasks — a driver can't
    answer the "you have N open subtasks" prompt the web flow shows."""
    if get_task(task_id) is None:
        return jsonify({"error": "not found"}), 404
    try:
        task = complete_parent_task(task_id, complete_subtasks=True)
    except ValidationError as e:
        return jsonify({"error": str(e), "field": e.field}), 422
    if task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True, "id": str(task.id), "status": task.status.value})


@bp.post("/<uuid:task_id>/move")
@voice_action_or_login
@limiter.limit("120 per minute")
def move(email: str, task_id: uuid.UUID):  # noqa: ARG001
    """Move a task to a WHITELISTED tier (today/tomorrow/next_week/backlog).
    The whitelist check is the load-bearing in-scope restriction — a voice
    token must never be able to set an arbitrary tier or any other field."""
    data = request.get_json(silent=True) or {}
    tier = data.get("tier")
    if tier not in _MOVE_WHITELIST:
        return (
            jsonify(
                {
                    "error": "tier must be one of "
                    + ", ".join(sorted(_MOVE_WHITELIST)),
                    "field": "tier",
                }
            ),
            422,
        )
    if get_task(task_id) is None:
        return jsonify({"error": "not found"}), 404
    try:
        # Pass ONLY the tier — never the raw body — so a voice request can
        # never smuggle title/notes/project/etc. through update_task.
        task = update_task(task_id, {"tier": tier})
    except ValidationError as e:
        return jsonify({"error": str(e), "field": e.field}), 422
    if task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True, "id": str(task.id), "tier": task.tier.value})


@bp.post("/<uuid:task_id>/cancel")
@voice_action_or_login
@limiter.limit("120 per minute")
def cancel(email: str, task_id: uuid.UUID):  # noqa: ARG001
    """Cancel a task. Auto-cancels open subtasks (same reason as complete)."""
    if get_task(task_id) is None:
        return jsonify({"error": "not found"}), 404
    try:
        task = cancel_parent_task(task_id, cancel_subtasks=True)
    except ValidationError as e:
        return jsonify({"error": str(e), "field": e.field}), 422
    if task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True, "id": str(task.id), "status": task.status.value})
