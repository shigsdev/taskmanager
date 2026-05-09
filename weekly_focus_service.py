"""Weekly Focus service — read/upsert + AI plan-for-focus.

Feature 1 (user-requested 2026-05-08, shipped 2026-05-09): a panel at
the top of the main board with N (configurable, default 3) free-form
focus statements for the current ISO week. Each slot can optionally
link to a Goal. The panel persists per ISO-week — silent history
snapshots when the user edits — but does NOT auto-roll on Monday;
last week's text stays visible until the user touches it.

The "✨ Plan" button next to each slot kicks off a one-shot Claude
Haiku call that proposes which existing tasks to promote/demote and
what new tasks to create to make the focus statement realistic. The
client renders a review modal (same shape as Auto-categorize Inbox)
where the user accepts per row before anything is applied.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from models import (
    AppSetting,
    Goal,
    GoalStatus,
    Project,
    Task,
    TaskStatus,
    TaskType,
    Tier,
    WeeklyFocus,
    db,
)
from utils import local_today_date

log = logging.getLogger(__name__)

# Slot count bounds. Default 3 per user research consensus
# (3 keystone outcomes per week beats 5+). Cap at 7 to keep the panel
# from getting unwieldy.
SLOT_COUNT_KEY = "weekly_focus_slot_count"
DEFAULT_SLOT_COUNT = 3
MIN_SLOT_COUNT = 1
MAX_SLOT_COUNT = 7

# Plan-for-focus output validation
_VALID_TIERS_FOR_PLAN: set[str] = {
    Tier.TODAY.value, Tier.TOMORROW.value, Tier.THIS_WEEK.value,
    Tier.NEXT_WEEK.value, Tier.BACKLOG.value, Tier.FREEZER.value,
}
_VALID_TYPES: set[str] = {TaskType.WORK.value, TaskType.PERSONAL.value}


def monday_of(d: date) -> date:
    """Return the Monday of the ISO week containing ``d``."""
    return d - timedelta(days=d.weekday())


# --- Settings: slot count ----------------------------------------------------


def get_slot_count() -> int:
    """Read the current slot count from ``app_settings``.

    Returns ``DEFAULT_SLOT_COUNT`` (3) if no setting exists or the
    stored value is malformed / out of range. Never raises — the panel
    must always have a valid slot count to render.
    """
    row = db.session.scalar(
        select(AppSetting).where(AppSetting.key == SLOT_COUNT_KEY)
    )
    if not row:
        return DEFAULT_SLOT_COUNT
    try:
        n = int(row.value)
    except (TypeError, ValueError):
        return DEFAULT_SLOT_COUNT
    if n < MIN_SLOT_COUNT or n > MAX_SLOT_COUNT:
        return DEFAULT_SLOT_COUNT
    return n


def set_slot_count(n: int) -> int:
    """Persist a new slot count. Clamps to [1, 7]."""
    if not isinstance(n, int):
        raise ValueError("slot count must be an int")
    n = max(MIN_SLOT_COUNT, min(MAX_SLOT_COUNT, n))
    row = db.session.scalar(
        select(AppSetting).where(AppSetting.key == SLOT_COUNT_KEY)
    )
    if row is None:
        row = AppSetting(key=SLOT_COUNT_KEY, value=str(n))
        db.session.add(row)
    else:
        row.value = str(n)
    db.session.commit()
    return n


# --- Read: what to display ---------------------------------------------------


def get_displayed_focus(today: date | None = None) -> dict:
    """Return the focus rows the panel should show today, plus the
    slot count.

    Strategy (matches user-confirmed spec 2026-05-09):
      1. If rows exist for ``monday_of(today)``, return those.
      2. Otherwise fall back to the most recent past week's rows
         (carry-forward — last week's text remains visible until the
         user edits).
      3. If no rows exist at all, return empty list — first-run state.

    Soft-deleted rows (``is_active=False``) are excluded.

    Returns:
        ``{"slot_count": int, "week_start_date": ISO, "fallback_from":
        ISO|None, "slots": [{slot_order, text, goal_id, goal_title}]}``
        — ``fallback_from`` is the previous week's ISO if we're
        carrying forward, else None (panel can show "Edit to update").
    """
    today = today or local_today_date()
    current_week = monday_of(today)

    rows = list(db.session.scalars(
        select(WeeklyFocus)
        .where(WeeklyFocus.week_start_date == current_week)
        .where(WeeklyFocus.is_active.is_(True))
        .order_by(WeeklyFocus.slot_order)
    ))
    fallback_from: date | None = None
    if not rows:
        # Most recent past week.
        most_recent = db.session.scalar(
            select(WeeklyFocus.week_start_date)
            .where(WeeklyFocus.week_start_date < current_week)
            .where(WeeklyFocus.is_active.is_(True))
            .order_by(WeeklyFocus.week_start_date.desc())
            .limit(1)
        )
        if most_recent:
            rows = list(db.session.scalars(
                select(WeeklyFocus)
                .where(WeeklyFocus.week_start_date == most_recent)
                .where(WeeklyFocus.is_active.is_(True))
                .order_by(WeeklyFocus.slot_order)
            ))
            fallback_from = most_recent

    # Resolve goal titles in one query rather than N+1.
    goal_ids = [r.goal_id for r in rows if r.goal_id]
    goal_titles: dict[uuid.UUID, str] = {}
    if goal_ids:
        goals = list(db.session.scalars(
            select(Goal).where(Goal.id.in_(goal_ids))
        ))
        goal_titles = {g.id: g.title for g in goals}

    return {
        "slot_count": get_slot_count(),
        "week_start_date": current_week.isoformat(),
        "fallback_from": fallback_from.isoformat() if fallback_from else None,
        "slots": [
            {
                "slot_order": r.slot_order,
                "text": r.text,
                "goal_id": str(r.goal_id) if r.goal_id else None,
                "goal_title": goal_titles.get(r.goal_id) if r.goal_id else None,
            }
            for r in rows
        ],
    }


# --- Write: upsert / clear ---------------------------------------------------


def upsert_slot(
    slot_order: int,
    text: str,
    goal_id: uuid.UUID | None = None,
    today: date | None = None,
) -> WeeklyFocus:
    """Set the text + optional goal link for ``slot_order`` of THIS week.

    If a row already exists for ``(this_week, slot_order)``, update it.
    Otherwise create a new row. Past-week rows are NEVER touched —
    history is preserved by always writing to the current week's row.

    Validation:
      - slot_order must be in [1, get_slot_count()]
      - text must be non-empty after strip()
      - goal_id, if given, must exist in goals table
    """
    today = today or local_today_date()
    current_week = monday_of(today)

    slot_count = get_slot_count()
    if not isinstance(slot_order, int) or slot_order < 1 or slot_order > slot_count:
        raise ValueError(
            f"slot_order must be 1..{slot_count} (got {slot_order})"
        )
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text required")
    text = text.strip()
    if len(text) > 500:
        text = text[:500]

    if goal_id is not None:
        if not isinstance(goal_id, uuid.UUID):
            try:
                goal_id = uuid.UUID(str(goal_id))
            except (TypeError, ValueError) as e:
                raise ValueError(f"goal_id is not a valid UUID: {goal_id}") from e
        # Verify the goal exists.
        if db.session.get(Goal, goal_id) is None:
            raise ValueError(f"goal_id {goal_id} not found")

    row = db.session.scalar(
        select(WeeklyFocus)
        .where(WeeklyFocus.week_start_date == current_week)
        .where(WeeklyFocus.slot_order == slot_order)
    )
    if row is None:
        row = WeeklyFocus(
            week_start_date=current_week,
            slot_order=slot_order,
            text=text,
            goal_id=goal_id,
            is_active=True,
        )
        db.session.add(row)
    else:
        row.text = text
        row.goal_id = goal_id
        row.is_active = True
    db.session.commit()
    return row


def clear_slot(slot_order: int, today: date | None = None) -> bool:
    """Soft-delete the row for ``(this_week, slot_order)``.

    Returns True if a row was cleared, False if no row existed (no-op).
    Past weeks' rows are never touched — only the current week's slot
    can be cleared via this path.
    """
    today = today or local_today_date()
    current_week = monday_of(today)
    row = db.session.scalar(
        select(WeeklyFocus)
        .where(WeeklyFocus.week_start_date == current_week)
        .where(WeeklyFocus.slot_order == slot_order)
        .where(WeeklyFocus.is_active.is_(True))
    )
    if row is None:
        return False
    row.is_active = False
    db.session.commit()
    return True


# --- AI: plan tasks for a focus statement -----------------------------------


# Cap input to bound cost + Claude input size. Active set > 100 means
# we skip the largest non-recent tasks; the rare 200+ active power user
# can still get useful suggestions on the front cohort.
MAX_TASKS_FOR_PLAN = 100


_PROMPT_TEMPLATE = """You are a personal productivity coach. The user has a focus
statement for this week and wants you to propose changes to their task list
to make that focus realistic. Be opinionated but conservative — only suggest
changes you can defend in one short sentence.

Today's date is {today_iso} ({today_weekday}). The focus week is
{week_start_iso} through {week_end_iso}.

THIS WEEK'S FOCUS STATEMENT:
"{focus_text}"
{linked_goal_block}
CONTEXT — currently-tracked projects and goals:

Projects:
{projects_block}

Goals:
{goals_block}

ACTIVE TASKS (id, title, current_tier, type, project, goal):
{tasks_block}

Choose changes that move tasks toward the focus. For each, pick exactly one of:

  promote_today      — task should be done TODAY to make the focus
  promote_this_week  — task should land in THIS_WEEK
  demote_backlog     — task is NOT relevant to the focus and should drop to
                       BACKLOG to clear the cognitive load (only use this for
                       tasks currently in TODAY/TOMORROW/THIS_WEEK that are
                       genuinely off-focus — be conservative)
  create_new         — propose a NEW task that needs to exist for the focus
                       to be realistic. Provide title (≤ 80 chars),
                       suggested_tier (today/tomorrow/this_week), type
                       (work/personal), and an optional ISO due_date.

Keep the total list to AT MOST 8 changes — prefer high-signal moves over
exhaustive coverage. If the focus is already well-supported by the existing
tier placement, return fewer (or zero) changes.

Respond with ONLY a JSON object — no markdown fences, no prose:

{{
  "changes": [
    {{"action": "promote_today",     "task_id": "...", "reason": "..."}},
    {{"action": "promote_this_week", "task_id": "...", "reason": "..."}},
    {{"action": "demote_backlog",    "task_id": "...", "reason": "..."}},
    {{"action": "create_new", "title": "...", "suggested_tier": "today",
      "type": "work", "due_date": null, "reason": "..."}}
  ]
}}

reason ≤ 80 chars per row. NEVER invent task IDs — only IDs from the ACTIVE
TASKS list above are valid.
"""


def _format_projects_block(projects: list[dict]) -> str:
    if not projects:
        return "(none)"
    return "\n".join(
        f"  - id={p['id']}: {p['name']} (type={p['type']})"
        for p in projects
    )


def _format_goals_block(goals: list[dict]) -> str:
    if not goals:
        return "(none)"
    return "\n".join(
        f"  - id={g['id']}: {g['title']} (category={g['category']})"
        for g in goals
    )


def _format_tasks_block(tasks: list[Task]) -> str:
    if not tasks:
        return "(none)"
    lines = []
    for t in tasks:
        proj_part = f", project={t.project_id}" if t.project_id else ""
        goal_part = f", goal={t.goal_id}" if t.goal_id else ""
        lines.append(
            f"  - id={t.id}: {t.title} "
            f"(tier={t.tier.value}, type={t.type.value}{proj_part}{goal_part})"
        )
    return "\n".join(lines)


def _load_plan_context() -> tuple[list[Task], list[dict], list[dict]]:
    """Active task set (capped) + active project + active goal lists."""
    task_stmt = (
        select(Task)
        .where(Task.status == TaskStatus.ACTIVE)
        .where(Task.parent_id.is_(None))  # parents only — subtasks ride along
        .order_by(Task.created_at.desc())
        .limit(MAX_TASKS_FOR_PLAN)
    )
    tasks = list(db.session.scalars(task_stmt))

    proj_stmt = select(Project).where(Project.is_active.is_(True))
    projects = [
        {"id": str(p.id), "name": p.name, "type": p.type.value}
        for p in db.session.scalars(proj_stmt)
    ]
    goal_stmt = select(Goal).where(Goal.status != GoalStatus.DONE)
    goals = [
        {"id": str(g.id), "title": g.title, "category": g.category.value}
        for g in db.session.scalars(goal_stmt)
    ]
    return tasks, projects, goals


def _build_plan_prompt(
    focus_text: str, linked_goal: Goal | None,
    tasks: list[Task], projects: list[dict], goals: list[dict],
) -> str:
    today = local_today_date()
    week_start = monday_of(today)
    week_end = week_start + timedelta(days=6)
    linked = ""
    if linked_goal is not None:
        linked = (
            f"\nLINKED GOAL (the focus is in service of this goal):\n"
            f"  - {linked_goal.title} "
            f"(category={linked_goal.category.value}, "
            f"status={linked_goal.status.value})\n"
        )
    return _PROMPT_TEMPLATE.format(
        today_iso=today.isoformat(),
        today_weekday=today.strftime("%A"),
        week_start_iso=week_start.isoformat(),
        week_end_iso=week_end.isoformat(),
        focus_text=focus_text.replace('"', '\\"'),
        linked_goal_block=linked,
        projects_block=_format_projects_block(projects),
        goals_block=_format_goals_block(goals),
        tasks_block=_format_tasks_block(tasks),
    )


def _post_to_claude(api_key: str, prompt: str, max_tokens: int) -> dict[str, Any]:
    from egress import EgressError, safe_call_api

    try:
        return safe_call_api(
            url="https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout_sec=60,
            vendor="Claude",
        )
    except EgressError as e:
        raise RuntimeError(str(e)) from e


def _parse_claude_response(raw_text: str) -> list[dict]:
    """Extract the changes array from Claude's response, tolerant of
    markdown fences. Returns the validated array (caller does ID/shape
    validation in ``_validate_change``)."""
    text = raw_text.strip()
    obj: dict | None = None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # Fence-stripping fallback.
        if "```" in text:
            for part in text.split("```"):
                cleaned = part.strip()
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:].strip()
                try:
                    obj = json.loads(cleaned)
                    break
                except json.JSONDecodeError:
                    continue
    if not isinstance(obj, dict):
        raise ValueError("Claude response was not a JSON object")
    changes = obj.get("changes")
    if not isinstance(changes, list):
        raise ValueError("Claude response did not contain a changes array")
    return changes


def _validate_change(
    raw: dict,
    *,
    valid_task_ids: set[str],
    title_lookup: dict[str, str],
) -> dict | None:
    """Coerce + sanity-check one change row from Claude. Drops bad shapes."""
    if not isinstance(raw, dict):
        return None
    action = raw.get("action")
    reason = raw.get("reason") or ""
    if not isinstance(reason, str):
        reason = ""
    reason = reason.strip()[:120]

    if action in ("promote_today", "promote_this_week", "demote_backlog"):
        task_id = raw.get("task_id")
        if not isinstance(task_id, str) or task_id not in valid_task_ids:
            return None
        return {
            "action": action,
            "task_id": task_id,
            "title": title_lookup[task_id],
            "reason": reason,
        }
    if action == "create_new":
        title = raw.get("title")
        if not isinstance(title, str) or not title.strip():
            return None
        title = title.strip()[:200]
        tier = raw.get("suggested_tier")
        if tier not in _VALID_TIERS_FOR_PLAN or tier == Tier.FREEZER.value:
            tier = Tier.THIS_WEEK.value
        type_ = raw.get("type")
        if type_ not in _VALID_TYPES:
            type_ = TaskType.WORK.value
        due = raw.get("due_date")
        if due is not None and (not isinstance(due, str) or len(due) != 10):
            due = None
        if isinstance(due, str):
            try:
                from datetime import date as _date
                _date.fromisoformat(due)
            except (TypeError, ValueError):
                due = None
        return {
            "action": "create_new",
            "title": title,
            "suggested_tier": tier,
            "type": type_,
            "due_date": due,
            "reason": reason,
        }
    return None


def plan_for_focus(slot_order: int, today: date | None = None) -> dict:
    """Run the AI plan for the slot's current focus statement.

    Returns ``{"focus": str, "linked_goal": str|None, "changes": [...]}``.
    Caller is the API layer; raises RuntimeError when the API key is
    missing or Claude fails. Never mutates the database — the client
    review modal does that on Apply via the existing PATCH/POST
    endpoints.
    """
    today = today or local_today_date()
    current_week = monday_of(today)
    # Find the slot's row — fall back to most recent past week if
    # current week has nothing (matches get_displayed_focus behavior).
    row = db.session.scalar(
        select(WeeklyFocus)
        .where(WeeklyFocus.week_start_date == current_week)
        .where(WeeklyFocus.slot_order == slot_order)
        .where(WeeklyFocus.is_active.is_(True))
    )
    if row is None:
        most_recent = db.session.scalar(
            select(WeeklyFocus.week_start_date)
            .where(WeeklyFocus.week_start_date < current_week)
            .where(WeeklyFocus.is_active.is_(True))
            .order_by(WeeklyFocus.week_start_date.desc())
            .limit(1)
        )
        if most_recent:
            row = db.session.scalar(
                select(WeeklyFocus)
                .where(WeeklyFocus.week_start_date == most_recent)
                .where(WeeklyFocus.slot_order == slot_order)
                .where(WeeklyFocus.is_active.is_(True))
            )
    if row is None:
        raise ValueError(f"no active focus slot {slot_order}")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    tasks, projects, goals = _load_plan_context()
    linked_goal = (
        db.session.get(Goal, row.goal_id) if row.goal_id else None
    )
    prompt = _build_plan_prompt(row.text, linked_goal, tasks, projects, goals)

    response = _post_to_claude(api_key, prompt, max_tokens=4000)
    raw_text = response.get("content", [{}])[0].get("text", "")
    raw_changes = _parse_claude_response(raw_text)

    title_lookup = {str(t.id): t.title for t in tasks}
    valid_task_ids = set(title_lookup.keys())
    cleaned: list[dict] = []
    for raw in raw_changes:
        c = _validate_change(
            raw,
            valid_task_ids=valid_task_ids,
            title_lookup=title_lookup,
        )
        if c is not None:
            cleaned.append(c)

    log.info(
        "weekly_focus.plan_for_focus: slot=%d %d changes proposed",
        slot_order, len(cleaned),
    )
    return {
        "focus": row.text,
        "linked_goal": linked_goal.title if linked_goal else None,
        "changes": cleaned,
    }
