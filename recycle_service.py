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

Projects and goals follow the archive rule (#356, #368 / ADR-038): undo
and restore archive and unarchive them through
``project_service._set_project_active`` and ``goal_service._set_goal_active``,
the same functions the Archive buttons use.

Restore returns rows to their state before the undo (#367): undo records
what it changes in ``ImportLog.undo_snapshot`` and restore reverses
exactly that, so a completed task comes back completed and a goal or
project the user had already archived stays archived.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import null, select, update

# #356 / #368: private names on purpose, the one writer of each parent's
# is_active. Renaming them public would rewrite #353's ADR, spec and
# docstrings for no behavioral gain.
from goal_service import _set_goal_active
from models import Goal, ImportLog, Project, RecurringTask, Task, TaskStatus, db
from project_service import _set_project_active
from recurring_service import templates_paused_by_archive

logger = logging.getLogger(__name__)

# #367: version of the ImportLog.undo_snapshot shape, in case it changes.
_SNAPSHOT_VERSION = 1

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


def _batch_projects(batch_id: uuid.UUID) -> list[Project]:
    """PR66 audit fix #131: return all projects in a batch.

    Mirrors _batch_tasks / _batch_goals shape — single canonical loader
    consumed by undo / restore / purge / list / summary."""
    return list(
        db.session.scalars(select(Project).where(Project.batch_id == batch_id))
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
    logs = list(db.session.scalars(stmt))
    if not logs:
        return []

    # PR69 perf #5: was 3 COUNTs per batch (3N+1) — N batches in the bin =
    # 3N+1 round-trips. Now: one GROUP BY per table covers all batches
    # at once. Total queries: 1 (logs) + 3 (per-table aggregations) = 4
    # regardless of N.
    batch_ids = [log.batch_id for log in logs]

    task_counts = dict(db.session.execute(
        select(Task.batch_id, db.func.count())
        .where(Task.batch_id.in_(batch_ids))
        .where(Task.status == TaskStatus.DELETED)
        .group_by(Task.batch_id)
    ).all())
    goal_counts = dict(db.session.execute(
        select(Goal.batch_id, db.func.count())
        .where(Goal.batch_id.in_(batch_ids))
        .where(Goal.is_active.is_(False))
        .group_by(Goal.batch_id)
    ).all())
    project_counts = dict(db.session.execute(
        select(Project.batch_id, db.func.count())
        .where(Project.batch_id.in_(batch_ids))
        .where(Project.is_active.is_(False))
        .group_by(Project.batch_id)
    ).all())

    # #367: what Restore will actually bring back. goal_count above stays
    # the purge truth (purge deletes every goal in the batch), but restore
    # only unarchives the goals the undo archived, so a goal the user had
    # archived first isn't counted here. A legacy batch (no snapshot)
    # restores every inactive goal, so it counts them all.
    snapshots = {log.batch_id: log.undo_snapshot for log in logs}
    restore_goal_counts: dict = {}
    for gbid, gid in db.session.execute(
        select(Goal.batch_id, Goal.id)
        .where(Goal.batch_id.in_(batch_ids))
        .where(Goal.is_active.is_(False))
    ).all():
        snap = snapshots.get(gbid)
        if snap is None or str(gid) in (snap.get("goals") or []):
            restore_goal_counts[gbid] = restore_goal_counts.get(gbid, 0) + 1

    entries = []
    for log in logs:
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
                "task_count": task_counts.get(log.batch_id, 0),
                "goal_count": goal_counts.get(log.batch_id, 0),
                "restore_goal_count": restore_goal_counts.get(log.batch_id, 0),
                "project_count": project_counts.get(log.batch_id, 0),
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
    # PR66 audit fix #131
    project_count = (
        db.session.scalar(
            select(db.func.count())
            .select_from(Project)
            .join(
                ImportLog,
                ImportLog.batch_id == Project.batch_id,  # noqa: E711
            )
            .where(
                Project.is_active.is_(False),
                Project.batch_id.is_not(None),
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
        "project_count": project_count,
    }


# --- Undo / Restore / Purge --------------------------------------------------


def undo_batch(batch_id: uuid.UUID) -> dict:
    """Move a batch to the recycle bin (soft-delete all rows)."""
    log = _get_log(batch_id)
    if log.undone_at is not None:
        raise BatchStateError(f"batch {batch_id} is already in the recycle bin")

    tasks = _batch_tasks(batch_id)
    goals = _batch_goals(batch_id)
    projects = _batch_projects(batch_id)

    # #367: record what this undo changes, BEFORE changing it, so restore
    # can put each row back exactly as it was. A row the undo leaves
    # alone (a cancelled task, a goal or project the user had already
    # archived) isn't listed, and restore never touches it.
    snapshot: dict = {
        "v": _SNAPSHOT_VERSION,
        "tasks": {
            str(t.id): t.status.value
            for t in tasks
            if t.status in (TaskStatus.ACTIVE, TaskStatus.ARCHIVED)
        },
        "goals": [str(g.id) for g in goals if g.is_active],
        "projects": [str(p.id) for p in projects if p.is_active],
    }

    for task in tasks:
        if task.status == TaskStatus.ACTIVE or task.status == TaskStatus.ARCHIVED:
            task.status = TaskStatus.DELETED
    # #368: through the same function as the Archive button, so the
    # goal's running repeating templates pause and restore resumes them.
    for goal in goals:
        _set_goal_active(goal, False)
    # PR66 audit fix #131: also soft-delete bulk-imported projects.
    # #356 / ADR-038: exactly as the Archive button does. Task links are
    # KEPT (PR66 used to null Task.project_id here, mirroring PR63 #129;
    # an archived project's id now renders no label, because the readers
    # resolve against active projects only), and the project's running
    # repeating templates pause and are flagged so restore resumes them.
    for project in projects:
        _set_project_active(project, False)

    log.undo_snapshot = snapshot
    log.undone_at = datetime.now(UTC)
    db.session.commit()

    return {
        "batch_id": str(batch_id),
        "tasks_removed": len(tasks),
        "goals_removed": len(goals),
        "projects_removed": len(projects),
    }


def undo_impact(batch_id: uuid.UUID) -> dict:
    """The repeating tasks ``undo_batch`` would pause, without undoing (#369).

    Only the batch's ACTIVE projects and goals count: the undo archives
    them through the transition-guarded ``_set_*_active``, which skips
    one that's already archived. Read-only; same errors as
    ``undo_batch``, so the confirm can't describe a batch the undo
    would refuse.
    """
    log = _get_log(batch_id)
    if log.undone_at is not None:
        raise BatchStateError(f"batch {batch_id} is already in the recycle bin")

    templates = templates_paused_by_archive(
        [p.id for p in _batch_projects(batch_id) if p.is_active],
        [g.id for g in _batch_goals(batch_id) if g.is_active],
    )
    return {
        "batch_id": str(batch_id),
        "paused_templates": [{"id": str(t.id), "title": t.title} for t in templates],
    }


def _restore_from_snapshot(snapshot: dict, tasks, goals, projects) -> tuple[int, int, int]:
    """Reverse exactly what the undo recorded (#367). Returns the counts.

    Walks the batch's own rows and looks each up in the snapshot, never
    the other way round, so an id for a row that's gone is simply never
    seen. Ids are stored as strings (JSON keys), hence ``str(row.id)``.
    """
    task_status = snapshot.get("tasks") or {}
    goal_ids = set(snapshot.get("goals") or [])
    project_ids = set(snapshot.get("projects") or [])

    restored_tasks = 0
    for task in tasks:
        recorded = task_status.get(str(task.id))
        if recorded is None or task.status != TaskStatus.DELETED:
            continue
        try:
            status = TaskStatus(recorded)
        except ValueError:
            status = None
        if status is None or status == TaskStatus.DELETED:
            # A corrupt entry must not sink the whole restore: leave this
            # one in the bin. Id only, never the title.
            logger.warning("recycle restore: bad snapshot status for task %s", task.id)
            continue
        task.status = status
        restored_tasks += 1

    restored_goals = 0
    for goal in goals:
        if str(goal.id) in goal_ids and not goal.is_active:
            _set_goal_active(goal, True)  # #368: resumes its templates
            restored_goals += 1

    # Exactly as Unarchive does (#356 / ADR-038), which resumes the
    # templates the undo paused. Task links come back with the project
    # because undo no longer nulls them.
    restored_projects = 0
    for project in projects:
        if str(project.id) in project_ids and not project.is_active:
            _set_project_active(project, True)
            restored_projects += 1

    return restored_tasks, restored_goals, restored_projects


def _restore_legacy(tasks, goals, projects) -> tuple[int, int, int]:
    """The pre-#367 rule, for a batch undone before snapshots existed.

    It can't know what each row looked like before the undo, so every
    DELETED task comes back ACTIVE and every inactive goal/project is
    unarchived. Batches undone BEFORE #356 also lost their task-project
    links, which nothing recorded; the user re-assigns by hand.
    """
    restored_tasks = 0
    for task in tasks:
        if task.status == TaskStatus.DELETED:
            task.status = TaskStatus.ACTIVE
            restored_tasks += 1

    restored_goals = 0
    for goal in goals:
        if not goal.is_active:
            _set_goal_active(goal, True)
            restored_goals += 1

    restored_projects = 0
    for project in projects:
        if not project.is_active:
            _set_project_active(project, True)
            restored_projects += 1

    return restored_tasks, restored_goals, restored_projects


def restore_batch(batch_id: uuid.UUID) -> dict:
    """Restore a batch from the recycle bin (un-soft-delete).

    #367: driven by the snapshot ``undo_batch`` recorded, so every row the
    undo changed goes back exactly as it was (a completed task comes back
    completed) and a row the undo didn't change is never touched (a
    project or goal the user had already archived stays archived). A row
    the user changed while the batch sat in the bin (a goal unarchived by
    hand) is no longer DELETED / inactive, so it's left alone too.

    A batch undone before #367 has no snapshot and restores with the old
    rule; see ``_restore_legacy``.
    """
    log = _get_log(batch_id)
    if log.undone_at is None:
        raise BatchStateError(f"batch {batch_id} is not in the recycle bin")

    tasks = _batch_tasks(batch_id)
    goals = _batch_goals(batch_id)
    projects = _batch_projects(batch_id)

    if log.undo_snapshot is not None:
        restored_tasks, restored_goals, restored_projects = _restore_from_snapshot(
            log.undo_snapshot, tasks, goals, projects,
        )
    else:
        restored_tasks, restored_goals, restored_projects = _restore_legacy(
            tasks, goals, projects,
        )

    # SQL NULL, not JSON 'null' (the JSON type's default for None), so
    # the column really is NULL as the model promises.
    log.undo_snapshot = null()
    log.undone_at = None
    db.session.commit()

    return {
        "batch_id": str(batch_id),
        "tasks_restored": restored_tasks,
        "goals_restored": restored_goals,
        "projects_restored": restored_projects,
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
    projects = _batch_projects(batch_id)
    goal_ids = [g.id for g in goals]
    project_ids = [p.id for p in projects]

    # Null out any external references to the goals we're about to purge.
    if goal_ids:
        db.session.execute(
            update(Task)
            .where(Task.goal_id.in_(goal_ids))
            .values(goal_id=None)
        )
    # PR66 audit fix #131: same null-out for project FKs. Required
    # because Task.project_id has no ondelete. Since #356 undo KEEPS task
    # links, so tasks (including ones linked by hand outside the batch)
    # normally still point at these projects when purge runs.
    if project_ids:
        db.session.execute(
            update(Task)
            .where(Task.project_id.in_(project_ids))
            .values(project_id=None)
        )

    # #356: a template paused by its project's archive carries
    # paused_by_project_archive, meaning "resume when the project is
    # unarchived". Purge makes that impossible, so the template becomes
    # an ordinary paused one. Its is_active is left alone: it isn't
    # resumed into no project. The DB's ON DELETE SET NULL then clears its
    # project_id when the project row goes.
    if project_ids:
        db.session.execute(
            update(RecurringTask)
            .where(RecurringTask.project_id.in_(project_ids))
            .values(paused_by_project_archive=False)
        )

    # #368: the same for the goal marker. Each purge clears only its own
    # marker, so a template whose project is still archived keeps that
    # one and still comes back when the project does.
    if goal_ids:
        db.session.execute(
            update(RecurringTask)
            .where(RecurringTask.goal_id.in_(goal_ids))
            .values(paused_by_goal_archive=False)
        )

    for task in tasks:
        db.session.delete(task)
    for goal in goals:
        db.session.delete(goal)
    for project in projects:
        db.session.delete(project)

    # Retain the ImportLog row as audit, but disassociate it from the now
    # non-existent rows. #367: the snapshot only lists their ids, so it
    # goes too.
    log.batch_id = None
    log.undo_snapshot = null()
    db.session.commit()

    return {
        "batch_id": str(batch_id),
        "tasks_purged": len(tasks),
        "goals_purged": len(goals),
        "projects_purged": len(projects),
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
    total_projects = 0
    for bid in batch_ids:
        # Bypass the confirmation check since we already validated it.
        result = purge_batch(bid, _CONFIRMATION_TOKEN)
        total_tasks += result["tasks_purged"]
        total_goals += result["goals_purged"]
        total_projects += result.get("projects_purged", 0)

    return {
        "batches_purged": len(batch_ids),
        "tasks_purged": total_tasks,
        "goals_purged": total_goals,
        "projects_purged": total_projects,
    }
