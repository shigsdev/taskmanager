"""Recycle bin service — undo/restore/purge for bulk imports.

A "batch" is a bulk-import operation: OneNote tasks, Excel goals, or an
image scan confirm-to-Inbox. Every row created in a batch carries the
same ``batch_id`` as the corresponding ``ImportLog`` row.

Undo (soft-delete) flow:
    batch is live
        ↓  POST /api/recycle-bin/undo/<batch_id>
    batch is in recycle bin (rows hidden, ImportLog.undone_at set)
        ↓  POST /api/recycle-bin/restore/<batch_id>
    batch is live again
        ↓  POST /api/recycle-bin/purge/<batch_id>
    batch is hard-deleted (rows gone, ImportLog row remains as audit)

State of a batch is determined by ``ImportLog.undone_at``:
    NULL  → live
    !NULL → in recycle bin (soft-deleted)
    gone (ImportLog row deleted) → purged

Scope decision: this recycle bin is import-undo only. Regular task delete
(trash icon) continues to hard soft-delete via ``TaskStatus.DELETED``
without going through the bin. See CLAUDE.md / BACKLOG.md for rationale.

No automated cleanup — the user manually purges batches or empties the
whole bin via the UI. See "Recycle bin: automated TTL cleanup" in the
BACKLOG Freezer for the deferred auto-expiry feature.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from models import Goal, ImportLog, Task, TaskStatus, db

# --- Errors ------------------------------------------------------------------


class BatchNotFoundError(Exception):
    """Raised when a batch_id has no matching ImportLog row."""


class BatchStateError(Exception):
    """Raised when an operation is invalid for the batch's current state.

    Examples:
        - undo() called on a batch that is already in the recycle bin
        - restore() called on a batch that is live
        - purge() called on a batch that is live (must undo first)
    """


class ConfirmationError(Exception):
    """Raised when a destructive operation is missing the typed confirmation."""


_CONFIRMATION_TOKEN = "DELETE"  # noqa: S105  # nosec B105 - typed-confirmation token (user must type "DELETE" to proceed), not a password


# --- Helpers -----------------------------------------------------------------


def _require_confirmation(token: str | None) -> None:
    if token != _CONFIRMATION_TOKEN:
        raise ConfirmationError(
            f'confirmation token must be exactly "{_CONFIRMATION_TOKEN}"'
        )


def _get_log(batch_id: uuid.UUID) -> ImportLog:
    log = db.session.scalar(
        select(ImportLog).where(ImportLog.batch_id == batch_id)
    )
    if log is None:
        raise BatchNotFoundError(f"no import batch with id {batch_id}")
    return log


def _batch_tasks(batch_id: uuid.UUID) -> list[Task]:
    """Return all tasks in a batch, regardless of status."""
    return list(
        db.session.scalars(select(Task).where(Task.batch_id == batch_id))
    )


def _batch_goals(batch_id: uuid.UUID) -> list[Goal]:
    """Return all goals in a batch, regardless of is_active."""
    return list(
        db.session.scalars(select(Goal).where(Goal.batch_id == batch_id))
    )


# --- Listing -----------------------------------------------------------------


def list_bin() -> list[dict]:
    """Return all batches currently in the recycle bin, newest undo first.

    Each entry contains enough info to render the recycle bin UI:
    batch_id, source, imported_at, undone_at, task_count, goal_count.
    """
    stmt = (
        select(ImportLog)
        .where(ImportLog.undone_at.is_not(None))
        .where(ImportLog.batch_id.is_not(None))
        .order_by(ImportLog.undone_at.desc())
    )
    entries = []
    for log in db.session.scalars(stmt):
        task_count = (
            db.session.scalar(
                select(db.func.count())
                .select_from(Task)
                .where(
                    Task.batch_id == log.batch_id,
                    Task.status == TaskStatus.DELETED,
                )
            )
            or 0
        )
        goal_count = (
            db.session.scalar(
                select(db.func.count())
                .select_from(Goal)
                .where(
                    Goal.batch_id == log.batch_id,
                    Goal.is_active.is_(False),
                )
            )
            or 0
        )
        entries.append(
            {
                "batch_id": str(log.batch_id),
                "source": log.source,
                "imported_at": (
                    log.imported_at.isoformat() if log.imported_at else None
                ),
                "undone_at": (
                    log.undone_at.isoformat() if log.undone_at else None
                ),
                "task_count": task_count,
                "goal_count": goal_count,
            }
        )
    return entries


def bin_summary() -> dict:
    """Return aggregate counts across every batch in the recycle bin.

    Used by the "Empty bin" confirmation modal and the settings badge.
    """
    task_count = (
        db.session.scalar(
            select(db.func.count())
            .select_from(Task)
            .join(
                ImportLog,
                ImportLog.batch_id == Task.batch_id,  # noqa: E711
            )
            .where(
                Task.status == TaskStatus.DELETED,
                Task.batch_id.is_not(None),
                ImportLog.undone_at.is_not(None),
            )
        )
        or 0
    )
    goal_count = (
        db.session.scalar(
            select(db.func.count())
            .select_from(Goal)
            .join(
                ImportLog,
                ImportLog.batch_id == Goal.batch_id,  # noqa: E711
            )
            .where(
                Goal.is_active.is_(False),
                Goal.batch_id.is_not(None),
                ImportLog.undone_at.is_not(None),
            )
        )
        or 0
    )
    batch_count = (
        db.session.scalar(
            select(db.func.count())
            .select_from(ImportLog)
            .where(
                ImportLog.undone_at.is_not(None),
                ImportLog.batch_id.is_not(None),
            )
        )
        or 0
    )
    return {
        "batch_count": batch_count,
        "task_count": task_count,
        "goal_count": goal_count,
    }


# --- Undo / Restore / Purge --------------------------------------------------


def undo_batch(batch_id: uuid.UUID) -> dict:
    """Move a batch to the recycle bin (soft-delete all rows)."""
    log = _get_log(batch_id)
    if log.undone_at is not None:
        raise BatchStateError(f"batch {batch_id} is already in the recycle bin")

    tasks = _batch_tasks(batch_id)
    goals = _batch_goals(batch_id)

    for task in tasks:
        if task.status == TaskStatus.ACTIVE or task.status == TaskStatus.ARCHIVED:
            task.status = TaskStatus.DELETED
    for goal in goals:
        if goal.is_active:
            goal.is_active = False

    log.undone_at = datetime.now(UTC)
    db.session.commit()

    return {
        "batch_id": str(batch_id),
        "tasks_removed": len(tasks),
        "goals_removed": len(goals),
    }


def restore_batch(batch_id: uuid.UUID) -> dict:
    """Restore a batch from the recycle bin (un-soft-delete).

    Only rows whose status is still ``DELETED`` / ``is_active=False`` are
    restored. If something has already been manually edited or had its
    status changed elsewhere, we leave it alone to avoid clobbering user
    intent.
    """
    log = _get_log(batch_id)
    if log.undone_at is None:
        raise BatchStateError(f"batch {batch_id} is not in the recycle bin")

    tasks = _batch_tasks(batch_id)
    goals = _batch_goals(batch_id)

    restored_tasks = 0
    for task in tasks:
        if task.status == TaskStatus.DELETED:
            task.status = TaskStatus.ACTIVE
            restored_tasks += 1

    restored_goals = 0
    for goal in goals:
        if not goal.is_active:
            goal.is_active = True
            restored_goals += 1

    log.undone_at = None
    db.session.commit()

    return {
        "batch_id": str(batch_id),
        "tasks_restored": restored_tasks,
        "goals_restored": restored_goals,
    }


def purge_batch(batch_id: uuid.UUID, confirmation: str | None) -> dict:
    """Hard-delete all rows in a batch. Batch must be in the recycle bin.

    Before deleting goals, any Task.goal_id FK pointing to one of the
    purged goals is nulled out so we never leave a dangling reference.
    The ImportLog row is retained as an audit trail but gets its
    ``batch_id`` nulled so it's clearly disassociated.
    """
    _require_confirmation(confirmation)

    log = _get_log(batch_id)
    if log.undone_at is None:
        raise BatchStateError(
            f"batch {batch_id} must be in the recycle bin before it can be "
            f"purged — call undo first"
        )

    tasks = _batch_tasks(batch_id)
    goals = _batch_goals(batch_id)
    goal_ids = [g.id for g in goals]

    # Null out any external references to the goals we're about to purge.
    if goal_ids:
        db.session.execute(
            update(Task)
            .where(Task.goal_id.in_(goal_ids))
            .values(goal_id=None)
        )

    for task in tasks:
        db.session.delete(task)
    for goal in goals:
        db.session.delete(goal)

    # Retain the ImportLog row as audit, but disassociate it from the now
    # non-existent rows.
    log.batch_id = None
    db.session.commit()

    return {
        "batch_id": str(batch_id),
        "tasks_purged": len(tasks),
        "goals_purged": len(goals),
    }


def empty_bin(confirmation: str | None) -> dict:
    """Hard-delete every batch currently in the recycle bin.

    Iterates over each soft-deleted batch and calls ``purge_batch`` on it.
    The confirmation token is checked once up front, not per batch.
    """
    _require_confirmation(confirmation)

    stmt = (
        select(ImportLog.batch_id)
        .where(ImportLog.undone_at.is_not(None))
        .where(ImportLog.batch_id.is_not(None))
    )
    batch_ids = list(db.session.scalars(stmt))

    total_tasks = 0
    total_goals = 0
    for bid in batch_ids:
        # Bypass the confirmation check since we already validated it.
        result = purge_batch(bid, _CONFIRMATION_TOKEN)
        total_tasks += result["tasks_purged"]
        total_goals += result["goals_purged"]

    return {
        "batches_purged": len(batch_ids),
        "tasks_purged": total_tasks,
        "goals_purged": total_goals,
    }
