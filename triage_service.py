"""Heuristic triage suggestions (#12).

Surfaces tasks that have gone stale in their current tier and recommends
a tier move or delete. Heuristic-only — no LLM call. The single-user
threat model + low API budget make a pure-rules approach the right
trade-off; an LLM upgrade can come later when there's enough historical
completion data to make classification more useful than rules.

Heuristics (calibrated for a single owner who triages roughly weekly):

    INBOX        > 7 days  → suggest move to BACKLOG
    TODAY        past due_date by > 3 days  → suggest move to BACKLOG
    TOMORROW     past due_date by > 3 days  → suggest move to BACKLOG
    THIS_WEEK    > 14 days no movement  → suggest move to BACKLOG
    NEXT_WEEK    > 21 days no movement  → suggest move to BACKLOG
    BACKLOG      > 90 days  → suggest delete
    FREEZER      > 60 days  → suggest delete

"Movement" = `updated_at`. Touching the task in any way (tier change,
field edit, marking it reviewed) resets the staleness clock.

The stale_days values are conservative — better to miss a suggestion
than to nag the user about a task they're actively planning to do
soon. If the cohort grows over time, tuning is one-line edits.
"""
from __future__ import annotations

from sqlalchemy import select

from models import Task, TaskStatus, Tier, db
from utils import local_today_date

# Thresholds (days) — tunable in one place. Tracked separately from the
# tier enum so adding a new tier doesn't silently miss a heuristic.
INBOX_STALE_DAYS = 7
PAST_DUE_DAYS = 3  # TODAY + TOMORROW
THIS_WEEK_STALE_DAYS = 14
NEXT_WEEK_STALE_DAYS = 21
BACKLOG_STALE_DAYS = 90
FREEZER_STALE_DAYS = 60


def _suggestion(
    task: Task,
    *,
    suggested_action: str,
    suggested_tier: str | None,
    reason: str,
    days_stale: int,
) -> dict:
    return {
        "task_id": str(task.id),
        "title": task.title,
        "current_tier": task.tier.value,
        "suggested_action": suggested_action,  # "move" | "delete"
        "suggested_tier": suggested_tier,      # tier value if action=move else None
        "reason": reason,
        "days_stale": days_stale,
    }


def compute_triage_suggestions() -> list[dict]:
    """Return triage suggestions for all active tasks that hit a heuristic.

    Result shape: ``list[{task_id, title, current_tier, suggested_action,
    suggested_tier, reason, days_stale}]``. Empty list when no tasks
    qualify.

    Sorted by days_stale descending so the most-egregious cases bubble up.
    """
    today = local_today_date()
    stmt = (
        select(Task)
        .where(Task.status == TaskStatus.ACTIVE)
        .where(Task.parent_id.is_(None))  # subtasks ride along with their parent
    )
    suggestions: list[dict] = []

    for task in db.session.scalars(stmt):
        # Use updated_at (datetime, tz-aware) → date in the same tz
        # mental model the rest of the app uses for staleness.
        updated_date = task.updated_at.date() if task.updated_at else today
        days_since_update = (today - updated_date).days

        if task.tier == Tier.INBOX and days_since_update > INBOX_STALE_DAYS:
            suggestions.append(_suggestion(
                task,
                suggested_action="move",
                suggested_tier=Tier.BACKLOG.value,
                reason=f"untouched in inbox {days_since_update} days",
                days_stale=days_since_update,
            ))
            continue

        if task.tier in (Tier.TODAY, Tier.TOMORROW) and task.due_date:
            days_overdue = (today - task.due_date).days
            if days_overdue > PAST_DUE_DAYS:
                suggestions.append(_suggestion(
                    task,
                    suggested_action="move",
                    suggested_tier=Tier.BACKLOG.value,
                    reason=f"{days_overdue} days past due",
                    days_stale=days_overdue,
                ))
                continue

        if task.tier == Tier.THIS_WEEK and days_since_update > THIS_WEEK_STALE_DAYS:
            suggestions.append(_suggestion(
                task,
                suggested_action="move",
                suggested_tier=Tier.BACKLOG.value,
                reason=f"stuck in this-week {days_since_update} days",
                days_stale=days_since_update,
            ))
            continue

        if task.tier == Tier.NEXT_WEEK and days_since_update > NEXT_WEEK_STALE_DAYS:
            suggestions.append(_suggestion(
                task,
                suggested_action="move",
                suggested_tier=Tier.BACKLOG.value,
                reason=f"stuck in next-week {days_since_update} days",
                days_stale=days_since_update,
            ))
            continue

        if task.tier == Tier.BACKLOG and days_since_update > BACKLOG_STALE_DAYS:
            suggestions.append(_suggestion(
                task,
                suggested_action="delete",
                suggested_tier=None,
                reason=f"languishing in backlog {days_since_update} days",
                days_stale=days_since_update,
            ))
            continue

        if task.tier == Tier.FREEZER and days_since_update > FREEZER_STALE_DAYS:
            suggestions.append(_suggestion(
                task,
                suggested_action="delete",
                suggested_tier=None,
                reason=f"frozen {days_since_update} days",
                days_stale=days_since_update,
            ))
            continue

    suggestions.sort(key=lambda s: s["days_stale"], reverse=True)
    return suggestions
