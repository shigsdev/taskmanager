"""Settings service — configuration status and import history.

This is a single-user app. Configuration lives in environment variables.
The settings page shows what's configured (never revealing actual values)
and provides access to import history from the audit log.
"""
from __future__ import annotations

import os

from sqlalchemy import select

from models import ImportLog, db


def get_service_status() -> dict:
    """Check which external services are configured.

    Returns a dict of service names to booleans indicating whether
    the required env var is set. Never exposes actual key values.
    """
    return {
        "google_oauth": bool(os.environ.get("GOOGLE_CLIENT_ID")),
        "google_vision": bool(os.environ.get("GOOGLE_VISION_API_KEY")),
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "sendgrid": bool(os.environ.get("SENDGRID_API_KEY")),
        "digest_email": bool(os.environ.get("DIGEST_TO_EMAIL")),
        "digest_from": bool(os.environ.get("DIGEST_FROM_EMAIL")),
    }


def get_import_history(limit: int = 50) -> list[dict]:
    """Return recent import log entries, newest first.

    Args:
        limit: Maximum entries to return.

    Returns:
        List of dicts with id, source, imported_at, task_count, batch_id,
        undone_at. The last two fields drive the Undo / Restore buttons
        in the settings UI. A row with ``batch_id=None`` is a legacy
        import (before the recycle bin feature) and cannot be undone.
        A row with ``undone_at`` set is currently in the recycle bin.
    """
    stmt = (
        select(ImportLog)
        .order_by(ImportLog.imported_at.desc())
        .limit(limit)
    )
    logs = list(db.session.scalars(stmt))
    return [
        {
            "id": str(log.id),
            "source": log.source,
            "imported_at": log.imported_at.isoformat() if log.imported_at else None,
            "task_count": log.task_count,
            "batch_id": str(log.batch_id) if log.batch_id else None,
            "undone_at": log.undone_at.isoformat() if log.undone_at else None,
        }
        for log in logs
    ]


def get_app_stats() -> dict:
    """Return basic app statistics for the settings dashboard."""
    from models import Goal, RecurringTask, Task, TaskStatus

    total_tasks = db.session.scalar(
        select(db.func.count()).select_from(Task)
    ) or 0
    active_tasks = db.session.scalar(
        select(db.func.count()).select_from(Task).where(
            Task.status == TaskStatus.ACTIVE
        )
    ) or 0
    total_goals = db.session.scalar(
        select(db.func.count()).select_from(Goal).where(
            Goal.is_active.is_(True)
        )
    ) or 0
    recurring_count = db.session.scalar(
        select(db.func.count()).select_from(RecurringTask).where(
            RecurringTask.is_active.is_(True)
        )
    ) or 0

    return {
        "total_tasks": total_tasks,
        "active_tasks": active_tasks,
        "total_goals": total_goals,
        "recurring_templates": recurring_count,
    }
