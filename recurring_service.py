"""Business logic for recurring tasks.

Recurring tasks are *templates* — they define what tasks should be created
automatically on certain days. The actual tasks that appear in the user's
Today tier are regular Task records spawned from these templates.

Key concepts:
- **frequency**: how often the task recurs
  - "daily" — every day
  - "weekly" — every week on a specific day
  - "day_of_week" — alias for weekly (uses ``day_of_week`` column)
- **day_of_week**: 0 = Monday, 6 = Sunday (Python's weekday() convention)
- **spawn**: creating a real Task from a recurring template for today
- **seed**: populating the default system recurring tasks from the spec
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from models import (
    RecurringFrequency,
    RecurringTask,
    Task,
    TaskType,
    Tier,
    db,
)


class ValidationError(Exception):
    """Raised when user input fails validation."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field


# --- Helpers -----------------------------------------------------------------


def _parse_enum(enum_cls, value: Any, field: str):
    if value is None:
        return None
    try:
        return enum_cls(str(value))
    except ValueError as e:
        raise ValidationError(f"invalid {field}: {value!r}", field) from e


def _parse_uuid(value: Any, field: str) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError) as e:
        raise ValidationError(f"invalid {field}", field) from e


# --- CRUD --------------------------------------------------------------------


def create_recurring(data: dict) -> RecurringTask:
    """Create a new recurring task template."""
    title = (data.get("title") or "").strip()
    if not title:
        raise ValidationError("title is required", "title")

    frequency = _parse_enum(RecurringFrequency, data.get("frequency"), "frequency")
    if frequency is None:
        raise ValidationError("frequency is required", "frequency")

    task_type = _parse_enum(TaskType, data.get("type"), "type")
    if task_type is None:
        raise ValidationError("type is required", "type")

    day_of_week = data.get("day_of_week")
    if frequency in (RecurringFrequency.WEEKLY, RecurringFrequency.DAY_OF_WEEK):
        if day_of_week is None:
            raise ValidationError(
                "day_of_week required for weekly/day_of_week frequency", "day_of_week"
            )
        try:
            day_of_week = int(day_of_week)
        except (TypeError, ValueError) as e:
            raise ValidationError("day_of_week must be integer 0-6", "day_of_week") from e
        if day_of_week < 0 or day_of_week > 6:
            raise ValidationError("day_of_week must be 0 (Mon) to 6 (Sun)", "day_of_week")

    rt = RecurringTask(
        title=title,
        frequency=frequency,
        day_of_week=day_of_week,
        type=task_type,
        project_id=_parse_uuid(data.get("project_id"), "project_id"),
    )
    db.session.add(rt)
    db.session.commit()
    return rt


def list_recurring(*, active_only: bool = True) -> list[RecurringTask]:
    """List all recurring task templates."""
    stmt = select(RecurringTask).order_by(RecurringTask.created_at.asc())
    if active_only:
        stmt = stmt.where(RecurringTask.is_active.is_(True))
    return list(db.session.scalars(stmt))


def get_recurring(rt_id: uuid.UUID) -> RecurringTask | None:
    return db.session.get(RecurringTask, rt_id)


def update_recurring(rt_id: uuid.UUID, data: dict) -> RecurringTask | None:
    """Update a recurring task template."""
    rt = get_recurring(rt_id)
    if rt is None:
        return None

    if "title" in data:
        title = (data["title"] or "").strip()
        if not title:
            raise ValidationError("title cannot be empty", "title")
        rt.title = title

    if "frequency" in data:
        rt.frequency = _parse_enum(
            RecurringFrequency, data["frequency"], "frequency"
        ) or rt.frequency

    if "day_of_week" in data:
        dow = data["day_of_week"]
        if dow is not None:
            try:
                dow = int(dow)
            except (TypeError, ValueError) as e:
                raise ValidationError("day_of_week must be integer 0-6", "day_of_week") from e
            if dow < 0 or dow > 6:
                raise ValidationError("day_of_week must be 0-6", "day_of_week")
        rt.day_of_week = dow

    if "type" in data:
        rt.type = _parse_enum(TaskType, data["type"], "type") or rt.type

    if "project_id" in data:
        rt.project_id = _parse_uuid(data["project_id"], "project_id")

    if "is_active" in data:
        rt.is_active = bool(data["is_active"])

    db.session.commit()
    return rt


def delete_recurring(rt_id: uuid.UUID) -> bool:
    """Soft-disable a recurring task (set is_active = False)."""
    rt = get_recurring(rt_id)
    if rt is None:
        return False
    rt.is_active = False
    db.session.commit()
    return True


# --- Spawn logic -------------------------------------------------------------


def tasks_due_today(*, target_date: date | None = None) -> list[RecurringTask]:
    """Return active recurring templates that should fire on the given date.

    A template fires if:
    - frequency is 'daily' (fires every day), OR
    - frequency is 'weekly' or 'day_of_week' AND day_of_week matches
      the target date's weekday (0=Monday, 6=Sunday)
    """
    today = target_date or date.today()
    weekday = today.weekday()

    stmt = select(RecurringTask).where(RecurringTask.is_active.is_(True))
    all_active = list(db.session.scalars(stmt))

    return [
        rt
        for rt in all_active
        if rt.frequency == RecurringFrequency.DAILY
        or (
            rt.frequency in (RecurringFrequency.WEEKLY, RecurringFrequency.DAY_OF_WEEK)
            and rt.day_of_week == weekday
        )
    ]


def spawn_today_tasks(*, target_date: date | None = None) -> list[Task]:
    """Create actual Task records from today's recurring templates.

    Each spawned task lands in the Today tier with status active.
    Returns the list of newly created tasks.

    This is designed to be called once per day (e.g., by a scheduled job
    or a manual "spawn" button). It does NOT check for duplicates — if
    called twice, it will create duplicates. The caller is responsible
    for ensuring it runs once per day.
    """
    templates = tasks_due_today(target_date=target_date)
    spawned = []
    for rt in templates:
        task = Task(
            title=rt.title,
            type=rt.type,
            tier=Tier.TODAY,
            project_id=rt.project_id,
        )
        db.session.add(task)
        spawned.append(task)
    if spawned:
        db.session.commit()
    return spawned


# --- Seed defaults -----------------------------------------------------------


_SYSTEM_DEFAULTS = [
    # Morning routine (daily)
    {"title": "Prep for meetings", "frequency": "daily", "type": "work"},
    {"title": "Review schedule", "frequency": "daily", "type": "work"},
    {"title": "Read 10 min", "frequency": "daily", "type": "personal"},
    # Evening routine (daily)
    {"title": "Review meeting notes", "frequency": "daily", "type": "work"},
    {"title": "Walk", "frequency": "daily", "type": "personal"},
    {"title": "Meditate", "frequency": "daily", "type": "personal"},
    # Monday
    {"title": "Agenda for working group meeting",
     "frequency": "day_of_week", "type": "work", "day_of_week": 0},
    # Tuesday
    {"title": "Update transformation scorecard",
     "frequency": "day_of_week", "type": "work", "day_of_week": 1},
    # Wednesday
    {"title": "1-1 deck submission", "frequency": "day_of_week", "type": "work", "day_of_week": 2},
    # Friday
    {"title": "Next week prep", "frequency": "day_of_week", "type": "work", "day_of_week": 4},
    {"title": "Reflection", "frequency": "day_of_week", "type": "personal", "day_of_week": 4},
    {"title": "2026 Plan review", "frequency": "day_of_week", "type": "work", "day_of_week": 4},
    # Weekend (Saturday = 5, Sunday = 6)
    {"title": "Masks", "frequency": "day_of_week", "type": "personal", "day_of_week": 5},
    {"title": "Meds", "frequency": "day_of_week", "type": "personal", "day_of_week": 5},
    {"title": "Laundry", "frequency": "day_of_week", "type": "personal", "day_of_week": 5},
    {"title": "Next week prep (weekend)",
     "frequency": "day_of_week", "type": "personal", "day_of_week": 6},
]


def seed_defaults() -> list[RecurringTask]:
    """Populate system default recurring tasks.

    Only creates templates that don't already exist (by title match)
    to avoid duplicates when called multiple times.
    """
    existing = {rt.title for rt in list_recurring(active_only=False)}
    created = []
    for defn in _SYSTEM_DEFAULTS:
        if defn["title"] in existing:
            continue
        rt = RecurringTask(
            title=defn["title"],
            frequency=RecurringFrequency(defn["frequency"]),
            day_of_week=defn.get("day_of_week"),
            type=TaskType(defn["type"]),
        )
        db.session.add(rt)
        created.append(rt)
    if created:
        db.session.commit()
    return created
