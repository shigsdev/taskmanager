"""Business logic for tasks. Routes call into this module; models stay thin.

All mutations commit on success. All validation failures raise
``ValidationError`` so the route layer can map them to HTTP 422.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
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


# PR63 audit fix #128: helper moved to utils.py so recurring/review/
# digest services can share it without a circular import. Kept as a
# thin alias here because external callers import the underscored name
# directly (and removing it would be a churn-y refactor).
from utils import local_today_date as _local_today_date  # noqa: E402, F401


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


# #74 (2026-04-26): when a task's `due_date` is set, route the tier to
# match the date by default. Per scoping: ALWAYS overwrite, except
# - FREEZER (user explicitly parked it; treat the date as a reminder,
#   not a commitment to do it that day)
# - status != ACTIVE (completed/cancelled/deleted are immutable)
# - caller explicitly set both `tier` AND `due_date` in same payload
#   (intentional combo like "plan for today but track in this_week")
#
# Subsumes the older _auto_promote_tier_on_due_today (#46) which only
# handled the today case.
_FROZEN_TIERS = frozenset({Tier.FREEZER})


def _tier_for_due_date(due_date: date) -> Tier:
    """Map a due_date to its natural tier per #72 Mon-Sat week boundaries.

    today               → TODAY
    tomorrow            → TOMORROW
    within this Mon-Sat → THIS_WEEK
    within next Mon-Sat → NEXT_WEEK
    anything later      → BACKLOG
    Sunday handling: a Sunday today maps to "this week = just-ended
    Mon-Sat" (consistent with the JS _tierDateRange helper).
    """
    today = _local_today_date()
    tomorrow = today + timedelta(days=1)
    if due_date == today:
        return Tier.TODAY
    if due_date == tomorrow:
        return Tier.TOMORROW
    # JS weekday: Mon=0, Sun=6. Same convention as Python's date.weekday().
    days_since_monday = today.weekday()
    this_monday = today - timedelta(days=days_since_monday)
    this_saturday = this_monday + timedelta(days=5)
    next_monday = this_monday + timedelta(days=7)
    next_saturday = this_monday + timedelta(days=12)
    if this_monday <= due_date <= this_saturday:
        return Tier.THIS_WEEK
    if next_monday <= due_date <= next_saturday:
        return Tier.NEXT_WEEK
    return Tier.BACKLOG


def _auto_promote_tier_on_due_today(task: Task, data: dict) -> None:
    """#74 (2026-04-26): when due_date changes, auto-route the tier to
    match the date's natural bucket. Always overwrites unless the
    caller is also explicit about tier, the task is FREEZER, or the
    task is non-ACTIVE.

    Function name kept for backwards-compat with call sites; the body
    now covers ALL date-to-tier mappings, not just today.
    """
    if "due_date" not in data:
        return
    # Caller explicit about both: respect the combination.
    if "tier" in data:
        return
    if task.due_date is None:
        return
    if task.tier in _FROZEN_TIERS:
        return
    # task.status is None on freshly-constructed Task() before flush —
    # treat that as ACTIVE (model default). Only skip when explicitly
    # not ACTIVE (archived/cancelled/deleted).
    if task.status is not None and task.status != TaskStatus.ACTIVE:
        return
    task.tier = _tier_for_due_date(task.due_date)


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
        "end_date": repeat.get("end_date"),  # #101 (PR30)
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
            "end_date": repeat.get("end_date"),  # #101 (PR30)
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
    # #77 (2026-04-26): if a project is set and the caller did NOT also
    # specify goal_id explicitly, cascade the project's goal onto the new
    # task. Always overwrite path is enforced via update_task; here we
    # only fill the gap when goal_id wasn't passed (so explicit caller
    # intent wins). Subtask parent-inherit above already ran.
    if project_id is not None and "goal_id" not in data:
        from models import Project
        proj = db.session.get(Project, project_id)
        if proj is not None and proj.goal_id is not None:
            goal_id = proj.goal_id

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
    # #46: inverse direction — promote tier to TODAY when user creates
    # a task with due_date=today in a planning tier (this_week / next_week
    # / backlog). Same hook as update_task; symmetric.
    _auto_promote_tier_on_due_today(task, data)
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
        # #77 (2026-04-26) + PR24 audit refinement (BUG-2):
        #   - Assigning a project WITH a goal → cascade the goal onto
        #     the task (always overwrite — feature, not bug).
        #   - Assigning a project WITHOUT a goal → preserve the task's
        #     existing goal (silent-data-loss otherwise — the audit
        #     finding).
        #   - Clearing the project (project_id → None) → clear the goal
        #     too. Same as before — unwinding the inheritance.
        # If the caller ALSO sets goal_id explicitly in this same
        # payload, that wins via the next branch which writes after.
        if task.project_id is not None:
            from models import Project
            proj = db.session.get(Project, task.project_id)
            if proj and proj.goal_id is not None:
                task.goal_id = proj.goal_id
            # else: project has no goal — preserve task's existing goal
        else:
            task.goal_id = None

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

    # #46: inverse direction — if the user just set due_date to today
    # AND the tier is in {THIS_WEEK, NEXT_WEEK, BACKLOG} (and they
    # didn't also explicitly set tier), promote tier to TODAY. The
    # mid-day complement to the 00:02 promote_due_today_tasks cron.
    _auto_promote_tier_on_due_today(task, data)

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


def realign_tiers_with_due_dates() -> int:
    """#108 (PR43, 2026-04-27): re-route every active task whose tier
    no longer matches its due_date.

    The bug this closes: setting a due_date on a planning-tier task
    runs `_tier_for_due_date` at write-time, but the calendar advances
    every day. A task you set 3 days ago with due_date=Apr 28 landed
    in THIS_WEEK because Apr 28 was 3 days out. Today (Apr 27) Apr 28
    is "tomorrow" — but no job re-runs the mapping, so the task sticks
    in This Week. User sees a "tomorrow" task under This Week's
    Tuesday day-group, never in the Tomorrow panel.

    Called by APScheduler at the user's local 00:03, AFTER the 00:01
    `roll_tomorrow_to_today` and 00:02 `promote_due_today_tasks`.
    Together: 00:01 moves yesterday's Tomorrow → Today; 00:02 promotes
    due-today planning tasks → Today; 00:03 re-aligns everything else
    so This_Week / Next_Week / Backlog tasks slide into the right
    bucket as the calendar advances.

    Excluded:
    - INBOX: still needs triage; auto-route would skip the user
    - FREEZER: explicit user park; outranks the date
    - non-ACTIVE: archived/cancelled stay where they ended

    Returns the number of rows updated. Idempotent — re-running
    when nothing has drifted is a no-op.
    """
    from sqlalchemy.orm import Session

    skip_tiers = _FROZEN_TIERS | {Tier.INBOX}
    updated = 0
    with Session(db.engine) as session:
        rows = session.scalars(
            select(Task).where(
                Task.due_date.is_not(None),
                Task.status == TaskStatus.ACTIVE,
            )
        ).all()
        for t in rows:
            if t.tier in skip_tiers:
                continue
            # Compute the "right" tier for this due_date as of today.
            # Inline computation so we don't have to import + monkey-
            # around with the module-level helpers in a fresh session.
            new_tier = _tier_for_due_date(t.due_date)
            if new_tier != t.tier:
                t.tier = new_tier
                updated += 1
        if updated:
            session.commit()
        return updated


def promote_due_today_tasks() -> int:
    """Move every active task with ``due_date == today`` from a planning
    tier (THIS_WEEK / NEXT_WEEK / BACKLOG) to TODAY.

    Called by APScheduler at the user's local 00:02 (#46), right after
    the 00:01 ``roll_tomorrow_to_today`` and before the 00:05
    ``recurring_spawn``. Mirrors the design of #27: when the date a
    task is committed to ARRIVES, the task should be in Today —
    regardless of which planning tier it was previously parked in.

    Excluded tiers (and why):
    - TODAY: already there — no-op
    - TOMORROW: handled by the 00:01 cron
    - INBOX: still needs triage; promoting bypasses that step
    - FREEZER: user explicitly parked it; their freeze decision
      outranks the date

    Only ACTIVE tasks move. Same isolated-session pattern as
    ``roll_tomorrow_to_today``. Returns the number of rows promoted.

    Closes bug #46: the "Friday Meds task due today shows in This Week
    panel but not in Today" report. Pairs with #38's cross-tier dedup —
    the spawn cron correctly skips a TODAY duplicate when a same-fire-
    date task already exists in this_week, but THIS cron then promotes
    that task into Today so the user sees it where they expect.
    """
    from sqlalchemy import update
    from sqlalchemy.orm import Session

    target_date = _local_today_date()
    with Session(db.engine) as session:
        result = session.execute(
            update(Task)
            .where(
                Task.tier.in_({Tier.THIS_WEEK, Tier.NEXT_WEEK, Tier.BACKLOG}),
                Task.due_date == target_date,
                Task.status == TaskStatus.ACTIVE,
            )
            .values(tier=Tier.TODAY)
        )
        session.commit()
        return result.rowcount or 0

