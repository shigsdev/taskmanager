"""Business logic for the weekly review flow.

The weekly review shows all active tasks that haven't been reviewed in 7+ days
(or have never been reviewed). The user steps through them one at a time and
chooses an action for each:

- **keep**   — leave in current tier, stamp last_reviewed = today
- **freeze** — move to Freezer tier, stamp last_reviewed
- **delete** — soft-delete the task
- **snooze** — stamp last_reviewed = today (pushes it out of the review queue
               for another 7 days without changing its tier)
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import or_, select

from models import Task, TaskStatus, Tier, db


def stale_tasks(*, stale_days: int = 7) -> list[Task]:
    """Return all active tasks not reviewed in the last ``stale_days`` days.

    A task is considered "stale" if:
    - It has never been reviewed (last_reviewed IS NULL), OR
    - It was last reviewed more than ``stale_days`` days ago.

    Only active tasks are returned (not deleted/archived).
    """
    cutoff = date.today() - timedelta(days=stale_days)
    stmt = (
        select(Task)
        .where(Task.status == TaskStatus.ACTIVE)
        .where(
            or_(
                Task.last_reviewed.is_(None),
                Task.last_reviewed <= cutoff,
            )
        )
        .order_by(Task.updated_at.asc())
    )
    return list(db.session.scalars(stmt))


def review_task(task: Task, action: str) -> str:
    """Apply a review action to a task.

    Args:
        task: The task being reviewed.
        action: One of "keep", "freeze", "delete", "snooze".

    Returns:
        The action that was applied (for summary tracking).

    Raises:
        ValueError: If action is not recognized.
    """
    today = date.today()

    if action == "keep":
        task.last_reviewed = today
    elif action == "freeze":
        task.tier = Tier.FREEZER
        task.last_reviewed = today
    elif action == "delete":
        task.status = TaskStatus.DELETED
    elif action == "snooze":
        task.last_reviewed = today
    else:
        raise ValueError(f"unknown review action: {action!r}")

    db.session.commit()
    return action
