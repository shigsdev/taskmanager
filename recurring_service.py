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


def _clean_subtasks_snapshot(value: object) -> list[dict]:
    """Normalise a subtasks_snapshot payload to a list of {"title": str}.

    Accepts a list of dicts (each with a "title" key), strips empty/
    non-string titles, and ignores any other keys for forward-compat.
    Returns [] for None / non-list inputs so the column always holds
    a JSON array (never null) — easier to query and iterate over.
    """
    if not isinstance(value, list):
        return []
    out: list[dict] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        title = entry.get("title")
        if not isinstance(title, str):
            continue
        title = title.strip()
        if not title:
            continue
        out.append({"title": title})
    return out


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
        subtasks_snapshot=_clean_subtasks_snapshot(data.get("subtasks_snapshot")),
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

    if "subtasks_snapshot" in data:
        rt.subtasks_snapshot = _clean_subtasks_snapshot(data["subtasks_snapshot"])

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


def compute_previews_in_range(
    *, start: date, end: date,
) -> list[dict]:
    """Return preview instances for active recurring templates firing in
    the inclusive date range ``[start, end]`` (backlog #32).

    Each preview is a dict with the template's metadata + the ``fire_date``
    it's scheduled for. Used by the This Week / Next Week panels to show
    "what's coming this week" without materialising Task rows ahead of
    time (that was rejected in Option B of the 2026-04-20 discussion).

    Same-day collision filtering: if a real Task already exists with
    ``recurring_task_id == template.id`` AND a ``created_at`` date within
    the range, the preview for that fire_date is dropped. Otherwise the
    user would see a phantom preview next to the real Task it spawned.

    Inactive templates (is_active=False) are never previewed.
    """
    if end < start:
        return []

    stmt = select(RecurringTask).where(RecurringTask.is_active.is_(True))
    all_active = list(db.session.scalars(stmt))

    # Pre-fetch Task rows that already spawned from any of these templates
    # within the range, so we can filter same-day collisions in one pass.
    # We check ``created_at`` (when the Task was spawned) rather than some
    # "spawn_date" field because we don't have one — the spawn IS the
    # create, so created_at's date is authoritative.
    template_ids = [rt.id for rt in all_active]
    spawned_by_template_and_day: set[tuple] = set()
    if template_ids:
        # Bucket each spawned Task's created_at by the user's LOCAL
        # date (DIGEST_TZ), not UTC. Matches the "today" semantics from
        # #28 / `_local_today_date()`. Without this, a Task spawned at
        # 8pm ET lives in UTC-tomorrow and the collision filter misses
        # the user-facing today cycle — making previews double-render
        # around the UTC-midnight boundary. Bug was latent until the
        # #32 test ran across the UTC boundary.
        try:
            import os as _os
            from zoneinfo import ZoneInfo
            _tz = ZoneInfo(_os.environ.get("DIGEST_TZ", "America/New_York"))
        except Exception:  # noqa: BLE001
            _tz = None
        spawned = db.session.scalars(
            select(Task).where(
                Task.recurring_task_id.in_(template_ids),
            )
        )
        for task in spawned:
            created = task.created_at
            # If created_at has no tzinfo (SQLite), treat it as UTC.
            if _tz is not None and created is not None:
                if created.tzinfo is None:
                    from datetime import UTC
                    created = created.replace(tzinfo=UTC)
                bucket_date = created.astimezone(_tz).date()
            else:
                bucket_date = created.date() if created else None
            if bucket_date is None:
                continue
            key = (task.recurring_task_id, bucket_date)
            spawned_by_template_and_day.add(key)

    previews: list[dict] = []
    # Iterate day-by-day across the range. 14 days max is our real
    # upper bound (this_week + next_week), so this loop is trivially cheap.
    current = start
    while current <= end:
        for rt in all_active:
            if not _template_fires_on(rt, current):
                continue
            if (rt.id, current) in spawned_by_template_and_day:
                continue  # collision — real task already exists for this day
            previews.append({
                "template_id": str(rt.id),
                "title": rt.title,
                "type": rt.type.value,
                "frequency": rt.frequency.value,
                "project_id": str(rt.project_id) if rt.project_id else None,
                "goal_id": str(rt.goal_id) if rt.goal_id else None,
                "fire_date": current.isoformat(),
                "notes": rt.notes,
                "url": rt.url,
            })
        current = date.fromordinal(current.toordinal() + 1)

    return previews


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

    # Commit parents first so they get IDs we can reference as parent_id
    # for the subtask clone pass below (#26).
    if spawned:
        db.session.commit()

    # Subtask clone (#26): for each spawned parent that came from a
    # template with a non-empty subtasks_snapshot, create one Task per
    # snapshot entry with parent_id set. Subtasks land in Today with
    # status active; they inherit goal_id/project_id from the parent
    # via the existing subtask cascade on update_task — but since we're
    # creating them fresh here we set those fields explicitly.
    subtasks_created: list[Task] = []
    for parent in spawned:
        rt = next((t for t in templates if t.id == parent.recurring_task_id), None)
        if rt is None or not rt.subtasks_snapshot:
            continue
        for entry in rt.subtasks_snapshot:
            # Defensive: older rows or direct DB writes may contain
            # anything. Only accept dicts with a non-empty string title.
            if not isinstance(entry, dict):
                continue
            title = entry.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            title = title.strip()
            sub = Task(
                title=title,
                type=parent.type,
                tier=Tier.TODAY,
                parent_id=parent.id,
                project_id=parent.project_id,
                goal_id=parent.goal_id,
                # Subtasks don't inherit notes/checklist/url — those are
                # parent-level metadata and would clutter every subtask.
            )
            db.session.add(sub)
            subtasks_created.append(sub)

    if subtasks_created:
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
