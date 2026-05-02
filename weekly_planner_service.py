"""Weekly planner — single-call LLM pass that proposes a Mon–Sun plan.

Big-picture:
    Click "Generate plan" on /plan → server gathers ALL active non-frozen
    tasks + 4 weeks of completed history (velocity calibration) +
    upcoming recurring fires + goals/projects context + stale freezer
    items > 60 days → ONE Claude Haiku call returns a structured plan
    → review modal shows day-grouped suggestions + goal hints + stale
    freezer review section. User accepts / overrides / ignores per row,
    then Apply All routes through the canonical PATCH /api/tasks/<id>.

Design constants (per user choices 2026-05-02):

    HISTORY_WEEKS       = 4    # velocity + pattern detection window
    FREEZER_STALE_DAYS  = 60   # threshold for stale-freezer review
    MAX_TASKS_PER_CALL  = 100  # bound input size + cost (~$0.01 ceiling)

Reuses the egress.safe_call_api wiring per ADR-023. Mutations route
through PATCH /api/tasks/<id> from the client — no separate write
surface here.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from models import (
    Goal,
    GoalStatus,
    Project,
    Task,
    TaskStatus,
    Tier,
    db,
)
from utils import local_today_date

log = logging.getLogger(__name__)

HISTORY_WEEKS = 4
FREEZER_STALE_DAYS = 60
MAX_TASKS_PER_CALL = 100

_VALID_PLAN_TIERS: set[str] = {
    Tier.TODAY.value, Tier.TOMORROW.value, Tier.THIS_WEEK.value,
    Tier.NEXT_WEEK.value, Tier.BACKLOG.value, Tier.FREEZER.value,
}
# Days the planner can place a task on. Mon=0 … Sun=6 in iso weekday-1.
_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday",
              "Friday", "Saturday", "Sunday")


def next_monday_from(today: date) -> date:
    """Return the next Monday strictly after ``today``.

    If today IS a Monday, returns today + 7 (the user plans for the
    following week, not today's week).
    """
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    return today + timedelta(days=days_until_monday)


_PROMPT_TEMPLATE = """\
You are a personal weekly planner. Review the user's current task state
and propose a Mon–Sun plan for the target week.

Target week: {start_iso} (Monday) through {end_iso} (Sunday).
Today's date: {today_iso}.

CONTEXT — currently-tracked projects (use only these IDs for any
suggested_project_id you cite):
{projects_block}

CONTEXT — currently-tracked goals (use only these IDs for any
suggested_goal_id you cite):
{goals_block}

CONTEXT — last {history_weeks} weeks of COMPLETED tasks (velocity calibration +
pattern detection). Use this to estimate the user's realistic
throughput per week. Do NOT include these in suggestions — they're done.
{history_block}

CONTEXT — recurring tasks expected to FIRE during the target week
(these spawn automatically per their template; do not re-suggest them
as new tasks, but you may suggest moving the spawn day if it conflicts
with another commitment, or note them as already-committed time):
{recurring_block}

ACTIVE TASKS to plan (all tiers EXCEPT freezer; tasks the user has
explicitly silenced via planner_ignore are not included):
{tasks_block}

STALE FREEZER REVIEW — items frozen > {freezer_days} days that may be
worth thawing or deleting (separate section, NOT part of the main
weekly plan):
{stale_freezer_block}

Return ONE JSON object with these top-level keys:

  per_task_suggestions: array of objects, one per ACTIVE TASK above.
    Each object:
      task_id: string (must match an id from ACTIVE TASKS)
      action: "keep" | "move" | "delete" | "freeze"
        keep: leave as-is — task is well-categorized already
        move: change tier and/or due_date per the suggested fields
        delete: drop it — looks abandoned or no-longer-relevant
        freeze: park in FREEZER for now
      suggested_tier: one of {{today, tomorrow, this_week, next_week,
        backlog, freezer}} (omit / use null when action != "move")
      suggested_due_date: ISO YYYY-MM-DD (use a date inside the target
        week if action="move" and tier=today/tomorrow/this_week, or
        null/omit otherwise)
      suggested_project_id: string ID from PROJECTS context, or null
      suggested_goal_id: string ID from GOALS context, or null
      reason: one short sentence (≤ 100 chars) explaining the choice

  day_by_day_plan: object keyed by weekday name. Each value is a
    list of task_ids you plan to land on that day (sourced from
    per_task_suggestions where suggested_due_date falls on that day).
    Keys: "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    "Saturday", "Sunday".

  goal_hints: array of objects, one per goal in the GOALS context.
      goal_id: string
      status: "on_track" | "falling_behind" | "no_progress" | "ahead"
      recommendation: short sentence — "add a task for this goal next
        week" / "you have N tasks linked, looks healthy" / etc.

  velocity_warning: string OR null. If your suggestions for today /
    tomorrow / this_week combined exceed the user's average completed
    tasks per week (computed from history) by more than 1.2x, surface a
    warning here ("Plan has 28 commitments; last 4 weeks averaged 18
    completions — consider deferring some to next_week"). Otherwise null.

  stale_freezer_review: array of objects, one per STALE FREEZER item.
      task_id: string
      recommendation: "thaw_to_<tier>" | "delete" | "keep_frozen"
      reason: short sentence

Respond with ONLY the JSON object — no markdown fences, no prose
before or after.
"""


def _format_projects_block(projects: list[dict]) -> str:
    if not projects:
        return "  (no projects)"
    return "\n".join(
        f"  - id={p['id']}: {p['name']} (type={p['type']}"
        + (f", goal_id={p['goal_id']}" if p.get("goal_id") else "")
        + ")"
        for p in projects
    )


def _format_goals_block(goals: list[dict]) -> str:
    if not goals:
        return "  (no goals)"
    return "\n".join(
        f"  - id={g['id']}: {g['title']} (category={g['category']})"
        for g in goals
    )


def _format_tasks_block(tasks: list[dict]) -> str:
    if not tasks:
        return "  (no active tasks to plan)"
    lines = []
    for t in tasks:
        meta_parts = [f"tier={t['tier']}"]
        if t.get("due_date"):
            meta_parts.append(f"due={t['due_date']}")
        if t.get("project_id"):
            meta_parts.append(f"project_id={t['project_id']}")
        if t.get("goal_id"):
            meta_parts.append(f"goal_id={t['goal_id']}")
        meta_parts.append(f"days_since_update={t['days_since_update']}")
        lines.append(f"  - id={t['id']}: {t['title']} ({', '.join(meta_parts)})")
    return "\n".join(lines)


def _format_history_block(completed: list[dict]) -> str:
    if not completed:
        return "  (no completion history yet)"
    # Just titles + completion dates — Claude needs counts/patterns,
    # not full task records. Keep tokens down.
    lines = [f"  - {c['title']} (done {c['completed_iso']})" for c in completed]
    return "\n".join(lines)


def _format_recurring_block(fires: list[dict]) -> str:
    if not fires:
        return "  (no recurring fires this week)"
    return "\n".join(
        f"  - {f['title']} fires {f['fire_day']}" for f in fires
    )


def _format_stale_freezer_block(items: list[dict]) -> str:
    if not items:
        return "  (no stale freezer items)"
    return "\n".join(
        f"  - id={i['id']}: {i['title']} (frozen {i['days_frozen']} days)"
        for i in items
    )


def _load_active_tasks(today: date) -> list[Task]:
    stmt = (
        select(Task)
        .where(Task.status == TaskStatus.ACTIVE)
        .where(Task.tier != Tier.FREEZER)
        .where(Task.parent_id.is_(None))
        .where(Task.planner_ignore.is_(False))
        .order_by(Task.created_at.asc())
        .limit(MAX_TASKS_PER_CALL)
    )
    return list(db.session.scalars(stmt))


def _load_completed_history(today: date) -> list[dict]:
    cutoff = today - timedelta(weeks=HISTORY_WEEKS)
    stmt = (
        select(Task)
        # TaskStatus.ARCHIVED is the "completed" state in this codebase.
        .where(Task.status == TaskStatus.ARCHIVED)
        .where(Task.parent_id.is_(None))
        .order_by(Task.updated_at.desc())
        .limit(200)
    )
    out: list[dict] = []
    for t in db.session.scalars(stmt):
        completed_date = t.updated_at.date() if t.updated_at else today
        if completed_date < cutoff:
            continue
        out.append({"title": t.title, "completed_iso": completed_date.isoformat()})
    return out


def _load_recurring_fires(start: date, end: date) -> list[dict]:
    """Return the recurring templates that will fire between start and end.

    Best-effort enumeration — uses RecurringTask.compute_fires() if
    available, otherwise returns templates whose frequency overlaps
    the week. The plan tolerates an approximate list — Claude only
    needs to know "these are reserved time".
    """
    try:
        from recurring_service import compute_previews_in_range
        previews = compute_previews_in_range(start, end)
    except Exception as e:  # noqa: BLE001
        log.warning("recurring preview load failed: %s", e)
        return []
    return [
        {"title": p.get("title", ""), "fire_day": p.get("due_date", "")}
        for p in previews
    ]


def _load_stale_freezer(today: date) -> list[dict]:
    cutoff = today - timedelta(days=FREEZER_STALE_DAYS)
    stmt = (
        select(Task)
        .where(Task.status == TaskStatus.ACTIVE)
        .where(Task.tier == Tier.FREEZER)
        .where(Task.parent_id.is_(None))
        .where(Task.planner_ignore.is_(False))
        .order_by(Task.updated_at.asc())
    )
    out: list[dict] = []
    for t in db.session.scalars(stmt):
        updated_date = t.updated_at.date() if t.updated_at else today
        if updated_date >= cutoff:
            continue
        out.append({
            "id": str(t.id),
            "title": t.title,
            "days_frozen": (today - updated_date).days,
        })
    return out


def _load_projects() -> list[dict]:
    stmt = select(Project).where(Project.is_active.is_(True))
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "type": p.type.value,
            "goal_id": str(p.goal_id) if p.goal_id else None,
        }
        for p in db.session.scalars(stmt)
    ]


def _load_goals() -> list[dict]:
    stmt = select(Goal).where(Goal.status != GoalStatus.DONE)
    return [
        {"id": str(g.id), "title": g.title, "category": g.category.value}
        for g in db.session.scalars(stmt)
    ]


def _serialize_active(t: Task, today: date) -> dict:
    updated_date = t.updated_at.date() if t.updated_at else today
    return {
        "id": str(t.id),
        "title": t.title,
        "tier": t.tier.value,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "project_id": str(t.project_id) if t.project_id else None,
        "goal_id": str(t.goal_id) if t.goal_id else None,
        "days_since_update": (today - updated_date).days,
    }


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
            timeout_sec=90,
            vendor="Claude",
        )
    except EgressError as e:
        raise RuntimeError(str(e)) from e


def _parse_claude_response(raw_text: str) -> dict:
    text = raw_text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    if "```" in text:
        for part in text.split("```"):
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            try:
                data = json.loads(cleaned)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue
    raise ValueError("Claude response did not contain a JSON object")


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_per_task(
    raw: dict,
    *,
    valid_task_ids: set[str],
    valid_project_ids: set[str],
    valid_goal_ids: set[str],
    target_start: date,
    target_end: date,
) -> dict | None:
    if not isinstance(raw, dict):
        return None
    task_id = raw.get("task_id")
    if not isinstance(task_id, str) or task_id not in valid_task_ids:
        return None

    action = raw.get("action")
    if action not in ("keep", "move", "delete", "freeze"):
        action = "keep"

    tier = raw.get("suggested_tier")
    if tier not in _VALID_PLAN_TIERS:
        tier = None

    due = raw.get("suggested_due_date")
    if due is not None:
        if not isinstance(due, str) or not _ISO_DATE_RE.match(due):
            due = None
        else:
            try:
                d = date.fromisoformat(due)
                # If the date isn't inside the target week and the
                # action is "move", clamp it to the week boundaries
                # rather than dropping the suggestion.
                if d < target_start:
                    due = target_start.isoformat()
                elif d > target_end:
                    due = target_end.isoformat()
            except (TypeError, ValueError):
                due = None

    proj = raw.get("suggested_project_id")
    if proj is not None and (not isinstance(proj, str) or proj not in valid_project_ids):
        proj = None

    goal = raw.get("suggested_goal_id")
    if goal is not None and (not isinstance(goal, str) or goal not in valid_goal_ids):
        goal = None

    reason = raw.get("reason")
    reason = reason.strip()[:140] if isinstance(reason, str) else ""

    return {
        "task_id": task_id,
        "action": action,
        "suggested_tier": tier,
        "suggested_due_date": due,
        "suggested_project_id": proj,
        "suggested_goal_id": goal,
        "reason": reason,
    }


def _validate_goal_hint(raw: dict, *, valid_goal_ids: set[str]) -> dict | None:
    if not isinstance(raw, dict):
        return None
    gid = raw.get("goal_id")
    if not isinstance(gid, str) or gid not in valid_goal_ids:
        return None
    status = raw.get("status")
    if status not in ("on_track", "falling_behind", "no_progress", "ahead"):
        status = "no_progress"
    rec = raw.get("recommendation")
    rec = rec.strip()[:200] if isinstance(rec, str) else ""
    return {"goal_id": gid, "status": status, "recommendation": rec}


def _validate_stale_freezer(raw: dict, *, valid_task_ids: set[str]) -> dict | None:
    if not isinstance(raw, dict):
        return None
    tid = raw.get("task_id")
    if not isinstance(tid, str) or tid not in valid_task_ids:
        return None
    rec_action = raw.get("recommendation", "")
    if not isinstance(rec_action, str):
        rec_action = "keep_frozen"
    reason = raw.get("reason")
    reason = reason.strip()[:140] if isinstance(reason, str) else ""
    return {"task_id": tid, "recommendation": rec_action[:60], "reason": reason}


def compute_weekly_plan(start_date: date | None = None) -> dict:
    """Build inputs, call Claude, validate response, return structured plan.

    If ``start_date`` is None, defaults to the next Monday after today
    (per user workflow — planning the upcoming week ahead of time).

    Returns:
        ``{
            "start_date": "YYYY-MM-DD",
            "end_date":   "YYYY-MM-DD",
            "active_count": int,
            "stale_freezer_count": int,
            "per_task_suggestions": [...],
            "day_by_day_plan": {Monday: [...], ...},
            "goal_hints": [...],
            "velocity_warning": str | None,
            "stale_freezer_review": [...],
            "model": "claude-haiku-...",
        }``

    Raises:
        RuntimeError: if ANTHROPIC_API_KEY is missing or Claude returns
        an unparseable response.
    """
    today = local_today_date()
    if start_date is None:
        start_date = next_monday_from(today)
    end_date = start_date + timedelta(days=6)

    active = _load_active_tasks(today)
    completed = _load_completed_history(today)
    recurring = _load_recurring_fires(start_date, end_date)
    stale_freezer = _load_stale_freezer(today)
    projects = _load_projects()
    goals = _load_goals()

    if not active and not stale_freezer:
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "active_count": 0,
            "stale_freezer_count": 0,
            "per_task_suggestions": [],
            "day_by_day_plan": {n: [] for n in _DAY_NAMES},
            "goal_hints": [],
            "velocity_warning": None,
            "stale_freezer_review": [],
            "model": None,
        }

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    active_serialized = [_serialize_active(t, today) for t in active]
    title_lookup = {a["id"]: a["title"] for a in active_serialized}
    stale_lookup = {s["id"]: s["title"] for s in stale_freezer}

    prompt = _PROMPT_TEMPLATE.format(
        start_iso=start_date.isoformat(),
        end_iso=end_date.isoformat(),
        today_iso=today.isoformat(),
        history_weeks=HISTORY_WEEKS,
        freezer_days=FREEZER_STALE_DAYS,
        projects_block=_format_projects_block(projects),
        goals_block=_format_goals_block(goals),
        history_block=_format_history_block(completed),
        recurring_block=_format_recurring_block(recurring),
        tasks_block=_format_tasks_block(active_serialized),
        stale_freezer_block=_format_stale_freezer_block(stale_freezer),
    )

    response = _post_to_claude(api_key, prompt, max_tokens=12000)
    raw_text = response.get("content", [{}])[0].get("text", "")
    raw = _parse_claude_response(raw_text)

    valid_task_ids = set(title_lookup.keys())
    valid_stale_ids = set(stale_lookup.keys())
    valid_project_ids = {p["id"] for p in projects}
    valid_goal_ids = {g["id"] for g in goals}

    cleaned_per_task: list[dict] = []
    seen_ids: set[str] = set()
    for r in raw.get("per_task_suggestions", []) or []:
        s = _validate_per_task(
            r,
            valid_task_ids=valid_task_ids,
            valid_project_ids=valid_project_ids,
            valid_goal_ids=valid_goal_ids,
            target_start=start_date,
            target_end=end_date,
        )
        if s is None or s["task_id"] in seen_ids:
            continue
        s["title"] = title_lookup[s["task_id"]]
        cleaned_per_task.append(s)
        seen_ids.add(s["task_id"])

    # Backfill any active task Claude omitted with a "keep" default.
    for tid, title in title_lookup.items():
        if tid in seen_ids:
            continue
        cleaned_per_task.append({
            "task_id": tid,
            "title": title,
            "action": "keep",
            "suggested_tier": None,
            "suggested_due_date": None,
            "suggested_project_id": None,
            "suggested_goal_id": None,
            "reason": "(no suggestion returned — review manually)",
        })

    # Day-by-day from suggested_due_date.
    day_plan: dict[str, list[str]] = {n: [] for n in _DAY_NAMES}
    for s in cleaned_per_task:
        if s["action"] != "move" or not s["suggested_due_date"]:
            continue
        try:
            d = date.fromisoformat(s["suggested_due_date"])
            day_plan[_DAY_NAMES[d.weekday()]].append(s["task_id"])
        except (TypeError, ValueError):
            continue

    # Goal hints — validate from Claude, backfill any missing goal as no_progress.
    cleaned_hints: list[dict] = []
    seen_goals: set[str] = set()
    for r in raw.get("goal_hints", []) or []:
        h = _validate_goal_hint(r, valid_goal_ids=valid_goal_ids)
        if h and h["goal_id"] not in seen_goals:
            cleaned_hints.append(h)
            seen_goals.add(h["goal_id"])
    for g in goals:
        if g["id"] not in seen_goals:
            cleaned_hints.append({
                "goal_id": g["id"],
                "status": "no_progress",
                "recommendation": "(no hint returned — review manually)",
            })
    # Annotate with goal title for client convenience.
    goal_title_map = {g["id"]: g["title"] for g in goals}
    for h in cleaned_hints:
        h["goal_title"] = goal_title_map.get(h["goal_id"], "")

    # Velocity warning passthrough — string or null.
    velocity = raw.get("velocity_warning")
    if not isinstance(velocity, str) or not velocity.strip():
        velocity = None
    else:
        velocity = velocity.strip()[:240]

    # Stale freezer review.
    cleaned_freezer: list[dict] = []
    seen_freezer: set[str] = set()
    for r in raw.get("stale_freezer_review", []) or []:
        s = _validate_stale_freezer(r, valid_task_ids=valid_stale_ids)
        if s and s["task_id"] not in seen_freezer:
            s["title"] = stale_lookup[s["task_id"]]
            cleaned_freezer.append(s)
            seen_freezer.add(s["task_id"])

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "active_count": len(active_serialized),
        "stale_freezer_count": len(stale_freezer),
        "per_task_suggestions": cleaned_per_task,
        "day_by_day_plan": day_plan,
        "goal_hints": cleaned_hints,
        "velocity_warning": velocity,
        "stale_freezer_review": cleaned_freezer,
        "model": "claude-haiku-4-5-20251001",
    }
