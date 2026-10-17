"""Business logic for tasks. Routes call into this module; models stay thin.

All mutations commit on success. All validation failures raise
``ValidationError`` so the route layer can map them to HTTP 422.
"""
from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from link_service import check_link_changes, unlink_other_type_project
from models import RecurringTask, Task, TaskStatus, TaskType, Tier, db
from utils import ValidationError  # noqa: F401 — re-exported for API layer
from utils import check_length as _check_length
from utils import max_length as _max_length
from utils import parse_enum as _parse_enum
from utils import parse_int as _parse_int
from utils import parse_text as _parse_text
from utils import parse_uuid as _parse_uuid

# --- Task-specific coercion helpers ------------------------------------------

# #447: column widths (Postgres refuses anything longer). Typed values are
# refused with a clear message; see utils.check_length.
_TITLE_MAX = _max_length(Task.__table__.c.title)
_URL_MAX = _max_length(Task.__table__.c.url)
_REASON_MAX = _max_length(Task.__table__.c.cancellation_reason)


def _check_title(title: str) -> str:
    return _check_length(title, _TITLE_MAX, "title", "Title")


def _check_reason(reason: str | None) -> str | None:
    return _check_length(reason, _REASON_MAX, "cancellation_reason", "Cancellation reason")


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
    return _check_length(url, _URL_MAX, "url", "URL")


def _parse_checklist(value: Any) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError("checklist must be a list", "checklist")
    if not all(isinstance(item, dict) for item in value):  # #476
        raise ValidationError("checklist items must be objects", "checklist")
    return value


def _check_repeat(value: Any) -> dict | None:
    """#476: ``repeat`` is an object or null — a string or list reached
    ``repeat.get`` in the template sync (500)."""
    if value is not None and not isinstance(value, dict):
        raise ValidationError("repeat must be an object or null", "repeat")
    return value


# --- Canonical Task serializer (#200) ----------------------------------------


def _serialize_repeat(task: Task) -> dict | None:
    """Build the repeat object from a task's linked RecurringTask template.

    Canonical home for the repeat-payload logic (#200). ``tasks_api`` keeps
    a thin re-export so its own call sites / test patches are unaffected.
    """
    rt = task.recurring_task if task.recurring_task_id else None
    if rt is None or not rt.is_active:
        return None
    result = {
        "template_id": str(rt.id),  # added for #32 preview-click lookup
        "frequency": rt.frequency.value,
    }
    if rt.day_of_week is not None:
        result["day_of_week"] = rt.day_of_week
    # #271 (2026-05-31): expose the MULTI_DAY_OF_WEEK weekday set so the
    # detail panel's "Specific weekdays" selector can pre-check the boxes
    # when re-opening an existing multi-day template. The create/spawn
    # path (_apply_repeat, _template_fires_on) already round-trips this;
    # only the read-back serialization was missing it.
    if rt.days_of_week:
        result["days_of_week"] = rt.days_of_week
    if rt.day_of_month is not None:
        result["day_of_month"] = rt.day_of_month
    if rt.week_of_month is not None:
        result["week_of_month"] = rt.week_of_month
    # #101 (PR30): expose the optional sunset date on the task payload
    # so the detail-panel form can pre-populate it.
    if rt.end_date is not None:
        result["end_date"] = rt.end_date.isoformat()
    # #501: and the start date, so the panel can show and change it.
    if rt.start_date is not None:
        result["start_date"] = rt.start_date.isoformat()
    return result


def _column_value(value: Any) -> Any:
    """Coerce a raw SQLAlchemy column value to a JSON-safe primitive.

    UUID → str, date/datetime → ISO string, Enum → its ``.value``,
    everything else (str, int, bool, list, dict, None) passes through.
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def serialize_task(task: Task, *, view: str = "full") -> dict:
    """Canonical Task→dict. view ∈ {"full","review","export"}.

    Single source of truth for Task serialization (#200) — replaces three
    hand-written, drifted serializers (``tasks_api._serialize``,
    ``review_api._serialize``, and ``app.export_data``'s inline
    ``serialize_task``). The export view dropped columns silently before
    this consolidation, so a "full backup" lost data.

    - ``view="export"`` includes EVERY column on the ``Task`` model,
      derived from ``Task.__table__.columns`` so it can never drift —
      adding a future Task column automatically appears in the backup.
      No computed relationship fields (repeat / subtask counts) are
      included: a full export must not trigger N+1 subtask queries.
    - ``view="full"`` reproduces ``tasks_api._serialize`` — the complete
      API payload including ``repeat``, ``subtask_count``, ``subtask_done``.
    - ``view="review"`` reproduces ``review_api._serialize`` — the subset
      the weekly-review flow needs.
    """
    if view == "export":
        # Derive the column list from the model so a new Task column is
        # captured automatically (drift-gated by test_task_serializer).
        return {
            col.name: _column_value(getattr(task, col.name))
            for col in Task.__table__.columns
        }

    if view == "review":
        return {
            "id": str(task.id),
            "title": task.title,
            "tier": task.tier.value,
            "type": task.type.value,
            "status": task.status.value,
            "project_id": str(task.project_id) if task.project_id else None,
            "goal_id": str(task.goal_id) if task.goal_id else None,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "notes": task.notes,
            "checklist": task.checklist or [],
            "last_reviewed": (
                task.last_reviewed.isoformat() if task.last_reviewed else None
            ),
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
        }

    if view != "full":
        raise ValueError(f"unknown serializer view: {view!r}")

    active_subtasks = [
        s for s in task.subtasks if s.status == TaskStatus.ACTIVE
    ]
    done_subtasks = [
        s for s in task.subtasks if s.status == TaskStatus.ARCHIVED
    ]
    return {
        "id": str(task.id),
        "title": task.title,
        "tier": task.tier.value,
        "type": task.type.value,
        "status": task.status.value,
        "parent_id": str(task.parent_id) if task.parent_id else None,
        # #428: set only while the task belongs to an import batch (an
        # ordinary delete clears it); the Recycle Bin uses it to keep a
        # batch's tasks out of its Deleted tasks list.
        "batch_id": str(task.batch_id) if task.batch_id else None,
        "project_id": str(task.project_id) if task.project_id else None,
        "goal_id": str(task.goal_id) if task.goal_id else None,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "url": task.url,
        "notes": task.notes,
        "cancellation_reason": task.cancellation_reason,
        "checklist": task.checklist or [],
        "sort_order": task.sort_order,
        "last_reviewed": (
            task.last_reviewed.isoformat() if task.last_reviewed else None
        ),
        "repeat": _serialize_repeat(task),
        "subtask_count": len(active_subtasks) + len(done_subtasks),
        "subtask_done": len(done_subtasks),
        # #433: a repeating task keeps its subtasks open when it closes
        # (#230), so the page leaves those out of its "they'll close too"
        # confirm; deleted_with_parent lets the Recycle Bin list a
        # subtask that went with its parent under that parent.
        "recurring_task_id": (
            str(task.recurring_task_id) if task.recurring_task_id else None
        ),
        "deleted_with_parent": bool(task.deleted_with_parent),
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }


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
    - Only fires for TODAY and TOMORROW. Moving back out to Inbox /
      Freezer does NOT clear the date; This Week / Backlog drop one that
      doesn't fit them (#466) and Next Week drops any (#220).
    """
    if "due_date" in data:
        return
    if task.due_date is not None:
        return
    if task.tier == Tier.TODAY:
        task.due_date = _local_today_date()
    elif task.tier == Tier.TOMORROW:
        task.due_date = _local_today_date() + timedelta(days=1)


def _redate_section_move(task: Task, data: dict) -> None:
    """#435: a write that names ``tier`` but not ``due_date`` and leaves
    an active task in TODAY / TOMORROW gives it that day's date, over
    any older one. Same rule as the board's tier buttons
    (``tierHelpers.dueDateForTier``), here so the bulk toolbar, the voice
    Shortcut, ✨ Plan and the review screens get it too. Runs even when
    the tier didn't change: "move to Today" on an overdue Today task
    means do it today. This Week / Backlog drop a date that doesn't fit
    (#466, ``_clear_unfitting_section_date``).
    """
    if "tier" not in data or "due_date" in data:
        return
    if task.status is not None and task.status != TaskStatus.ACTIVE:
        return
    if task.tier == Tier.TODAY:
        task.due_date = _local_today_date()
    elif task.tier == Tier.TOMORROW:
        task.due_date = _local_today_date() + timedelta(days=1)


# #466: the sections whose section-only move drops a date that doesn't fit.
# Next Week drops any date already (#220); Inbox and Freezer keep theirs.
_DATE_FITTED_TIERS = frozenset({Tier.THIS_WEEK, Tier.BACKLOG})


def _clear_unfitting_section_date(task: Task, data: dict, tier_before: Tier | None) -> None:
    """#466 (user decision 2026-10-16): a write that MOVES an active task to
    THIS_WEEK / BACKLOG without naming ``due_date`` drops a date that
    doesn't fit there — overdue, today, or one that files to another
    section. Kept, the 00:03 re-sort moved the task straight back out (a ✨
    Plan "Promote to This Week" of a far-dated task was in Backlog next
    morning; a due-today task moved to Backlog stayed on today's calendar
    square, then came back). A date fits when it's after today and
    ``_tier_for_due_date`` files it to that section. Same idea as #220's
    Next Week clear, and like it only on an actual move.
    """
    if "tier" not in data or "due_date" in data:
        return
    if task.tier not in _DATE_FITTED_TIERS or task.tier == tier_before:
        return
    if task.due_date is None:
        return
    if task.status is not None and task.status != TaskStatus.ACTIVE:
        return
    if task.due_date > _local_today_date() and _tier_for_due_date(task.due_date) == task.tier:
        return
    task.due_date = None


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
    """Map a due_date to its natural tier per #218 Mon-Sun ISO week boundaries.

    today               → TODAY
    tomorrow            → TOMORROW
    within this Mon-Sun → THIS_WEEK
    within next Mon-Sun → NEXT_WEEK
    anything later      → BACKLOG

    #218 (2026-05-24): switched from Mon-Sat (#72) to Mon-Sun. Under the
    old design a Sunday due_date had no week home and got orphaned to
    BACKLOG — user-reported. Mirrors the JS tier_helpers.tierForDueDate
    + app.js _tierDateRange so the board, calendar, and detail-panel
    tier preview all agree.
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
    # #218: was this_monday + 5 (Saturday). Mon-Sun ISO week ends Sun = +6.
    this_sunday = this_monday + timedelta(days=6)
    next_monday = this_monday + timedelta(days=7)
    # #218: was this_monday + 12 (next Saturday). Next Mon-Sun ends +13.
    next_sunday = this_monday + timedelta(days=13)
    if this_monday <= due_date <= this_sunday:
        return Tier.THIS_WEEK
    if next_monday <= due_date <= next_sunday:
        return Tier.NEXT_WEEK
    return Tier.BACKLOG


def _tier_for_filed_date(due_date: date) -> Tier:
    """#386: like `_tier_for_due_date`, but an overdue date files to TODAY.

    `_tier_for_due_date` maps a past date to THIS_WEEK or BACKLOG, which
    would file an overdue task out of sight. On the #386 paths (a dated
    candidate, an Inbox task getting a date) the user chose Today — the
    same "keep the nag visible" call #170 makes for the 00:03 realign.
    """
    if due_date < _local_today_date():
        return Tier.TODAY
    return _tier_for_due_date(due_date)


def tier_for_candidate(tier: Tier, due_date: date | None) -> Tier:
    """#386: the tier for a task created from a reviewed candidate
    (reflection / scan / voice / import).

    The date always wins on these paths — over the proposed or
    review-screen section, Freezer included (user decision 2026-10-05,
    docs/design/386-dated-tasks-skip-inbox.md §8); an overdue date files
    to TODAY. With no date the candidate keeps its section.
    """
    if due_date is None:
        return tier
    return _tier_for_filed_date(due_date)


def _auto_promote_tier_on_due_today(
    task: Task, data: dict, *, due_changed: bool = True
) -> None:
    """#74 (2026-04-26): when due_date changes, auto-route the tier to
    match the date's natural bucket. Always overwrites unless the
    caller is also explicit about tier, the task is FREEZER, or the
    task is non-ACTIVE.

    #386: an explicit ``tier: "inbox"`` does NOT count as explicit when
    the date changed in the same write — the task panel and every
    create default to Inbox, so the server can't tell an Inbox the user
    picked from the default. ``due_changed`` is always True on create;
    update_task passes whether the date actually moved, so a deliberate
    move of an already-dated task into Inbox is respected.

    Function name kept for backwards-compat with call sites; the body
    now covers ALL date-to-tier mappings, not just today.
    """
    if "due_date" not in data:
        return
    # Caller explicit about both: respect the combination — unless the
    # explicit tier is Inbox and the date just changed (#386).
    if "tier" in data and not (task.tier == Tier.INBOX and due_changed):
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
    # #386: an Inbox task getting an overdue date files to TODAY, not out
    # of sight in THIS_WEEK / BACKLOG. Other tiers keep the #74 mapping.
    if task.tier == Tier.INBOX:
        task.tier = _tier_for_filed_date(task.due_date)
    else:
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
        # #171 (2026-05-21): days_of_week was missing — MULTI_DAY_OF_WEEK
        # templates created via the task-detail repeat panel hit the
        # required-field check and raised 422.
        "days_of_week": repeat.get("days_of_week"),
        "day_of_month": repeat.get("day_of_month"),
        "week_of_month": repeat.get("week_of_month"),
        "project_id": str(task.project_id) if task.project_id else None,
        "goal_id": str(task.goal_id) if task.goal_id else None,
        "notes": task.notes,
        "checklist": task.checklist,
        "url": task.url,
        "subtasks_snapshot": _snapshot_subtasks(task),
        "end_date": repeat.get("end_date"),  # #101 (PR30)
        # #147 (2026-05-02): if the user provided an explicit start_date
        # in the repeat payload, use it; otherwise fall back to the task's
        # due_date so a "daily next week through Wed" task doesn't fire
        # preview cards on this Saturday. NULL preserves "fire forever
        # from the past" for templates created without a date hint.
        # #501: an explicit start_date key wins, null included ("right
        # away" -- the panel sends one only when the user filled it in).
        "start_date": (
            repeat["start_date"] if "start_date" in repeat
            else (task.due_date.isoformat() if task.due_date else None)
        ),
    }
    rt = create_recurring(rt_data)
    task.recurring_task_id = rt.id


def _update_repeat(task: Task, repeat: dict | None) -> None:
    """Update or remove the recurring template linked to a task."""
    if repeat is None:
        # Remove repeat — deactivate linked template
        if task.recurring_task_id:
            rt = db.session.get(RecurringTask, task.recurring_task_id)
            if rt is not None and not rt.is_active:
                # #353: an INACTIVE template is shown as Repeat "none"
                # (_serialize_repeat hides it), and the detail panel always
                # sends `repeat`, so null here is the form echoing what it
                # displayed, not a choice. Keep the link — otherwise saving
                # any spawned task on an archived project cuts it loose from
                # a template that unarchive will resume, and re-setting
                # Repeat later would mint a duplicate template.
                return
            if rt:
                # #363: removing the repeat ends the series. A delete, not
                # a pause, so it doesn't linger on /recurring as PAUSED.
                rt.is_active = False
                rt.deleted_at = datetime.now(UTC)
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
            # #171 (2026-05-21): days_of_week was missing here too — the
            # update path dropped it, so editing a MULTI_DAY_OF_WEEK
            # template through the task-detail panel raised 422.
            "days_of_week": repeat.get("days_of_week"),
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
        # #426: never derive start_date from the task here. This task is
        # one occurrence, and its due date may have been pushed — copying
        # it onto the template stopped every occurrence before it, and a
        # push past end_date made the save 422. Only an explicit
        # repeat.start_date changes it. (_apply_repeat still backfills
        # when a repeat is first added — #147.)
        # #501: the panel now shows the template's start date and sends it
        # back, so a present key is the user's value -- null clears it.
        # A client that doesn't send the key (an older tab) keeps it.
        if "start_date" in repeat:
            update_data["start_date"] = repeat["start_date"]
        update_recurring(task.recurring_task_id, update_data)
    else:
        _apply_repeat(task, repeat)


# --- CRUD --------------------------------------------------------------------


def resolve_project_hint(
    hint: str, task_type: str | None = None,
) -> tuple[uuid.UUID | None, str | None]:
    """Resolve a capture-bar ``@project`` hint to a project_id (#207).

    The capture parser (``parse_capture.js``) can only lift the raw
    ``@token`` out of the typed text — it has no knowledge of project
    names — so the actual name resolution happens here, server-side,
    keeping project names the single source of truth.

    Matching is **case-insensitive substring** against ACTIVE project
    names. Returns ``(project_id, warning)``:

    * exactly one match  → ``(id, None)``
    * no match           → ``(None, "<warning>")``
    * two or more        → ``(None, "<ambiguous warning>")`` — too vague
      to pick one safely, so the caller creates the task with no project

    With ``task_type`` (#475), matches of that type are counted first; a
    hint that only matches one project of the other type is a warning.

    The warning string is user-facing (surfaced by the capture bar);
    ``None`` means "nothing to tell the user".
    """
    from models import Project

    cleaned = (hint or "").strip()
    if not cleaned:
        return None, None
    needle = cleaned.lower()
    projects = list(
        db.session.scalars(select(Project).where(Project.is_active.is_(True)))
    )
    matches = [p for p in projects if needle in p.name.lower()]
    # #475: a task can only sit on a project of its own type, so a match of
    # that type wins, and a match of only the other type is reported.
    if task_type is not None:
        own = [p for p in matches if p.type.value == task_type]
        if len(own) == 1:
            return own[0].id, None
        if not own and len(matches) == 1:
            other = matches[0]
            return None, (
                f'"@{cleaned}" matches {other.name}, a {other.type.value} '
                "project — task created without a project."
            )
        if own:
            matches = own
    if len(matches) == 1:
        return matches[0].id, None
    if not matches:
        return None, (
            f'No active project matches "@{cleaned}" — '
            "task created without a project."
        )
    names = ", ".join(p.name for p in matches[:3])
    suffix = "…" if len(matches) > 3 else ""
    return None, (
        f'"@{cleaned}" matches {len(matches)} projects ({names}{suffix}) — '
        "task created without a project. Use a more specific hint."
    )


def create_task(data: dict) -> Task:
    title = _parse_text(data.get("title"), "title").strip()
    if not title:
        raise ValidationError("title is required", "title")
    _check_title(title)

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
        _refuse_closed_parent(parent)  # #493

    # #475: refuse a missing / archived / other-type link. A subtask's
    # links are its parent's, archived or not.
    check_link_changes(
        data, item_type=task_type,
        inherited_project_id=parent.project_id if parent else None,
        inherited_goal_id=parent.goal_id if parent else None,
    )

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
        notes=(_parse_text(data.get("notes"), "notes") or None),
        checklist=_parse_checklist(data.get("checklist")),
        sort_order=_parse_int(data.get("sort_order", 0), "sort_order"),
    )
    # #28: fill due_date from tier when TODAY/TOMORROW and no explicit value.
    _auto_fill_tier_due_date(task, data)
    # #46: inverse direction — promote tier to TODAY when user creates
    # a task with due_date=today in a planning tier (this_week / next_week
    # / backlog). Same hook as update_task; symmetric.
    _auto_promote_tier_on_due_today(task, data)
    repeat = _check_repeat(data.get("repeat"))
    db.session.add(task)
    db.session.flush()  # assign task.id before linking recurring template

    if repeat is not None:
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
    """List tasks. PR69 perf #2: eager-load `subtasks` and `recurring_task`
    so `tasks_api._serialize` doesn't fire 2N+1 SELECTs (one per task for
    subtasks, one per task for recurring_task) on the main board load.

    `selectinload` for the one-to-many `subtasks` collection — issues
    one extra ``WHERE parent_id IN (...)`` rather than a join cartesian.
    `joinedload` for the one-to-one `recurring_task`. Project + goal
    are NOT eager-loaded here: most callers don't need them on the
    list path; the digest, weekly-review, and detail-panel paths join
    them explicitly when they do.
    """
    stmt = (
        select(Task)
        .options(
            selectinload(Task.subtasks),
            joinedload(Task.recurring_task),
        )
    )
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
    # `unique()` required by SQLAlchemy when joinedload yields a one-to-one
    # — the Cartesian product collapses cleanly here since subtasks is
    # selectinload (separate query), but joinedload(recurring_task) on a
    # nullable FK is fine.
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


_CLOSED_STATUSES = (TaskStatus.ARCHIVED, TaskStatus.CANCELLED)


def _refuse_closing_from_bin(task: Task) -> None:
    """#474: a task in the Recycle Bin can't be completed or cancelled —
    that pulled it out of the bin (a stale tab's Done, the Shortcut's queue)
    and left the subtasks that went with it behind. Restore it first."""
    if task.status == TaskStatus.DELETED:
        raise ValidationError(
            "This task is in the Recycle Bin — restore it there first.", "status",
        )


_CLOSED_PARENT_REASONS = {
    TaskStatus.ARCHIVED: "That task is completed — re-open it first.",
    TaskStatus.CANCELLED: "That task is cancelled — re-open it first.",
    TaskStatus.DELETED: "That task is in the Recycle Bin — restore it there first.",
}


def _refuse_closed_parent(parent: Task) -> None:
    """#493: a subtask goes only under an ACTIVE parent (user decision
    2026-10-16). A deleted parent put an open subtask in the Inbox with its
    parent in the bin; a completed / cancelled one hid the subtask's parent
    and undid #433, which closes the open subtasks with the parent."""
    reason = _CLOSED_PARENT_REASONS.get(parent.status)
    if reason:
        raise ValidationError(reason, "parent_id")


def _apply_status_to_subtasks(
    task: Task, new_status: TaskStatus, close_subtasks: bool
) -> None:
    """#433: what a parent's status change does to its open subtasks.

    Called before ``task.status`` is overwritten, so ``task.status`` is
    still the old value. Mirrors ``complete_parent_task`` /
    ``cancel_parent_task`` for every other path (bulk, Goals tick box,
    reflection proposals):

    - to ARCHIVED / CANCELLED: refused while open subtasks remain, unless
      the caller sent ``close_subtasks: true`` — then they close the same
      way. A repeating-template task keeps them open (#230).
    - to DELETED: they go to the Recycle Bin with it (``_soft_delete``).
    - DELETED → ACTIVE (Restore): the ones that went with it come back.

    #480: DELETED goes through ``_soft_delete`` for a subtask too (before
    the early return below), so its ``batch_id`` is cleared and the
    Recycle Bin lists it — a bulk Delete of an imported subtask used to
    keep the batch id and vanish from the bin.
    """
    if new_status == TaskStatus.DELETED:
        _soft_delete(task)
        return
    if task.parent_id is not None:
        return
    if new_status in _CLOSED_STATUSES:
        if task.recurring_task_id is not None:
            return
        open_subs = [s for s in task.subtasks if s.status == TaskStatus.ACTIVE]
        if not open_subs:
            return
        if not close_subtasks:
            verb = "complete" if new_status == TaskStatus.ARCHIVED else "cancel"
            raise ValidationError(
                f"{len(open_subs)} open subtask(s) — {verb} them too or close "
                "them individually first",
                "subtasks",
            )
        for sub in open_subs:
            sub.status = new_status
    elif task.status == TaskStatus.DELETED and new_status == TaskStatus.ACTIVE:
        _restore_subtasks_deleted_with(task)


def update_task(task_id: uuid.UUID, data: dict) -> Task | None:
    task = get_task(task_id)
    if task is None:
        return None

    # #433: a request flag, not a column — consent to close the open
    # subtasks along with the parent (see _apply_status_to_subtasks).
    close_subtasks = data.pop("close_subtasks", False) is True

    # Snapshot pre-update values so we can cascade goal/project changes to
    # subtasks that still mirror the parent's old value (see below).
    old_goal_id = task.goal_id
    old_project_id = task.project_id
    # #386: whether this write moved the date decides if an explicit
    # tier=inbox still routes (see _auto_promote_tier_on_due_today).
    old_due_date = task.due_date
    tier_before = task.tier  # #466
    old_type = task.type

    # #475: check a new project / goal before anything is written, against
    # the type the task ends up with.
    new_type = task.type
    if "type" in data:
        new_type = _parse_enum(TaskType, data["type"], "type") or task.type
    check_link_changes(
        data, item_type=new_type,
        old_project_id=old_project_id, old_goal_id=old_goal_id,
    )

    # Weekly-planner ignore flag is "stop suggesting until I touch the
    # task again". Any meaningful field change resets it so the next
    # planner run reconsiders the task. The PATCH from the planner
    # itself uses planner_ignore=True explicitly (see ignore endpoint),
    # so when the user clicks "Ignore" we honor it; everything else
    # (tier change, project link, retitle, …) means the user engaged
    # with the task and the silence is no longer wanted.
    _meaningful_change_fields = {
        "title", "type", "tier", "status", "project_id", "goal_id",
        "due_date", "url", "notes", "checklist", "cancellation_reason",
        "parent_id",
    }
    if task.planner_ignore and any(k in data for k in _meaningful_change_fields):
        task.planner_ignore = False

    if "title" in data:
        title = _parse_text(data["title"], "title").strip()
        if not title:
            raise ValidationError("title cannot be empty", "title")
        task.title = _check_title(title)

    if "type" in data:
        task.type = _parse_enum(TaskType, data["type"], "type") or task.type

    if "tier" in data:
        old_tier = task.tier
        task.tier = _parse_enum(Tier, data["tier"], "tier") or task.tier
        # #220 (2026-05-24): when the user EXPLICITLY punts a task to
        # NEXT_WEEK from a different tier, clear any stale due_date.
        # The user-reported scenario: tier=TODAY, due_date=today;
        # user clicks "Next Week" expecting the task to move OFF the
        # today cell on /calendar. Tier-only mutation kept due_date
        # untouched, so the calendar still showed the task on its
        # original day — the "immediate reflection is not working"
        # complaint. Clearing the date lands the task in the
        # Unscheduled aside; user can drag to a specific next-week
        # day if they want. Skipped when:
        #   - tier didn't actually change (e.g. PATCH from the same
        #     panel that just re-saves the existing tier)
        #   - user explicitly set due_date in the same payload
        #     (intentional "schedule for X next week")
        #   - task had no due_date to begin with (no-op)
        # Mirrors the spirit of _auto_fill_tier_due_date — that hook
        # auto-FILLS for TODAY/TOMORROW; this one auto-CLEARS for
        # NEXT_WEEK. THIS_WEEK / BACKLOG drop only a date that doesn't
        # fit them (#466, _clear_unfitting_section_date); INBOX keeps it.
        if (
            task.tier != old_tier
            and task.tier == Tier.NEXT_WEEK
            and "due_date" not in data
            and task.due_date is not None
        ):
            task.due_date = None

    if "status" in data:
        new_status = _parse_enum(TaskStatus, data["status"], "status") or task.status
        old_status = task.status
        if new_status in _CLOSED_STATUSES:
            _refuse_closing_from_bin(task)
        # When transitioning out of CANCELLED, clear the reason so a stale
        # explanation doesn't outlive the cancellation. Caller can still
        # set it explicitly in the same PATCH if they want to preserve it.
        if (
            task.status == TaskStatus.CANCELLED
            and new_status != TaskStatus.CANCELLED
            and "cancellation_reason" not in data
        ):
            task.cancellation_reason = None
        if new_status != old_status:
            _apply_status_to_subtasks(task, new_status, close_subtasks)
        task.status = new_status
        if old_status == TaskStatus.DELETED and new_status != TaskStatus.DELETED:
            task.deleted_with_parent = False

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
            # #493: only a NEW parent must be open. The panel re-sends the
            # parent on every Save, and a repeating task's subtasks stay
            # open when it closes — those must keep saving.
            if new_parent_id != task.parent_id:
                _refuse_closed_parent(parent)
        task.parent_id = new_parent_id

    if "project_id" in data:
        task.project_id = _parse_uuid(data["project_id"], "project_id")
        # #77 (2026-04-26) + PR24 audit refinement (BUG-2):
        #   - Assigning a project WITH a goal → cascade the goal onto
        #     the task (always overwrite — feature, not bug).
        #   - Assigning a project WITHOUT a goal, or clearing the project
        #     (project_id → None) → drop the goal only if it CAME from the
        #     old project (#427, #461). A goal set by hand stays (the
        #     PR24 audit's silent-data-loss finding); the old project's
        #     goal doesn't linger under a project it doesn't belong to —
        #     the task panel's rule since 2026-05-04
        #     (filter_helpers.goalAfterProjectChange), now the server's
        #     too, so a drag or a bulk edit agrees with the panel.
        # If the caller ALSO sets goal_id explicitly in this same
        # payload, that wins via the next branch which writes after.
        from models import Project
        proj = db.session.get(Project, task.project_id) if task.project_id is not None else None
        if proj is not None and proj.goal_id is not None:
            task.goal_id = proj.goal_id
        elif old_project_id is not None and old_project_id != task.project_id:
            old_proj = db.session.get(Project, old_project_id)
            if (
                old_proj is not None
                and old_proj.goal_id is not None
                and task.goal_id == old_proj.goal_id
            ):
                task.goal_id = None

    if "goal_id" in data:
        task.goal_id = _parse_uuid(data["goal_id"], "goal_id")

    # #475: a type change takes the task off a project of the other type.
    # Before the repeat sync below, so the template follows.
    unlink_other_type_project(task, old_type=old_type, data=data, old_goal_id=old_goal_id)

    if "due_date" in data:
        task.due_date = _parse_date(data["due_date"], "due_date")

    if "last_reviewed" in data:
        task.last_reviewed = _parse_date(data["last_reviewed"], "last_reviewed")

    if "url" in data:
        task.url = _parse_url(data["url"])

    if "notes" in data:
        task.notes = _parse_text(data["notes"], "notes") or None

    if "cancellation_reason" in data:
        # Empty string normalizes to None so the field clears cleanly when
        # the user un-cancels a task (status → active) and re-cancels later.
        reason = _parse_text(data["cancellation_reason"], "cancellation_reason").strip()
        task.cancellation_reason = _check_reason(reason or None)

    if "checklist" in data:
        task.checklist = _parse_checklist(data["checklist"])

    if "sort_order" in data:
        task.sort_order = _parse_int(data["sort_order"], "sort_order")

    if "repeat" in data:
        _update_repeat(task, _check_repeat(data["repeat"]))

    # #28: after all explicit updates, if the tier is TODAY/TOMORROW
    # and due_date ended up null (and wasn't explicitly set in this
    # payload), fill it from the tier. Runs on every update — catches
    # drag-to-today, bulk tier change, capture-bar #today with no
    # explicit date, etc. #435: a tier-only move there replaces an older
    # date first.
    _clear_unfitting_section_date(task, data, tier_before)  # #466
    _redate_section_move(task, data)
    _auto_fill_tier_due_date(task, data)

    # #46: inverse direction — if the user just set due_date to today
    # AND the tier is in {THIS_WEEK, NEXT_WEEK, BACKLOG} (and they
    # didn't also explicitly set tier), promote tier to TODAY. The
    # mid-day complement to the 00:02 promote_due_today_tasks cron.
    _auto_promote_tier_on_due_today(
        task, data, due_changed=task.due_date != old_due_date
    )

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
        # #461: a goal that changed because the project did (assigned a
        # project with a goal, or dropped an inherited one) cascades too —
        # this used to need "goal_id" in the payload. A goal changed by a
        # type change (#475's unlink) doesn't: the subtasks keep theirs.
        goal_changed = (
            ("goal_id" in data or "project_id" in data) and task.goal_id != old_goal_id
        )
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
    or raise a ValidationError so the UI can prompt the user.

    #230 (2026-05-25): RECURRING-spawn tasks (task.recurring_task_id is not
    None) SKIP the cascade-or-prompt logic entirely: the parent archives,
    open subtasks stay ACTIVE. User-requested behavior — subtasks of a
    recurring task ("hand off X, follow up with Y" under a "Weekly Work
    Prep") are often independent work that should survive the parent's
    weekly close-out. Mirror change in `cancel_parent_task` below.
    """
    task = get_task(task_id)
    if task is None:
        return None
    _refuse_closing_from_bin(task)
    open_subtasks = list_subtasks(task_id)
    # #230: recurring-spawn → silently leave subtasks open.
    if task.recurring_task_id is not None:
        task.status = TaskStatus.ARCHIVED
        db.session.commit()
        return task
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


def cancel_parent_task(
    task_id: uuid.UUID,
    *,
    cancel_subtasks: bool = False,
    reason: str | None = None,
) -> Task | None:
    """Cancel a parent task, cascading to its open subtasks.

    #176 (2026-05-21): the cancel path used to be a plain
    ``PATCH {status: "cancelled"}`` through ``update_task`` — which set
    the parent's status but left open subtasks ACTIVE under a cancelled
    parent (orphaned, still showing the now-dead parent-link badge).
    The complete path already had ``complete_parent_task``; this is the
    missing mirror for cancel.

    Mirrors ``complete_parent_task``: if the parent has open subtasks
    and ``cancel_subtasks`` is False, raise a ValidationError so the UI
    can prompt. When ``cancel_subtasks`` is True, the open subtasks are
    set to CANCELLED alongside the parent. ``reason`` is stored on the
    parent's ``cancellation_reason``; subtasks inherit the CANCELLED
    status only (no per-subtask reason — they were collateral).
    """
    # #447: refuse an over-long reason before anything changes.
    reason = _check_reason((reason or "").strip() or None)
    task = get_task(task_id)
    if task is None:
        return None
    _refuse_closing_from_bin(task)
    open_subtasks = list_subtasks(task_id)
    # #230 (2026-05-25): recurring-spawn → silently leave subtasks open
    # (mirror of the complete_parent_task hook above). User intent: when
    # I cancel "Weekly Work Prep", the prep-subtasks may still be valid
    # work to follow through on. Don't bulk-cancel them.
    if task.recurring_task_id is not None:
        task.status = TaskStatus.CANCELLED
        task.cancellation_reason = reason
        db.session.commit()
        return task
    if open_subtasks and not cancel_subtasks:
        raise ValidationError(
            f"{len(open_subtasks)} open subtask(s) — cancel all or close individually first",
            "subtasks",
        )
    if cancel_subtasks:
        for sub in open_subtasks:
            sub.status = TaskStatus.CANCELLED
    task.status = TaskStatus.CANCELLED
    task.cancellation_reason = reason
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
    _soft_delete(task)
    db.session.commit()
    return True


def _soft_delete(task: Task) -> int:
    """Set ``task`` DELETED and take its open subtasks along (#433). No commit.

    Each ACTIVE subtask goes to the Recycle Bin too, marked
    ``deleted_with_parent`` so restoring the parent brings back exactly
    those (``_restore_subtasks_deleted_with``); done / cancelled subtasks
    are left as they are. ``batch_id`` is cleared on all of them — see
    ``delete_task``. Returns how many subtasks went along.
    """
    task.status = TaskStatus.DELETED
    task.batch_id = None
    task.deleted_with_parent = False
    taken = 0
    if task.parent_id is None:
        for sub in task.subtasks:
            if sub.status != TaskStatus.ACTIVE:
                continue
            sub.status = TaskStatus.DELETED
            sub.batch_id = None
            sub.deleted_with_parent = True
            taken += 1
    return taken


def _restore_subtasks_deleted_with(task: Task) -> None:
    """#433: the Recycle Bin's Restore of a parent brings back the subtasks
    that went to the bin with it — not one deleted on its own."""
    for sub in task.subtasks:
        if sub.status == TaskStatus.DELETED and sub.deleted_with_parent:
            sub.status = TaskStatus.ACTIVE
            sub.deleted_with_parent = False


def duplicate_task(task_id: uuid.UUID) -> Task | None:
    """#143 (2026-05-04): clone a task to TOMORROW so the user can keep
    working on it the next day without retyping title / project / goal /
    notes / checklist.

    What carries over:
      title · type · project_id · goal_id · url · notes · checklist
      (every checklist item gets ``checked=False`` since the duplicate
      represents a fresh attempt, not the in-progress state of the
      original)

    What's reset / fresh on the new task:
      tier         → TOMORROW
      due_date     → tomorrow's date (DIGEST_TZ-local, matches
                      _local_today_date semantics)
      status       → ACTIVE
      parent_id    → None (duplicates are standalone — subtasks usually
                      describe the parent's specific concrete steps,
                      not a copy-pasted plan)
      recurring_task_id → None (don't accidentally link to a template)
      batch_id     → None (not a bulk-import row)
      sort_order   → 0
      last_reviewed → None
      created_at / updated_at → fresh

    Subtasks are NOT cascaded in v1 — see #143 for the rationale.

    Returns the new Task, or None if the source doesn't exist or has
    been deleted.
    """
    src = get_task(task_id)
    if src is None or src.status == TaskStatus.DELETED:
        return None

    from utils import local_today_date
    tomorrow = local_today_date() + timedelta(days=1)

    # Reset all checklist items so the duplicate represents a fresh start.
    new_checklist: list[dict] = []
    if isinstance(src.checklist, list):
        for item in src.checklist:
            if isinstance(item, dict):
                new_checklist.append({
                    "id": item.get("id", ""),
                    "text": item.get("text", ""),
                    "checked": False,
                })

    new_task = Task(
        title=src.title,
        type=src.type,
        tier=Tier.TOMORROW,
        due_date=tomorrow,
        project_id=src.project_id,
        goal_id=src.goal_id,
        url=src.url,
        notes=src.notes,
        checklist=new_checklist,
        status=TaskStatus.ACTIVE,
        # Explicitly NOT copied: parent_id / recurring_task_id / batch_id
        # / sort_order / last_reviewed / cancellation_reason / planner_ignore
    )
    db.session.add(new_task)
    db.session.commit()
    return new_task


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

    PR70 perf #8: previously each call to ``update_task`` ran its own
    ``db.session.commit()`` — 200 task ids = 200 fsync round-trips to
    Postgres (~2-5 seconds on Railway). Now wrapped in nested
    SAVEPOINTs so partial failures still roll back per-task without
    affecting the rest, but the OUTER transaction commits ONCE at the
    end. Same per-task error reporting + same partial-progress
    semantics as before, just one fsync instead of N.

    Why not run inside a single transaction with rollback-on-any-error:
    a typo in `updates` would invalidate the entire batch with no UI
    way to know which task triggered it. Per-task SAVEPOINT gives
    the user a precise error report and keeps the partial progress.
    """
    updated = 0
    not_found: list[str] = []
    errors: list[dict] = []
    for tid in task_ids:
        # Per-task SAVEPOINT so a failure on one row doesn't poison
        # the outer transaction. ``update_task`` calls ``db.session.commit()``
        # on success — that "commit" actually closes the savepoint
        # because we're inside a begin_nested block; the outer txn is
        # still open. SQLAlchemy 2.x calls this RELEASE SAVEPOINT semantics.
        try:
            with db.session.begin_nested():
                task = update_task(tid, dict(updates))
        except ValidationError as e:
            errors.append({"id": str(tid), "field": e.field, "message": str(e)})
            continue
        if task is None:
            not_found.append(str(tid))
            continue
        updated += 1
    # Single fsync at the end. If everything failed, this is a no-op.
    db.session.commit()
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


def backfill_clear_stale_next_week_due_dates() -> int:
    """#220 follow-up (2026-05-24): one-shot cleanup for tasks that
    were punted to NEXT_WEEK via the tier button BEFORE the #220 hook
    shipped — they still carry their old today/past `due_date` because
    the pre-fix code path didn't clear it. Same data shape my #220
    hook prevents for future punts.

    Selects tasks where:
      - tier == NEXT_WEEK
      - due_date <= today
      - status == ACTIVE

    …and sets due_date = None on each one. Idempotent — re-running
    after the data is clean is a no-op.

    Different invariant than `realign_tiers_with_due_dates`:
      - realign treats due_date as authoritative and re-computes tier.
        Running that on these stuck tasks would move them OFF
        NEXT_WEEK (back to today/this_week) — opposite of what the
        user intended when they clicked "Next Week" in the first place.
      - This function treats the user's explicit tier choice as
        authoritative and CLEARS the stale date so the calendar view
        agrees. Matches the #220 hook's semantics.

    Returns the number of rows updated.
    """
    from sqlalchemy.orm import Session

    today = _local_today_date()
    updated = 0
    with Session(db.engine) as session:
        rows = session.scalars(
            select(Task).where(
                Task.tier == Tier.NEXT_WEEK,
                Task.due_date.is_not(None),
                Task.due_date <= today,
                Task.status == TaskStatus.ACTIVE,
            )
        ).all()
        for t in rows:
            t.due_date = None
            updated += 1
        if updated:
            session.commit()
        return updated


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
    - TODAY with a past due_date (#170): a task the user left in the
      Today panel as an unfinished-yesterday nag. `_tier_for_due_date`
      maps a past date to THIS_WEEK or BACKLOG, so without this guard
      the 00:03 cron silently demotes "I didn't finish this" tasks off
      the Today panel overnight with no notification. Inverse of the
      drift #108 fixes — that one corrects tasks that drifted OUT of
      alignment; this one preserves a deliberate placement. The task
      stays in Today until the user acts on it.

    #438 (user decisions 2026-10-12, docs/design/438-week-rollover.md):
    - A THIS_WEEK / NEXT_WEEK task whose date has passed goes to TODAY,
      not BACKLOG — overdue stays in sight, as #170 / #386 already do.
    - Once per ISO week, undated NEXT_WEEK tasks move to THIS_WEEK: the
      week they were parked for has arrived. Keyed on the week rather
      than "is it Monday" so a missed Monday run that is replayed later
      still rolls. The first run ever only records the week.

    Returns the number of rows updated. Idempotent — re-running
    when nothing has drifted is a no-op.
    """
    from sqlalchemy.orm import Session

    skip_tiers = _FROZEN_TIERS | {Tier.INBOX}
    week_tiers = {Tier.THIS_WEEK, Tier.NEXT_WEEK}
    today = _local_today_date()
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
            # #170: keep an overdue task that the user parked in TODAY
            # visible in the Today panel as a nag — don't let the cron
            # quietly demote it to BACKLOG / THIS_WEEK overnight.
            if t.tier == Tier.TODAY and t.due_date < today:
                continue
            # #438: a week task whose day has passed comes to Today —
            # it used to fall to Backlog on Monday, carrying its overdue
            # date out of sight.
            if t.tier in week_tiers and t.due_date < today:
                new_tier = Tier.TODAY
            else:
                # Compute the "right" tier for this due_date as of today.
                new_tier = _tier_for_due_date(t.due_date)
            if new_tier != t.tier:
                t.tier = new_tier
                updated += 1
        updated += _roll_undated_next_week(session, today)
        session.commit()
        return updated


# #438: the ISO week the undated-Next-Week roll last ran for.
WEEK_ROLL_KEY = "week_roll_last_iso_week"


def _roll_undated_next_week(session, today: date) -> int:
    """#438: move undated NEXT_WEEK tasks to THIS_WEEK once per ISO week.

    The first run (no marker yet) only records the current week: what is
    in Next Week right now was put there meaning the coming week.
    Leaves committing to the caller.
    """
    from models import AppSetting

    iso = today.isocalendar()
    week = f"{iso.year}-W{iso.week:02d}"
    marker = session.scalars(
        select(AppSetting).where(AppSetting.key == WEEK_ROLL_KEY)
    ).first()
    if marker is None:
        session.add(AppSetting(key=WEEK_ROLL_KEY, value=week))
        return 0
    if marker.value == week:
        return 0
    rows = session.scalars(
        select(Task).where(
            Task.tier == Tier.NEXT_WEEK,
            Task.due_date.is_(None),
            Task.status == TaskStatus.ACTIVE,
        )
    ).all()
    for t in rows:
        t.tier = Tier.THIS_WEEK
    marker.value = week
    return len(rows)


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

