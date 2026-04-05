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


class ValidationError(Exception):
    """Raised when user input fails validation. Routes map this to HTTP 422."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field


# --- Coercion helpers --------------------------------------------------------


def _parse_enum(enum_cls, value: Any, field: str):
    if value is None:
        return None
    try:
        return enum_cls(str(value))
    except ValueError as e:
        raise ValidationError(f"invalid {field}: {value!r}", field) from e


def _parse_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as e:
        raise ValidationError(f"invalid {field}: must be integer", field) from e


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
    """Soft-delete by setting is_active=False. Returns False if not found."""
    goal = get_goal(goal_id)
    if goal is None:
        return False
    goal.is_active = False
    db.session.commit()
    return True


# --- Progress ----------------------------------------------------------------


def goal_progress(goal_id: uuid.UUID) -> dict:
    """Return {total, completed, percent} for tasks linked to a goal."""
    total = db.session.scalar(
        select(func.count()).select_from(Task).where(
            Task.goal_id == goal_id,
            Task.status != TaskStatus.DELETED,
        )
    )
    completed = db.session.scalar(
        select(func.count()).select_from(Task).where(
            Task.goal_id == goal_id,
            Task.status == TaskStatus.ARCHIVED,
        )
    )
    total = total or 0
    completed = completed or 0
    pct = round(completed / total * 100) if total > 0 else None
    return {"total": total, "completed": completed, "percent": pct}
