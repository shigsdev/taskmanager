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
    Project,
    RecurringTask,
    Task,
    TaskStatus,
    WeeklyFocus,
    db,
)
from recurring_service import cascade_parent_archive
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
        _set_goal_active(goal, data["is_active"])

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
    _set_goal_active(goal, False)
    goal.batch_id = None
    db.session.commit()
    return True


def _set_goal_active(goal: Goal, active: bool) -> None:
    """The one place a goal's ``is_active`` changes (#368).

    Archiving pauses the goal's running repeating templates and marks
    them ``paused_by_goal_archive``; unarchiving resumes the marked ones
    whose project isn't archived too. The rule is shared with projects
    in ``recurring_service.cascade_parent_archive``, the same way #353's
    ``project_service._set_project_active`` works.

    Service layer, not route, because the reflection apply path calls
    ``update_goal`` / ``delete_goal`` directly, and the recycle bin's
    ``undo_batch`` / ``restore_batch`` call this.

    Only on an actual transition: a re-sent ``is_active: false`` (a
    second tab, a double click, a second DELETE) must not re-pause a
    template the user resumed by hand. Doesn't commit; callers do.
    """
    if goal.is_active == active:
        return
    goal.is_active = active
    cascade_parent_archive("goal", goal.id, not active)


# #349 (2026-10-01): the hard delete, and the guard that makes it safe.
#
# FOUR models carry a `goal_id`: Project, Task, RecurringTask and
# WeeklyFocus. Only `Task.goal_id` lacks `ondelete="SET NULL"`, so a raw
# DELETE would hard-fail on tasks and SILENTLY null the other three.
# Silently nulling a project's goal because its goal was removed is
# exactly the class of invisible data change #350/#351 exist to stop, so
# this refuses and names the blockers rather than letting the database
# quietly decide.
#
# WeeklyFocus is the one worth calling out: it is the least visible of
# the four, and leaving it out would have emptied a past week's focus
# row with nothing shown to the user.
_GOAL_REFERRERS = (
    ("tasks", Task),
    ("projects", Project),
    ("recurring", RecurringTask),
    ("weekly_focus", WeeklyFocus),
)


def goal_reference_counts(goal_id: uuid.UUID) -> dict[str, int]:
    """How many rows in each table still point at this goal.

    Deliberately unfiltered by status or is_active: an archived task
    holds the same foreign key as an active one, and the database does
    not care which it is.
    """
    return {
        name: db.session.scalar(
            select(func.count()).select_from(model).where(model.goal_id == goal_id)
        ) or 0
        for name, model in _GOAL_REFERRERS
    }


def hard_delete_goal(goal_id: uuid.UUID) -> dict:
    """Permanently remove a goal row.

    Returns ``{"deleted": bool, "reason": str | None, "references": {...}}``.
    ``reason`` is ``"not_found"``, ``"still_active"`` or ``"referenced"``.

    Requires the goal to be ARCHIVED first. That is a deliberate second
    gate: it makes the destructive path two separate decisions, and it
    means every hard delete has already been through ``delete_goal``,
    which clears ``batch_id`` — so a hard delete can never strand a
    restorable import batch holding a row that no longer exists.
    """
    goal = get_goal(goal_id)
    if goal is None:
        return {"deleted": False, "reason": "not_found", "references": {}}

    refs = goal_reference_counts(goal_id)
    if goal.is_active:
        return {"deleted": False, "reason": "still_active", "references": refs}
    if any(refs.values()):
        return {"deleted": False, "reason": "referenced", "references": refs}

    db.session.delete(goal)
    db.session.commit()
    return {"deleted": True, "reason": None, "references": refs}


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
