"""Business logic for tasks. Routes call into this module; models stay thin.

All mutations commit on success. All validation failures raise
``ValidationError`` so the route layer can map them to HTTP 422.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from models import Task, TaskStatus, TaskType, Tier, db
from utils import ValidationError  # noqa: F401 — re-exported for API layer
from utils import parse_enum as _parse_enum
from utils import parse_int as _parse_int
from utils import parse_uuid as _parse_uuid

# --- Task-specific coercion helpers ------------------------------------------


def _parse_date(value: Any, field: str = "due_date") -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as e:
        raise ValidationError(f"invalid date: {value!r}", field) from e


def _parse_url(value: Any) -> str | None:
    if value is None or value == "":
        return None
    url = str(value).strip()
    if not url.startswith(("http://", "https://")):
        raise ValidationError("url must start with http:// or https://", "url")
    if len(url) > 2000:
        raise ValidationError("url too long", "url")
    return url


def _parse_checklist(value: Any) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError("checklist must be a list", "checklist")
    return value


# --- CRUD --------------------------------------------------------------------


def create_task(data: dict) -> Task:
    title = (data.get("title") or "").strip()
    if not title:
        raise ValidationError("title is required", "title")

    task_type = _parse_enum(TaskType, data.get("type"), "type")
    if task_type is None:
        raise ValidationError("type is required", "type")

    tier = _parse_enum(Tier, data.get("tier"), "tier") or Tier.INBOX

    parent_id = _parse_uuid(data.get("parent_id"), "parent_id")
    if parent_id is not None:
        parent = get_task(parent_id)
        if parent is None:
            raise ValidationError("parent task not found", "parent_id")
        if parent.parent_id is not None:
            raise ValidationError("subtasks cannot have their own subtasks", "parent_id")

    task = Task(
        title=title,
        type=task_type,
        tier=tier,
        parent_id=parent_id,
        project_id=_parse_uuid(data.get("project_id"), "project_id"),
        goal_id=_parse_uuid(data.get("goal_id"), "goal_id"),
        due_date=_parse_date(data.get("due_date")),
        url=_parse_url(data.get("url")),
        notes=(data.get("notes") or None),
        checklist=_parse_checklist(data.get("checklist")),
        sort_order=_parse_int(data.get("sort_order", 0), "sort_order"),
    )
    db.session.add(task)
    db.session.commit()
    return task


def get_task(task_id: uuid.UUID) -> Task | None:
    return db.session.get(Task, task_id)


def list_tasks(
    *,
    tier: Tier | None = None,
    type: TaskType | None = None,
    status: TaskStatus | None = TaskStatus.ACTIVE,
    project_id: uuid.UUID | None = None,
    goal_id: uuid.UUID | None = None,
) -> list[Task]:
    stmt = select(Task)
    if status is not None:
        stmt = stmt.where(Task.status == status)
    if tier is not None:
        stmt = stmt.where(Task.tier == tier)
    if type is not None:
        stmt = stmt.where(Task.type == type)
    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    if goal_id is not None:
        stmt = stmt.where(Task.goal_id == goal_id)
    stmt = stmt.order_by(Task.sort_order.asc(), Task.created_at.desc())
    return list(db.session.scalars(stmt))


_UPDATABLE_FIELDS = {
    "title",
    "type",
    "tier",
    "status",
    "parent_id",
    "project_id",
    "goal_id",
    "due_date",
    "url",
    "notes",
    "checklist",
    "sort_order",
    "last_reviewed",
}


def update_task(task_id: uuid.UUID, data: dict) -> Task | None:
    task = get_task(task_id)
    if task is None:
        return None

    if "title" in data:
        title = (data["title"] or "").strip()
        if not title:
            raise ValidationError("title cannot be empty", "title")
        task.title = title

    if "type" in data:
        task.type = _parse_enum(TaskType, data["type"], "type") or task.type

    if "tier" in data:
        task.tier = _parse_enum(Tier, data["tier"], "tier") or task.tier

    if "status" in data:
        task.status = _parse_enum(TaskStatus, data["status"], "status") or task.status

    if "parent_id" in data:
        new_parent_id = _parse_uuid(data["parent_id"], "parent_id")
        if new_parent_id is not None:
            parent = get_task(new_parent_id)
            if parent is None:
                raise ValidationError("parent task not found", "parent_id")
            if parent.parent_id is not None:
                raise ValidationError("subtasks cannot have their own subtasks", "parent_id")
            if new_parent_id == task.id:
                raise ValidationError("task cannot be its own parent", "parent_id")
        task.parent_id = new_parent_id

    if "project_id" in data:
        task.project_id = _parse_uuid(data["project_id"], "project_id")

    if "goal_id" in data:
        task.goal_id = _parse_uuid(data["goal_id"], "goal_id")

    if "due_date" in data:
        task.due_date = _parse_date(data["due_date"], "due_date")

    if "last_reviewed" in data:
        task.last_reviewed = _parse_date(data["last_reviewed"], "last_reviewed")

    if "url" in data:
        task.url = _parse_url(data["url"])

    if "notes" in data:
        task.notes = data["notes"] or None

    if "checklist" in data:
        task.checklist = _parse_checklist(data["checklist"])

    if "sort_order" in data:
        task.sort_order = _parse_int(data["sort_order"], "sort_order")

    unknown = set(data) - _UPDATABLE_FIELDS
    if unknown:
        raise ValidationError(f"unknown fields: {sorted(unknown)}", next(iter(unknown)))

    db.session.commit()
    return task


def list_subtasks(parent_id: uuid.UUID) -> list[Task]:
    """Return active subtasks for a given parent task."""
    stmt = (
        select(Task)
        .where(Task.parent_id == parent_id, Task.status == TaskStatus.ACTIVE)
        .order_by(Task.sort_order.asc(), Task.created_at.desc())
    )
    return list(db.session.scalars(stmt))


def complete_parent_task(task_id: uuid.UUID, complete_subtasks: bool = False) -> Task | None:
    """Archive a parent task. If it has open subtasks, either archive them too
    or raise a ValidationError so the UI can prompt the user."""
    task = get_task(task_id)
    if task is None:
        return None
    open_subtasks = list_subtasks(task_id)
    if open_subtasks and not complete_subtasks:
        raise ValidationError(
            f"{len(open_subtasks)} open subtask(s) — complete all or close individually first",
            "subtasks",
        )
    if complete_subtasks:
        for sub in open_subtasks:
            sub.status = TaskStatus.ARCHIVED
    task.status = TaskStatus.ARCHIVED
    db.session.commit()
    return task


def delete_task(task_id: uuid.UUID) -> bool:
    """Soft-delete by setting status to DELETED. Returns False if not found.

    Also severs the task from any bulk-import batch by clearing
    ``batch_id``. This prevents the recycle bin flow from resurrecting
    a user-trashed task when the batch it came from is restored — the
    user explicitly trashed this one, so it should stay trashed.
    """
    task = get_task(task_id)
    if task is None:
        return False
    task.status = TaskStatus.DELETED
    task.batch_id = None
    db.session.commit()
    return True
