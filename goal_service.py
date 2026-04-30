"""Business logic for goals. Routes call into this module; models stay thin."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    GoalStatus,
    Task,
    TaskStatus,
    db,
)
from utils import (
    ValidationError,  # noqa: F401 — re-exported for API layer
    parse_int,
)
from utils import parse_enum as _parse_enum


def _parse_int(value: Any, field: str) -> int | None:
    """Goal's priority_rank is optional (nullable)."""
    return parse_int(value, field, allow_none=True)


# --- CRUD --------------------------------------------------------------------


def create_goal(data: dict) -> Goal:
    title = (data.get("title") or "").strip()
    if not title:
        raise ValidationError("title is required", "title")

    category = _parse_enum(GoalCategory, data.get("category"), "category")
    if category is None:
        raise ValidationError("category is required", "category")

    priority = _parse_enum(GoalPriority, data.get("priority"), "priority")
    if priority is None:
        raise ValidationError("priority is required", "priority")

    goal = Goal(
        title=title,
        category=category,
        priority=priority,
        priority_rank=_parse_int(data.get("priority_rank"), "priority_rank"),
        actions=data.get("actions") or None,
        target_quarter=(data.get("target_quarter") or "").strip() or None,
        status=_parse_enum(GoalStatus, data.get("status"), "status") or GoalStatus.NOT_STARTED,
        notes=data.get("notes") or None,
    )
    db.session.add(goal)
    db.session.commit()
    return goal


def get_goal(goal_id: uuid.UUID) -> Goal | None:
    return db.session.get(Goal, goal_id)


def list_goals(
    *,
    category: GoalCategory | None = None,
    priority: GoalPriority | None = None,
    status: GoalStatus | None = None,
    is_active: bool | None = True,
) -> list[Goal]:
    stmt = select(Goal)
    if is_active is not None:
        stmt = stmt.where(Goal.is_active == is_active)
    if category is not None:
        stmt = stmt.where(Goal.category == category)
    if priority is not None:
        stmt = stmt.where(Goal.priority == priority)
    if status is not None:
        stmt = stmt.where(Goal.status == status)
    stmt = stmt.order_by(Goal.category.asc(), Goal.priority_rank.asc(), Goal.title.asc())
    return list(db.session.scalars(stmt))


_UPDATABLE_FIELDS = {
    "title",
    "category",
    "priority",
    "priority_rank",
    "actions",
    "target_quarter",
    "status",
    "notes",
    "is_active",
}


def update_goal(goal_id: uuid.UUID, data: dict) -> Goal | None:
    goal = get_goal(goal_id)
    if goal is None:
        return None

    if "title" in data:
        title = (data["title"] or "").strip()
        if not title:
            raise ValidationError("title cannot be empty", "title")
        goal.title = title

    if "category" in data:
        goal.category = _parse_enum(GoalCategory, data["category"], "category") or goal.category

    if "priority" in data:
        goal.priority = _parse_enum(GoalPriority, data["priority"], "priority") or goal.priority

    if "priority_rank" in data:
        goal.priority_rank = _parse_int(data["priority_rank"], "priority_rank")

    if "actions" in data:
        goal.actions = data["actions"] or None

    if "target_quarter" in data:
        goal.target_quarter = (data["target_quarter"] or "").strip() or None

    if "status" in data:
        goal.status = _parse_enum(GoalStatus, data["status"], "status") or goal.status

    if "notes" in data:
        goal.notes = data["notes"] or None

    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            raise ValidationError("is_active must be a boolean", "is_active")
        goal.is_active = data["is_active"]

    unknown = set(data) - _UPDATABLE_FIELDS
    if unknown:
        raise ValidationError(f"unknown fields: {sorted(unknown)}", next(iter(unknown)))

    db.session.commit()
    return goal


def delete_goal(goal_id: uuid.UUID) -> bool:
    """Soft-delete by setting is_active=False. Returns False if not found.

    Also severs the goal from any bulk-import batch by clearing
    ``batch_id``. This prevents the recycle bin flow from resurrecting
    a user-trashed goal when the batch it came from is restored — the
    user explicitly trashed this one, so it should stay trashed.
    """
    goal = get_goal(goal_id)
    if goal is None:
        return False
    goal.is_active = False
    goal.batch_id = None
    db.session.commit()
    return True


# --- Progress ----------------------------------------------------------------


def goal_progress(goal_id: uuid.UUID) -> dict:
    """Return {total, completed, cancelled, percent} for tasks linked to a goal.

    Cancelled tasks (#25) are excluded from BOTH the numerator and the
    denominator: they shouldn't pad the completion ratio in either
    direction. The user explicitly chose to drop them, so they don't
    count as success OR as a missed opportunity. They're still surfaced
    via the `cancelled` field so the UI can show them separately.

    PR69: prefer ``goal_progress_batch([id, ...])`` for list views — this
    single-id helper still issues 3 COUNTs which is cheap for one goal
    but explodes to 3N+1 if called inside a list-rendering loop.
    """
    return goal_progress_batch([goal_id])[goal_id]


def goal_progress_batch(goal_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """Return ``{goal_id: progress_dict}`` for a batch of goal ids.

    PR69 perf #1: ``goals_api._serialize`` used to call ``goal_progress``
    inside a list comprehension, which fired 3 COUNT queries PER GOAL
    (3N+1 against ~20 goals = 60 round-trips per /goals page load,
    repeated on every visibilitychange + 60s poll). This batches them
    into one ``GROUP BY`` per status bucket; total queries goes from
    3N+1 to 3 regardless of N.

    The shape returned per id matches the single-goal ``goal_progress``
    contract — ``{total, completed, cancelled, percent}`` — so callers
    can swap in without changing serialization.
    """
    if not goal_ids:
        return {}

    # status status-bucketed counts per goal — single query, group-by.
    rows = db.session.execute(
        select(Task.goal_id, Task.status, func.count())
        .where(Task.goal_id.in_(goal_ids))
        .where(Task.status.notin_([TaskStatus.DELETED]))
        .group_by(Task.goal_id, Task.status)
    ).all()

    # bucket: {goal_id: {status: count}}
    buckets: dict[uuid.UUID, dict[TaskStatus, int]] = {gid: {} for gid in goal_ids}
    for gid, status, count in rows:
        buckets[gid][status] = count

    out: dict[uuid.UUID, dict] = {}
    for gid in goal_ids:
        b = buckets[gid]
        completed = b.get(TaskStatus.ARCHIVED, 0)
        cancelled = b.get(TaskStatus.CANCELLED, 0)
        # `total` == ARCHIVED + ACTIVE (cancelled excluded from denom).
        total = completed + b.get(TaskStatus.ACTIVE, 0)
        pct = round(completed / total * 100) if total > 0 else None
        out[gid] = {
            "total": total,
            "completed": completed,
            "cancelled": cancelled,
            "percent": pct,
        }
    return out
