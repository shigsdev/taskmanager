"""Inbox auto-categorization (Option A from #post-12 brainstorm).

Single-call Claude pass that takes every active INBOX task and returns
suggested {tier, project_id, goal_id, due_date, type} so the user can
review-then-apply in one batch instead of opening each task and clicking
through 5 dropdowns.

Design:

- One Claude call per click. Inbox is capped at 50 tasks per call to
  bound input size + cost; if the inbox is larger, the user runs the
  flow twice.
- Suggestions only — never auto-applies. The UI shows a review modal
  where the user can override per-row before clicking "Apply all".
- Uses Haiku, not Sonnet, since classification is well-defined +
  cheap. ~$0.001 per 50-task batch.
- Server-side projects + goals lists are passed verbatim to the
  prompt so Claude can ID-match its picks. We then re-validate the
  IDs server-side before returning to the client (defense against
  Claude hallucinating IDs).

Returned shape (one entry per inbox task):
    {
      "task_id": str,
      "title": str,                  # echoed back for UI rendering
      "suggested_tier": str,         # one of TIER_VALUES (excluding inbox)
      "suggested_project_id": str | None,
      "suggested_goal_id": str | None,
      "suggested_due_date": str | None,    # ISO date
      "suggested_type": str,         # "work" | "personal"
      "reason": str,                 # short explanation
    }
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from sqlalchemy import select

from models import Goal, GoalStatus, Project, Task, TaskStatus, TaskType, Tier, db
from utils import local_today_date

log = logging.getLogger(__name__)

# Cap input to bound cost + Claude input size. Inbox >50 means the user
# needs to run the flow twice (rare; manual triage flows handle the rest).
MAX_INBOX_TASKS_PER_CALL = 50

# Claude can suggest any tier except INBOX (that's the source).
_VALID_SUGGESTED_TIERS: set[str] = {
    Tier.TODAY.value, Tier.TOMORROW.value, Tier.THIS_WEEK.value,
    Tier.NEXT_WEEK.value, Tier.BACKLOG.value, Tier.FREEZER.value,
}
_VALID_TYPES: set[str] = {TaskType.WORK.value, TaskType.PERSONAL.value}


_PROMPT_TEMPLATE = """You are a personal task categorization assistant. Review the
user's inbox tasks and suggest where each one should go.

Today's date is {today_iso} ({today_weekday}).

CONTEXT — currently-tracked projects and goals:

Projects (use only these IDs for suggested_project_id):
{projects_block}

Goals (use only these IDs for suggested_goal_id):
{goals_block}

INBOX TASKS to categorize:
{tasks_block}

For each task, choose values for:

  suggested_tier — one of: today, tomorrow, this_week, next_week, backlog, freezer
    today: time-sensitive and clearly today (e.g. "Take 3pm meds", "Call doctor before 5pm")
    tomorrow: clearly tomorrow only
    this_week: should happen within the current week
    next_week: planned for the following week
    backlog: should happen sometime, no strong urgency
    freezer: parking lot — interesting but no near-term commitment

  suggested_project_id — pick the most-relevant project ID from the list above, or null if none.
    Only use IDs from the Projects list. NEVER invent an ID.

  suggested_goal_id — pick the most-relevant goal ID from the list above, or null if none fits.
    If suggested_project_id is set, prefer that project's goal_id.
    Only use IDs from the Goals list. NEVER invent an ID.

  suggested_due_date — ISO date string (YYYY-MM-DD), or null. Set when the title implies one
    (e.g. "Pay rent by 15th" → next 15th; "Mom's birthday Friday" → upcoming Friday).
    Otherwise null.

  suggested_type — "work" or "personal". Default "personal" if ambiguous unless the
    title clearly references work projects, code, deadlines, meetings, etc.

  reason — one short sentence (≤ 80 chars) explaining the most-influential signal.

Respond with ONLY a JSON array. No markdown fences, no prose before or after.
Each entry must have exactly these keys:
  task_id, suggested_tier, suggested_project_id, suggested_goal_id,
  suggested_due_date, suggested_type, reason

Order doesn't matter. Every task in INBOX TASKS must appear exactly once.
"""


def _format_projects_block(projects: list[dict]) -> str:
    if not projects:
        return "(none)"
    lines = []
    for p in projects:
        goal_part = f", goal_id={p['goal_id']}" if p.get("goal_id") else ""
        lines.append(f"  - id={p['id']}: {p['title']} (type={p['type']}{goal_part})")
    return "\n".join(lines)


def _format_goals_block(goals: list[dict]) -> str:
    if not goals:
        return "(none)"
    lines = []
    for g in goals:
        lines.append(f"  - id={g['id']}: {g['title']} (category={g['category']})")
    return "\n".join(lines)


def _format_tasks_block(tasks: list[dict]) -> str:
    if not tasks:
        return "(none)"
    lines = []
    for t in tasks:
        lines.append(f"  - id={t['id']}: {t['title']}")
    return "\n".join(lines)


def _load_inbox_context() -> tuple[list[Task], list[dict], list[dict]]:
    """Load the inbox + the active-project + active-goal lists in one
    pass. Subtasks excluded (parent rides the categorization)."""
    inbox_stmt = (
        select(Task)
        .where(Task.status == TaskStatus.ACTIVE)
        .where(Task.tier == Tier.INBOX)
        .where(Task.parent_id.is_(None))
        .order_by(Task.created_at.asc())
        .limit(MAX_INBOX_TASKS_PER_CALL)
    )
    tasks = list(db.session.scalars(inbox_stmt))

    proj_stmt = select(Project).where(Project.is_active.is_(True))
    projects = [
        {
            "id": str(p.id),
            # Project model uses `name`; surface as `title` for prompt symmetry with Goal.
            "title": p.name,
            "type": p.type.value,
            "goal_id": str(p.goal_id) if p.goal_id else None,
        }
        for p in db.session.scalars(proj_stmt)
    ]

    goal_stmt = select(Goal).where(Goal.status != GoalStatus.DONE)
    goals = [
        {"id": str(g.id), "title": g.title, "category": g.category.value}
        for g in db.session.scalars(goal_stmt)
    ]

    return tasks, projects, goals


def _build_prompt(tasks: list[Task], projects: list[dict], goals: list[dict]) -> str:
    today = local_today_date()
    return _PROMPT_TEMPLATE.format(
        today_iso=today.isoformat(),
        today_weekday=today.strftime("%A"),
        projects_block=_format_projects_block(projects),
        goals_block=_format_goals_block(goals),
        tasks_block=_format_tasks_block([
            {"id": str(t.id), "title": t.title} for t in tasks
        ]),
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
                # Haiku — classification is well-defined; Sonnet is overkill.
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
    """Extract the JSON array from Claude's response, tolerant of markdown
    fences."""
    text = raw_text.strip()
    # Direct parse first.
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    # Fence-stripping fallback.
    if "```" in text:
        for part in text.split("```"):
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            try:
                data = json.loads(cleaned)
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                continue
    raise ValueError("Claude response did not contain a JSON array")


def _validate_suggestion(
    raw: dict,
    *,
    valid_task_ids: set[str],
    valid_project_ids: set[str],
    valid_goal_ids: set[str],
    title_lookup: dict[str, str],
) -> dict | None:
    """Coerce + sanity-check one row from Claude. Drops the row if any
    must-have field is malformed; returns the cleaned dict otherwise."""
    if not isinstance(raw, dict):
        return None
    task_id = raw.get("task_id")
    if not isinstance(task_id, str) or task_id not in valid_task_ids:
        return None

    tier = raw.get("suggested_tier")
    if tier not in _VALID_SUGGESTED_TIERS:
        tier = Tier.BACKLOG.value  # safe default

    type_ = raw.get("suggested_type")
    if type_ not in _VALID_TYPES:
        type_ = TaskType.PERSONAL.value

    proj_id = raw.get("suggested_project_id")
    if proj_id is not None and (
        not isinstance(proj_id, str) or proj_id not in valid_project_ids
    ):
        proj_id = None

    goal_id = raw.get("suggested_goal_id")
    if goal_id is not None and (
        not isinstance(goal_id, str) or goal_id not in valid_goal_ids
    ):
        goal_id = None

    due = raw.get("suggested_due_date")
    if due is not None:
        if not isinstance(due, str) or len(due) != 10:
            due = None
        else:
            # YYYY-MM-DD basic shape check; rely on PATCH-side strict
            # parsing for full validation.
            try:
                from datetime import date as _date
                _date.fromisoformat(due)
            except (TypeError, ValueError):
                due = None

    reason = raw.get("reason")
    if not isinstance(reason, str):
        reason = ""
    reason = reason.strip()[:120]

    return {
        "task_id": task_id,
        "title": title_lookup[task_id],
        "suggested_tier": tier,
        "suggested_project_id": proj_id,
        "suggested_goal_id": goal_id,
        "suggested_due_date": due,
        "suggested_type": type_,
        "reason": reason,
    }


def categorize_inbox() -> dict:
    """Entry point. Loads inbox + context, calls Claude, validates the
    response, returns the structured suggestions list (plus metadata).

    Returns a dict (NOT raw list) so the API response can include
    ``count`` + ``model`` + ``capped`` flags without changing shape later.
    """
    tasks, projects, goals = _load_inbox_context()

    if not tasks:
        return {"count": 0, "suggestions": [], "capped": False}

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    prompt = _build_prompt(tasks, projects, goals)
    # ~150 chars per suggestion × 50 max = ~7500 chars; 8000 token budget
    # leaves room for verbose reasons without truncation.
    response = _post_to_claude(api_key, prompt, max_tokens=8000)
    raw_text = response.get("content", [{}])[0].get("text", "")
    raw_suggestions = _parse_claude_response(raw_text)

    title_lookup = {str(t.id): t.title for t in tasks}
    valid_task_ids = set(title_lookup.keys())
    valid_project_ids = {p["id"] for p in projects}
    valid_goal_ids = {g["id"] for g in goals}

    cleaned: list[dict] = []
    seen_ids: set[str] = set()
    for raw in raw_suggestions:
        s = _validate_suggestion(
            raw,
            valid_task_ids=valid_task_ids,
            valid_project_ids=valid_project_ids,
            valid_goal_ids=valid_goal_ids,
            title_lookup=title_lookup,
        )
        if s is None:
            continue
        if s["task_id"] in seen_ids:
            continue  # Claude doubled up — keep the first.
        cleaned.append(s)
        seen_ids.add(s["task_id"])

    # Backfill any task Claude omitted entirely with a default suggestion
    # so the UI can show ALL inbox tasks (Claude might silently drop a row).
    for t in tasks:
        tid = str(t.id)
        if tid in seen_ids:
            continue
        cleaned.append({
            "task_id": tid,
            "title": t.title,
            "suggested_tier": Tier.BACKLOG.value,
            "suggested_project_id": None,
            "suggested_goal_id": None,
            "suggested_due_date": None,
            "suggested_type": t.type.value,
            "reason": "(no suggestion returned — review manually)",
        })

    capped = len(tasks) == MAX_INBOX_TASKS_PER_CALL
    log.info("inbox_categorize: %d tasks suggested (capped=%s)", len(cleaned), capped)
    return {
        "count": len(cleaned),
        "suggestions": cleaned,
        "capped": capped,
    }


# Re-export uuid for tests that need to construct fake task IDs.
__all__ = ["categorize_inbox", "MAX_INBOX_TASKS_PER_CALL", "uuid"]
