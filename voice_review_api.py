"""Voice Task Review API (#297, ADR-034).

A deliberately tiny blueprint — the ONLY surface the scoped voice-action
token (``voice_action_token.py``) can authenticate. An iOS Shortcut
driven by Siri/CarPlay reads the review queue and then completes / moves
/ cancels tasks hands-free while driving.

Security (ADR-034): every route here is ``@voice_action_or_login``. The
voice-action token is structurally rejected on every OTHER route in the
app (they use ``@login_required``, which never inspects the bearer
token), so a leaked token can ONLY:
  - read the today/overdue/tomorrow review queue (titles + ids),
  - complete / move-to-{today,tomorrow,next_week,backlog} / cancel a task,
  - (#500, ADR-043) rename an open task or set / clear its due date, and
    add a task (title, Work / Personal, due date — nothing else).
It cannot delete, bulk-edit, read settings/exports, or touch any other
entity or field. ``/move`` enforces the tier whitelist explicitly, and
``/answer`` / ``/tasks`` hand ``update_task`` / ``create_task`` only the
keys ``voice_answer`` produced — those are the load-bearing in-scope
checks.

These routes also accept normal OAuth (so the web app could call them),
but in practice the web app uses ``/api/tasks/*`` directly.
"""
from __future__ import annotations

import uuid

from flask import Blueprint, g, jsonify
from sqlalchemy import and_, or_

from auth import voice_action_or_login
from models import Task, TaskStatus, Tier
from rate_limit import limiter
from task_service import (
    ValidationError,
    cancel_parent_task,
    complete_parent_task,
    create_task,
    get_task,
    update_task,
)
from utils import local_today_date, optional_json_body
from voice_answer import interpret_answer, parse_new_task, spoken_date

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
@optional_json_body
def move(email: str, task_id: uuid.UUID):  # noqa: ARG001
    """Move a task to a WHITELISTED tier (today/tomorrow/next_week/backlog).
    The whitelist check is the load-bearing in-scope restriction — a voice
    token must never be able to set an arbitrary tier or any other field."""
    data = g.json_body
    tier = data.get("tier")
    if not isinstance(tier, str) or tier not in _MOVE_WHITELIST:
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


# --- #500 (ADR-043): one spoken answer, and adding a task by voice ---------
# Every answer carries ``say``, a sentence the Shortcut speaks as-is, so a
# Shortcut built per docs never goes silent — even on a 400 or 404.

_SECTION_NAMES = {
    Tier.INBOX: "your Inbox", Tier.TODAY: "Today", Tier.TOMORROW: "Tomorrow",
    Tier.THIS_WEEK: "This Week", Tier.NEXT_WEEK: "Next Week",
    Tier.BACKLOG: "Backlog", Tier.FREEZER: "the Freezer",
}
_SAY_UNKNOWN = "I didn't catch that, so I left it as it is."
_SAY_BAD_DATE = "I didn't understand that date, so I left it as it is."
_SAY_NO_ANSWER = "I didn't hear an answer, so I left it as it is."
_SAY_NOT_OPEN = "That task isn't open any more, so I skipped it."
_SAY_GONE = "That task isn't there any more, so I skipped it."
_SAY_NO_TASK = "I didn't hear a task, so nothing was added."
_SAY_TOO_LONG_ANSWER = "That was too long, so I left it as it is."
_SAY_TOO_LONG_TASK = "That was too long, so nothing was added."
# Far past anything dictated (a title is at most 500); refused before any
# parsing, so a long text can't make the parser work hard (security
# review 2026-10-18).
_MAX_TEXT = 1000


def _said(ok: bool, action: str, task_id: uuid.UUID, say: str, status: int = 200):
    return jsonify({"ok": ok, "action": action, "id": str(task_id), "say": say}), status


@bp.post("/<uuid:task_id>/answer")
@voice_action_or_login
@limiter.limit("120 per minute")
@optional_json_body
def answer(email: str, task_id: uuid.UUID):  # noqa: ARG001
    """Do what the user said about one task (#500, spec §2).

    Only ``text`` is read; ``voice_answer.interpret_answer`` turns it into
    one action, and only that action's own keys reach the task
    (``title`` / ``due_date`` / ``tier``, or complete / cancel). A task
    that isn't active is left alone, so the token can't edit a completed,
    cancelled or deleted one.
    """
    text = g.json_body.get("text")
    if not isinstance(text, str):
        return jsonify({"ok": False, "say": _SAY_NO_ANSWER}), 400
    if len(text) > _MAX_TEXT:
        return jsonify({"ok": False, "say": _SAY_TOO_LONG_ANSWER}), 400
    task = get_task(task_id)
    if task is None:
        return jsonify({"ok": False, "say": _SAY_GONE}), 404

    intent = interpret_answer(text, local_today_date())
    action = intent["action"]
    if action == "unknown":
        return _said(False, action, task_id, _SAY_UNKNOWN)
    if action == "bad_date":
        return _said(False, action, task_id, _SAY_BAD_DATE)
    if task.status != TaskStatus.ACTIVE:
        return _said(False, action, task_id, _SAY_NOT_OPEN)
    if action == "skip":
        return _said(True, action, task_id, "Skipped.")

    try:
        if action == "complete":
            complete_parent_task(task_id, complete_subtasks=True)
            say = "Marked complete."
        elif action == "cancel":
            cancel_parent_task(task_id, cancel_subtasks=True)
            say = "Cancelled."
        elif action == "move":
            task = update_task(task_id, {"tier": intent["tier"]})
            say = f"Moved to {_SECTION_NAMES[task.tier]}."
        elif action == "rename":
            task = update_task(task_id, {"title": intent["title"]})
            say = f'Renamed to "{task.title}".'
        elif action == "due":
            task = update_task(task_id, {"due_date": intent["due_date"].isoformat()})
            say = (f"Due {spoken_date(task.due_date)}. "
                   f"It's in {_SECTION_NAMES[task.tier]}.")
        else:  # clear_due
            update_task(task_id, {"due_date": None})
            say = "Due date removed."
    except ValidationError as e:
        return _said(False, action, task_id, f"I couldn't do that: {e}")
    return _said(True, action, task_id, say)


@bp.post("/tasks")
@voice_action_or_login
@limiter.limit("30 per minute")
@optional_json_body
def add_task(email: str):  # noqa: ARG001
    """Add a task from what the user said (#500, spec §2):
    ``[work|personal] [task] <title> [due <date>]``. Only the title, type
    and due date reach ``create_task`` — Inbox, or the date's section
    (#386) — never a project, goal, notes or any other field."""
    text = g.json_body.get("text")
    if not isinstance(text, str):
        return jsonify({"ok": False, "say": _SAY_NO_TASK}), 400
    if len(text) > _MAX_TEXT:
        return jsonify({"ok": False, "say": _SAY_TOO_LONG_TASK}), 400
    parsed = parse_new_task(text, local_today_date())
    if parsed is None:
        return jsonify({"ok": False, "say": _SAY_NO_TASK})
    data = {"title": parsed["title"], "type": parsed["type"]}
    if parsed["due_date"] is not None:
        data["due_date"] = parsed["due_date"].isoformat()
    try:
        task = create_task(data)
    except ValidationError as e:
        return jsonify({"ok": False, "say": f"I couldn't add that: {e}"})
    where = _SECTION_NAMES[task.tier]
    due = f", due {spoken_date(task.due_date)}," if parsed["due_date"] else ""
    to = "to " + where
    say = f'Added "{task.title}"{due} {to} as a {task.type.value} task.'
    return jsonify({"ok": True, "id": str(task.id), "title": task.title, "say": say}), 201
