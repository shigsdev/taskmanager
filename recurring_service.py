"""Business logic for recurring tasks.

Recurring tasks are *templates* — they define what tasks should be created
automatically on certain days. The actual tasks that appear in the user's
Today tier are regular Task records spawned from these templates.

Key concepts:
- **frequency**: how often the task recurs
  - "daily" — every day
  - "weekdays" — Monday through Friday
  - "weekly" — every week on a specific day
  - "day_of_week" — alias for weekly (uses ``day_of_week`` column)
  - "monthly_date" — same day of the month (e.g. the 15th)
  - "monthly_nth_weekday" — nth weekday of the month (e.g. first Monday)
- **day_of_week**: 0 = Monday, 6 = Sunday (Python's weekday() convention)
- **day_of_month**: 1–31 for monthly_date frequency
- **week_of_month**: 1–4 for monthly_nth_weekday (1 = first, 4 = fourth)
- **spawn**: creating a real Task from a recurring template for today
- **seed**: populating the default system recurring tasks from the spec
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select

from models import (
    RecurringFrequency,
    RecurringTask,
    Task,
    TaskType,
    Tier,
    db,
)
from utils import ValidationError  # noqa: F401 — re-exported for API layer
from utils import parse_enum as _parse_enum
from utils import parse_uuid as _parse_uuid

# --- Field parsers -----------------------------------------------------------


def _parse_day_of_week(value: object) -> int | None:
    if value is None:
        return None
    try:
        v = int(value)
    except (TypeError, ValueError) as e:
        raise ValidationError("day_of_week must be integer 0-6", "day_of_week") from e
    if v < 0 or v > 6:
        raise ValidationError("day_of_week must be 0 (Mon) to 6 (Sun)", "day_of_week")
    return v


def _parse_day_of_month(value: object) -> int | None:
    if value is None:
        return None
    try:
        v = int(value)
    except (TypeError, ValueError) as e:
        raise ValidationError("day_of_month must be integer 1-31", "day_of_month") from e
    if v < 1 or v > 31:
        raise ValidationError("day_of_month must be 1-31", "day_of_month")
    return v


def _parse_week_of_month(value: object) -> int | None:
    if value is None:
        return None
    try:
        v = int(value)
    except (TypeError, ValueError) as e:
        raise ValidationError("week_of_month must be integer 1-4", "week_of_month") from e
    if v < 1 or v > 4:
        raise ValidationError("week_of_month must be 1-4", "week_of_month")
    return v


def _nth_weekday_of_month(target_date: date) -> int:
    """Return which occurrence of this weekday it is within the month (1-based).

    E.g. if target_date is the second Monday of the month, returns 2.
    """
    return (target_date.day - 1) // 7 + 1


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

    day_of_week = _parse_day_of_week(data.get("day_of_week"))
    day_of_month = _parse_day_of_month(data.get("day_of_month"))
    week_of_month = _parse_week_of_month(data.get("week_of_month"))

    if (
        frequency in (RecurringFrequency.WEEKLY, RecurringFrequency.DAY_OF_WEEK)
        and day_of_week is None
    ):
        raise ValidationError(
            "day_of_week required for weekly/day_of_week frequency", "day_of_week"
        )

    if frequency == RecurringFrequency.MONTHLY_DATE and day_of_month is None:
        raise ValidationError(
            "day_of_month required for monthly_date frequency", "day_of_month"
        )

    if frequency == RecurringFrequency.MONTHLY_NTH_WEEKDAY:
        if week_of_month is None:
            raise ValidationError(
                "week_of_month required for monthly_nth_weekday frequency", "week_of_month"
            )
        if day_of_week is None:
            raise ValidationError(
                "day_of_week required for monthly_nth_weekday frequency", "day_of_week"
            )

    rt = RecurringTask(
        title=title,
        frequency=frequency,
        day_of_week=day_of_week,
        day_of_month=day_of_month,
        week_of_month=week_of_month,
        type=task_type,
        project_id=_parse_uuid(data.get("project_id"), "project_id"),
        goal_id=_parse_uuid(data.get("goal_id"), "goal_id"),
        notes=data.get("notes") or None,
        checklist=data.get("checklist") if isinstance(data.get("checklist"), list) else None,
        url=data.get("url") or None,
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
        rt.day_of_week = _parse_day_of_week(data["day_of_week"])

    if "day_of_month" in data:
        rt.day_of_month = _parse_day_of_month(data["day_of_month"])

    if "week_of_month" in data:
        rt.week_of_month = _parse_week_of_month(data["week_of_month"])

    if "type" in data:
        rt.type = _parse_enum(TaskType, data["type"], "type") or rt.type

    if "project_id" in data:
        rt.project_id = _parse_uuid(data["project_id"], "project_id")

    if "goal_id" in data:
        rt.goal_id = _parse_uuid(data["goal_id"], "goal_id")

    if "notes" in data:
        rt.notes = data["notes"] or None

    if "checklist" in data:
        rt.checklist = data["checklist"] if isinstance(data["checklist"], list) else None

    if "url" in data:
        rt.url = data["url"] or None

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


def _template_fires_on(rt: RecurringTask, target: date) -> bool:
    """Return True if the recurring template should fire on the given date."""
    weekday = target.weekday()

    if rt.frequency == RecurringFrequency.DAILY:
        return True

    if rt.frequency == RecurringFrequency.WEEKDAYS:
        return weekday < 5  # Mon=0 .. Fri=4

    if rt.frequency in (RecurringFrequency.WEEKLY, RecurringFrequency.DAY_OF_WEEK):
        return rt.day_of_week == weekday

    if rt.frequency == RecurringFrequency.MONTHLY_DATE:
        return target.day == rt.day_of_month

    if rt.frequency == RecurringFrequency.MONTHLY_NTH_WEEKDAY:
        return (
            rt.day_of_week == weekday
            and _nth_weekday_of_month(target) == rt.week_of_month
        )

    return False


def tasks_due_today(*, target_date: date | None = None) -> list[RecurringTask]:
    """Return active recurring templates that should fire on the given date."""
    today = target_date or date.today()

    stmt = select(RecurringTask).where(RecurringTask.is_active.is_(True))
    all_active = list(db.session.scalars(stmt))

    return [rt for rt in all_active if _template_fires_on(rt, today)]


def spawn_today_tasks(*, target_date: date | None = None) -> list[Task]:
    """Create actual Task records from today's recurring templates.

    Each spawned task lands in the Today tier with status active.
    Returns the list of newly created tasks.

    Idempotent — if a task with the same title already exists in Today
    (active status), it will not be created again. Safe to call multiple
    times per day.
    """
    from models import TaskStatus

    templates = tasks_due_today(target_date=target_date)

    # Check existing active Today tasks to prevent duplicates
    existing_titles = {
        t.title
        for t in db.session.scalars(
            select(Task).where(
                Task.tier == Tier.TODAY,
                Task.status == TaskStatus.ACTIVE,
            )
        )
    }

    spawned = []
    for rt in templates:
        if rt.title in existing_titles:
            continue
        task = Task(
            title=rt.title,
            type=rt.type,
            tier=Tier.TODAY,
            project_id=rt.project_id,
            goal_id=rt.goal_id,
            notes=rt.notes,
            checklist=list(rt.checklist) if rt.checklist else None,
            url=rt.url,
            recurring_task_id=rt.id,
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
