"""#367: recycle-bin Restore returns every row to its state before the undo.

Spec: docs/design/367-restore-returns-rows-to-pre-undo-state.md. Undo
records what it changes in ``ImportLog.undo_snapshot``; Restore reverses
exactly those rows, so a completed task comes back completed and a
project or goal the user had already archived stays archived. Restore
never touches a batch row that isn't in the snapshot.
"""
from __future__ import annotations

import logging
import uuid

import recycle_service
from goal_service import update_goal
from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    ImportLog,
    Project,
    RecurringFrequency,
    RecurringTask,
    Task,
    TaskStatus,
    TaskType,
    Tier,
    db,
)
from project_service import update_project


def _batch():
    batch_id = uuid.uuid4()
    log = ImportLog(source="t", task_count=1, batch_id=batch_id)
    db.session.add(log)
    db.session.commit()
    return batch_id, log


def _task(batch_id, status=TaskStatus.ACTIVE, title="t") -> Task:
    t = Task(title=title, type=TaskType.WORK, tier=Tier.INBOX,
             status=status, batch_id=batch_id)
    db.session.add(t)
    db.session.commit()
    return t


def _goal(batch_id, *, active: bool = True) -> Goal:
    g = Goal(title="g", category=GoalCategory.WORK, priority=GoalPriority.SHOULD,
             batch_id=batch_id, is_active=active)
    db.session.add(g)
    db.session.commit()
    return g


def _project(batch_id, *, active: bool = True) -> Project:
    p = Project(name="p", batch_id=batch_id, is_active=active)
    db.session.add(p)
    db.session.commit()
    return p


def _log(batch_id) -> ImportLog:
    log = db.session.scalar(db.select(ImportLog).where(ImportLog.batch_id == batch_id))
    db.session.refresh(log)
    return log


def _status(task_id) -> TaskStatus:
    t = db.session.get(Task, task_id)
    db.session.refresh(t)
    return t.status


def _active(model, row_id) -> bool:
    row = db.session.get(model, row_id)
    db.session.refresh(row)
    return row.is_active


def _template(*, project=None, goal=None) -> RecurringTask:
    rt = RecurringTask(title="routine", frequency=RecurringFrequency.DAILY,
                       type=TaskType.WORK,
                       project_id=project.id if project else None,
                       goal_id=goal.id if goal else None)
    db.session.add(rt)
    db.session.commit()
    return rt


def _rt(rt_id) -> tuple[bool, bool, bool]:
    rt = db.session.get(RecurringTask, rt_id)
    db.session.refresh(rt)
    return rt.is_active, rt.paused_by_project_archive, rt.paused_by_goal_archive


def test_import_log_has_nullable_undo_snapshot(app):
    with app.app_context():
        bid, log = _batch()
        assert _log(bid).undo_snapshot is None
        log.undo_snapshot = {"v": 1, "tasks": {}, "goals": [], "projects": []}
        db.session.commit()
        assert _log(bid).undo_snapshot["v"] == 1


# --- tasks --------------------------------------------------------------------


def test_completed_task_comes_back_completed(app):
    with app.app_context():
        bid, _ = _batch()
        tid = _task(bid, TaskStatus.ARCHIVED).id

        recycle_service.undo_batch(bid)
        assert _status(tid) == TaskStatus.DELETED

        result = recycle_service.restore_batch(bid)
        assert _status(tid) == TaskStatus.ARCHIVED
        assert result["tasks_restored"] == 1


def test_active_task_round_trip_and_cancelled_untouched(app):
    with app.app_context():
        bid, _ = _batch()
        a = _task(bid).id
        c = _task(bid, TaskStatus.CANCELLED).id

        recycle_service.undo_batch(bid)
        assert _status(c) == TaskStatus.CANCELLED
        result = recycle_service.restore_batch(bid)

        assert _status(a) == TaskStatus.ACTIVE
        assert _status(c) == TaskStatus.CANCELLED
        assert result["tasks_restored"] == 1


def test_snapshot_records_exactly_what_undo_changed(app):
    with app.app_context():
        bid, _ = _batch()
        a = _task(bid).id
        b = _task(bid, TaskStatus.ARCHIVED).id
        _task(bid, TaskStatus.CANCELLED)
        g_on = _goal(bid).id
        _goal(bid, active=False)
        p_on = _project(bid).id
        _project(bid, active=False)

        recycle_service.undo_batch(bid)

        assert _log(bid).undo_snapshot == {
            "v": 1,
            "tasks": {str(a): "active", str(b): "archived"},
            "goals": [str(g_on)],
            "projects": [str(p_on)],
        }


# --- goals and projects -------------------------------------------------------


def test_project_archived_before_undo_stays_archived(app):
    with app.app_context():
        bid, _ = _batch()
        p = _project(bid)
        rt_id = _template(project=p).id
        update_project(p.id, {"is_active": False})
        assert _rt(rt_id) == (False, True, False)

        recycle_service.undo_batch(bid)
        result = recycle_service.restore_batch(bid)

        assert _active(Project, p.id) is False
        assert _rt(rt_id) == (False, True, False)
        assert result["projects_restored"] == 0


def test_goal_archived_by_patch_before_undo_stays_archived(app):
    # update_goal (the PATCH / reflection path) keeps batch_id, unlike
    # the Archive button's delete_goal, so the goal is still in the batch.
    with app.app_context():
        bid, _ = _batch()
        g = _goal(bid)
        rt_id = _template(goal=g).id
        update_goal(g.id, {"is_active": False})
        assert _rt(rt_id) == (False, False, True)

        recycle_service.undo_batch(bid)
        result = recycle_service.restore_batch(bid)

        assert _active(Goal, g.id) is False
        assert _rt(rt_id) == (False, False, True)
        assert result["goals_restored"] == 0


def test_active_project_and_goal_restore_and_resume_templates(app):
    with app.app_context():
        bid, _ = _batch()
        p, g = _project(bid), _goal(bid)
        rp, rg = _template(project=p).id, _template(goal=g).id

        recycle_service.undo_batch(bid)
        assert _rt(rp)[0] is False and _rt(rg)[0] is False

        result = recycle_service.restore_batch(bid)
        assert _active(Project, p.id) and _active(Goal, g.id)
        assert _rt(rp) == (True, False, False)
        assert _rt(rg) == (True, False, False)
        assert (result["projects_restored"], result["goals_restored"]) == (1, 1)


# --- snapshot lifecycle -------------------------------------------------------


def test_restore_and_purge_clear_the_snapshot(app):
    with app.app_context():
        bid, _ = _batch()
        _task(bid)
        recycle_service.undo_batch(bid)
        recycle_service.restore_batch(bid)
        assert _log(bid).undo_snapshot is None

        recycle_service.undo_batch(bid)
        log_id = _log(bid).id
        recycle_service.purge_batch(bid, "DELETE")
        log = db.session.get(ImportLog, log_id)
        db.session.refresh(log)
        assert log.undo_snapshot is None

        bid3, _ = _batch()
        _task(bid3)
        recycle_service.undo_batch(bid3)
        log3_id = _log(bid3).id
        recycle_service.empty_bin("DELETE")
        log3 = db.session.get(ImportLog, log3_id)
        db.session.refresh(log3)
        assert log3.undo_snapshot is None


def test_second_round_trip_uses_a_fresh_snapshot(app):
    # Review Focus 1: the second undo must record the task's NEW state.
    with app.app_context():
        bid, _ = _batch()
        tid = _task(bid).id
        recycle_service.undo_batch(bid)
        recycle_service.restore_batch(bid)

        t = db.session.get(Task, tid)
        t.status = TaskStatus.ARCHIVED
        db.session.commit()

        recycle_service.undo_batch(bid)
        recycle_service.restore_batch(bid)
        assert _status(tid) == TaskStatus.ARCHIVED


def test_restore_skips_goal_unarchived_by_hand_in_the_bin(app):
    # Review Focus 2: the user brought it back already; restore must not
    # count it or run the unarchive cascade a second time.
    with app.app_context():
        bid, _ = _batch()
        g = _goal(bid)
        rt_id = _template(goal=g).id
        recycle_service.undo_batch(bid)
        update_goal(g.id, {"is_active": True})
        assert _rt(rt_id) == (True, False, False)

        result = recycle_service.restore_batch(bid)
        assert result["goals_restored"] == 0
        assert _active(Goal, g.id) is True
        assert _rt(rt_id) == (True, False, False)


def test_null_snapshot_restores_like_before(app):
    # Review Focus 4: a batch undone before #367 has no snapshot. It
    # restores with the old rule (every DELETED task comes back ACTIVE)
    # rather than failing.
    with app.app_context():
        bid, _ = _batch()
        tid = _task(bid, TaskStatus.ARCHIVED).id
        recycle_service.undo_batch(bid)
        log = _log(bid)
        log.undo_snapshot = None
        db.session.commit()

        result = recycle_service.restore_batch(bid)
        assert _status(tid) == TaskStatus.ACTIVE
        assert result["tasks_restored"] == 1


def test_cleared_snapshot_is_sql_null(app):
    # Final review: the spec and model promise NULL. A JSON 'null' would
    # read back as None in Python but slip past an `IS NULL` filter.
    with app.app_context():
        bid, _ = _batch()
        _task(bid)
        recycle_service.undo_batch(bid)
        recycle_service.restore_batch(bid)
        hit = db.session.scalar(
            db.select(ImportLog.id).where(
                ImportLog.batch_id == bid, ImportLog.undo_snapshot.is_(None)))
        assert hit is not None

        recycle_service.undo_batch(bid)
        log_id = _log(bid).id
        recycle_service.purge_batch(bid, "DELETE")
        hit = db.session.scalar(
            db.select(ImportLog.id).where(
                ImportLog.id == log_id, ImportLog.undo_snapshot.is_(None)))
        assert hit is not None


def test_list_bin_restore_goal_count_excludes_goals_restore_leaves(app):
    # Final review: the Restore dialog said "Restore 1 goal" for a goal
    # the user had archived before the undo, which restore now leaves
    # alone. goal_count stays the purge truth (purge deletes it too);
    # restore_goal_count is what Restore will actually bring back.
    with app.app_context():
        bid, _ = _batch()
        _goal(bid)
        _goal(bid, active=False)
        recycle_service.undo_batch(bid)

        entry = next(e for e in recycle_service.list_bin() if e["batch_id"] == str(bid))
        assert entry["goal_count"] == 2
        assert entry["restore_goal_count"] == 1


def test_list_bin_restore_goal_count_legacy_batch_counts_every_inactive_goal(app):
    with app.app_context():
        bid, _ = _batch()
        _goal(bid)
        _goal(bid, active=False)
        recycle_service.undo_batch(bid)
        log = _log(bid)
        log.undo_snapshot = None
        db.session.commit()

        entry = next(e for e in recycle_service.list_bin() if e["batch_id"] == str(bid))
        assert entry["restore_goal_count"] == entry["goal_count"] == 2


def test_unknown_status_in_snapshot_is_skipped(app, caplog):
    # Review Focus 5: one bad entry leaves that task in the bin and
    # restores the rest; the warning never carries the task's title.
    with app.app_context():
        bid, _ = _batch()
        bad = _task(bid, title="Secret plan").id
        good = _task(bid).id
        recycle_service.undo_batch(bid)
        log = _log(bid)
        snap = dict(log.undo_snapshot)
        snap["tasks"] = {**snap["tasks"], str(bad): "bogus"}
        log.undo_snapshot = snap
        db.session.commit()

        with caplog.at_level(logging.WARNING):
            result = recycle_service.restore_batch(bid)

        assert _status(bad) == TaskStatus.DELETED
        assert _status(good) == TaskStatus.ACTIVE
        assert result["tasks_restored"] == 1
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings
        assert all("Secret plan" not in r.getMessage() for r in warnings)
