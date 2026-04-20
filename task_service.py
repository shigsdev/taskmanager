"""Business logic for tasks. Routes call into this module; models stay thin.

All mutations commit on success. All validation failures raise
``ValidationError`` so the route layer can map them to HTTP 422.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from models import RecurringTask, Task, TaskStatus, TaskType, Tier, db
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


# --- Tier auto-fill helpers (#28) --------------------------------------------


def _local_today_date() -> date:
    """Return "today" in the user's configured timezone.

    The server runs in UTC on Railway, but "today" from the user's POV
    follows ``DIGEST_TZ`` (default America/New_York). Using server UTC
    would make a 10pm-ET task land in tomorrow's Today-tier. Same TZ
    convention as the Tomorrow auto-roll cron (#27), so behaviour is
    self-consistent.
    """
    try:
        from zoneinfo import ZoneInfo
        tz_name = os.environ.get("DIGEST_TZ", "America/New_York")
        return datetime.now(ZoneInfo(tz_name)).date()
    except Exception:  # noqa: BLE001
        # ZoneInfo / tzdata unavailable → fall back to server local date.
        # Not ideal on Railway-UTC, but better than crashing.
        return date.today()


def _auto_fill_tier_due_date(task: Task, data: dict) -> None:
    """Backlog #28: when a task lands in TODAY / TOMORROW with no
    ``due_date`` set, fill ``due_date`` from the tier.

    Rules:
    - Fill-if-null only — an explicit user-provided ``due_date`` is
      never clobbered.
    - Skipped if the caller mentioned ``due_date`` in this request at
      all (even setting it to ``None`` is user intent; don't second-
      guess). Means: only auto-fills when the field wasn't in the
      payload.
    - Only fires for TODAY and TOMORROW. Moving back out to Backlog /
      Freezer / etc. does NOT clear an auto-filled due_date — the
      date is still meaningful as a reminder (per the backlog's
      design note).
    """
    if "due_date" in data:
        return
    if task.due_date is not None:
        return
    if task.tier == Tier.TODAY:
        task.due_date = _local_today_date()
    elif task.tier == Tier.TOMORROW:
        task.due_date = _local_today_date() + timedelta(days=1)


# --- Repeat helpers ----------------------------------------------------------


def _snapshot_subtasks(task: Task) -> list[dict]:
    """Capture parent's currently-active subtask titles for #26 cloning.

    Only ACTIVE subtasks are snapshotted — completed/cancelled/deleted
    subtasks from the previous cycle don't make sense to clone forward.
    Each snapshot entry is `{"title": str}`; we deliberately keep this
    minimal so adding fields later (project_id override, due offset)
    doesn't break old rows.
    """
    return [
        {"title": s.title}
        for s in task.subtasks
        if s.status == TaskStatus.ACTIVE
    ]


def _apply_repeat(task: Task, repeat: dict) -> None:
    """Create or update a RecurringTask template linked to the given task."""
    from recurring_service import create_recurring

    rt_data = {
        "title": task.title,
        "type": task.type.value,
        "frequency": repeat.get("frequency"),
        "day_of_week": repeat.get("day_of_week"),
        "day_of_month": repeat.get("day_of_month"),
        "week_of_month": repeat.get("week_of_month"),
        "project_id": str(task.project_id) if task.project_id else None,
        "goal_id": str(task.goal_id) if task.goal_id else None,
        "notes": task.notes,
        "checklist": task.checklist,
        "url": task.url,
        "subtasks_snapshot": _snapshot_subtasks(task),
    }
    rt = create_recurring(rt_data)
    task.recurring_task_id = rt.id


def _update_repeat(task: Task, repeat: dict | None) -> None:
    """Update or remove the recurring template linked to a task."""
    if repeat is None:
        # Remove repeat — deactivate linked template
        if task.recurring_task_id:
            rt = db.session.get(RecurringTask, task.recurring_task_id)
            if rt:
                rt.is_active = False
            task.recurring_task_id = None
        return

    if task.recurring_task_id:
        # Update existing template
        from recurring_service import update_recurring

        update_data = {
            "title": task.title,
            "type": task.type.value,
            "frequency": repeat.get("frequency"),
            "day_of_week": repeat.get("day_of_week"),
            "day_of_month": repeat.get("day_of_month"),
            "week_of_month": repeat.get("week_of_month"),
            "project_id": str(task.project_id) if task.project_id else None,
            "goal_id": str(task.goal_id) if task.goal_id else None,
            "notes": task.notes,
            "checklist": task.checklist,
            "url": task.url,
            "subtasks_snapshot": _snapshot_subtasks(task),
            "is_active": True,
        }
        update_recurring(task.recurring_task_id, update_data)
    else:
        _apply_repeat(task, repeat)


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
    parent = None
    if parent_id is not None:
        parent = get_task(parent_id)
        if parent is None:
            raise ValidationError("parent task not found", "parent_id")
        if parent.parent_id is not None:
            raise ValidationError("subtasks cannot have their own subtasks", "parent_id")

    # Subtasks inherit goal and project from parent when not explicitly set
    goal_id = _parse_uuid(data.get("goal_id"), "goal_id")
    project_id = _parse_uuid(data.get("project_id"), "project_id")
    if parent is not None:
        if goal_id is None:
            goal_id = parent.goal_id
        if project_id is None:
            project_id = parent.project_id

    task = Task(
        title=title,
        type=task_type,
        tier=tier,
        parent_id=parent_id,
        project_id=project_id,
        goal_id=goal_id,
        due_date=_parse_date(data.get("due_date")),
        url=_parse_url(data.get("url")),
        notes=(data.get("notes") or None),
        checklist=_parse_checklist(data.get("checklist")),
        sort_order=_parse_int(data.get("sort_order", 0), "sort_order"),
    )
    # #28: fill due_date from tier when TODAY/TOMORROW and no explicit value.
    _auto_fill_tier_due_date(task, data)
    db.session.add(task)
    db.session.flush()  # assign task.id before linking recurring template

    repeat = data.get("repeat")
    if isinstance(repeat, dict):
        _apply_repeat(task, repeat)

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
    "repeat",
    "cancellation_reason",
}


def update_task(task_id: uuid.UUID, data: dict) -> Task | None:
    task = get_task(task_id)
    if task is None:
        return None

    # Snapshot pre-update values so we can cascade goal/project changes to
    # subtasks that still mirror the parent's old value (see below).
    old_goal_id = task.goal_id
    old_project_id = task.project_id

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
        new_status = _parse_enum(TaskStatus, data["status"], "status") or task.status
        # When transitioning out of CANCELLED, clear the reason so a stale
        # explanation doesn't outlive the cancellation. Caller can still
        # set it explicitly in the same PATCH if they want to preserve it.
        if (
            task.status == TaskStatus.CANCELLED
            and new_status != TaskStatus.CANCELLED
            and "cancellation_reason" not in data
        ):
            task.cancellation_reason = None
        task.status = new_status

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

    if "cancellation_reason" in data:
        # Empty string normalizes to None so the field clears cleanly when
        # the user un-cancels a task (status → active) and re-cancels later.
        reason = data["cancellation_reason"]
        if reason is not None:
            reason = str(reason).strip()
        task.cancellation_reason = reason or None

    if "checklist" in data:
        task.checklist = _parse_checklist(data["checklist"])

    if "sort_order" in data:
        task.sort_order = _parse_int(data["sort_order"], "sort_order")

    if "repeat" in data:
        _update_repeat(task, data["repeat"])

    # #28: after all explicit updates, if the tier is TODAY/TOMORROW
    # and due_date ended up null (and wasn't explicitly set in this
    # payload), fill it from the tier. Runs on every update — catches
    # drag-to-today, bulk tier change, capture-bar #today with no
    # explicit date, etc.
    _auto_fill_tier_due_date(task, data)

    unknown = set(data) - _UPDATABLE_FIELDS
    if unknown:
        raise ValidationError(f"unknown fields: {sorted(unknown)}", next(iter(unknown)))

    # Cascade goal/project changes from a parent task down to its active
    # subtasks. Mirrors the creation-time inheritance rule: only subtasks
    # that still match the parent's OLD value are updated, so an explicit
    # override (subtask.goal_id != old_goal_id) is left alone. Subtasks
    # cannot themselves have subtasks (one-level-deep), so tasks with a
    # parent_id never cascade.
    if task.parent_id is None:
        goal_changed = "goal_id" in data and task.goal_id != old_goal_id
        project_changed = "project_id" in data and task.project_id != old_project_id
        if goal_changed or project_changed:
            for sub in task.subtasks:
                if sub.status != TaskStatus.ACTIVE:
                    continue
                if goal_changed and sub.goal_id == old_goal_id:
                    sub.goal_id = task.goal_id
                if project_changed and sub.project_id == old_project_id:
                    sub.project_id = task.project_id

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


# --- Bulk operations --------------------------------------------------------


def bulk_update_tasks(
    task_ids: list[uuid.UUID],
    updates: dict,
) -> dict:
    """Apply the same `updates` dict to every task in `task_ids`.

    Reuses the per-task ``update_task`` for each id so cascade rules
    (subtask goal/project inheritance, etc.) and field-level
    validation behave identically to single-task updates.

    Args:
        task_ids: List of task UUIDs to update.
        updates: Dict of fields to apply to each. Same shape as the
            JSON body of ``PATCH /api/tasks/<id>``.

    Returns:
        ``{"updated": int, "not_found": [ids], "errors": [{"id", "field", "message"}]}``

        - ``updated`` = number of tasks successfully updated
        - ``not_found`` = task_ids that didn't resolve to an existing task
        - ``errors`` = per-task validation failures (e.g. unknown field on
          one task but valid on another). The successful tasks are
          committed; failed tasks are skipped, not rolled back. Bulk
          ops are best-effort by design — a partial failure shouldn't
          undo the successes.

    Why not run inside a single transaction with rollback-on-any-error:
    a typo in `updates` would invalidate the entire batch with no UI
    way to know which task triggered it. Per-task try/except gives
    the user a precise error report and keeps the partial progress.
    """
    updated = 0
    not_found: list[str] = []
    errors: list[dict] = []
    for tid in task_ids:
        try:
            task = update_task(tid, dict(updates))
        except ValidationError as e:
            errors.append({"id": str(tid), "field": e.field, "message": str(e)})
            db.session.rollback()
            continue
        if task is None:
            not_found.append(str(tid))
            continue
        updated += 1
    return {
        "updated": updated,
        "not_found": not_found,
        "errors": errors,
    }


# --- Scheduled background operations ----------------------------------------


def roll_tomorrow_to_today() -> int:
    """Move every active ``TOMORROW`` task to ``TODAY``.

    Called by APScheduler at the user's local midnight (#27). Uses an
    isolated SQLAlchemy session rather than Flask-SQLAlchemy's
    ``db.session`` because this runs from a scheduler thread outside
    any request context — same pattern as ``DBLogHandler`` and
    ``_ensure_postgres_enum_values``. Returns the number of rows
    rolled (useful for tests and future scheduler-heartbeat logs).

    Only ACTIVE tasks move. Archived / cancelled / deleted Tomorrow
    tasks stay put — rolling them would resurrect end-states, which
    is surprising.
    """
    from sqlalchemy import update
    from sqlalchemy.orm import Session

    with Session(db.engine) as session:
        result = session.execute(
            update(Task)
            .where(
                Task.tier == Tier.TOMORROW,
                Task.status == TaskStatus.ACTIVE,
            )
            .values(tier=Tier.TODAY)
        )
        session.commit()
        return result.rowcount or 0

