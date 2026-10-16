"""#465: Import Undo takes the open subtasks you added to an imported task.

Spec: docs/design/465-undo-takes-subtasks.md. ``undo_batch`` used to set
only the batch's own rows DELETED, so a subtask added to an imported task
later stayed ACTIVE under a deleted parent, and Restore knew nothing about
it. Since #433 every other delete takes open subtasks along
(``deleted_with_parent``); an import undo now does the same, records them
in the snapshot, Restore brings them back, and Purge removes them with
the batch.
"""
from __future__ import annotations

import uuid

import recycle_service
from models import ImportLog, Task, TaskStatus, TaskType, Tier, db


def _batch():
    batch_id = uuid.uuid4()
    db.session.add(ImportLog(source="t", task_count=1, batch_id=batch_id))
    db.session.commit()
    return batch_id


def _task(*, batch_id=None, parent=None, status=TaskStatus.ACTIVE, title="t") -> Task:
    t = Task(title=title, type=TaskType.WORK, tier=Tier.INBOX, status=status,
             batch_id=batch_id, parent_id=parent.id if parent else None)
    db.session.add(t)
    db.session.commit()
    return t


def _get(task_id) -> Task:
    t = db.session.get(Task, task_id)
    db.session.refresh(t)
    return t


def _snapshot(batch_id) -> dict:
    log = db.session.scalar(db.select(ImportLog).where(ImportLog.batch_id == batch_id))
    db.session.refresh(log)
    return log.undo_snapshot


def test_undo_takes_open_subtasks_along(app):
    bid = _batch()
    parent = _task(batch_id=bid)
    sub = _task(parent=parent, title="added later")
    recycle_service.undo_batch(bid)
    got = _get(sub.id)
    assert got.status == TaskStatus.DELETED
    assert got.deleted_with_parent is True
    assert got.batch_id is None          # still not a batch row
    assert _snapshot(bid)["subtasks"] == [str(sub.id)]


def test_done_and_cancelled_subtasks_stay_where_they_are(app):
    """Same rule as #433's _soft_delete: only OPEN subtasks go along."""
    bid = _batch()
    parent = _task(batch_id=bid)
    done = _task(parent=parent, status=TaskStatus.ARCHIVED)
    dropped = _task(parent=parent, status=TaskStatus.CANCELLED)
    recycle_service.undo_batch(bid)
    assert _get(done.id).status == TaskStatus.ARCHIVED
    assert _get(dropped.id).status == TaskStatus.CANCELLED
    assert _snapshot(bid)["subtasks"] == []


def test_a_subtask_already_in_the_bin_on_its_own_is_left_alone(app):
    bid = _batch()
    parent = _task(batch_id=bid)
    binned = _task(parent=parent, status=TaskStatus.DELETED)
    recycle_service.undo_batch(bid)
    recycle_service.restore_batch(bid)
    got = _get(binned.id)
    assert got.status == TaskStatus.DELETED
    assert got.deleted_with_parent is False


def test_restore_brings_the_subtasks_back(app):
    bid = _batch()
    parent = _task(batch_id=bid)
    sub = _task(parent=parent)
    recycle_service.undo_batch(bid)
    result = recycle_service.restore_batch(bid)
    assert _get(parent.id).status == TaskStatus.ACTIVE
    got = _get(sub.id)
    assert got.status == TaskStatus.ACTIVE
    assert got.deleted_with_parent is False
    assert result["subtasks_restored"] == 1


def test_restore_leaves_a_subtask_restored_by_hand(app):
    """Restored from elsewhere while the batch sat in the bin: not DELETED
    any more, so the batch restore doesn't touch it."""
    bid = _batch()
    parent = _task(batch_id=bid)
    sub = _task(parent=parent)
    recycle_service.undo_batch(bid)
    t = _get(sub.id)
    t.status = TaskStatus.ARCHIVED
    t.deleted_with_parent = False
    db.session.commit()
    result = recycle_service.restore_batch(bid)
    assert _get(sub.id).status == TaskStatus.ARCHIVED
    assert result["subtasks_restored"] == 0


def test_a_subtask_whose_parent_stays_in_the_bin_stays_too(app):
    """A parent the snapshot can't restore (corrupt entry) keeps its
    subtasks with it rather than leaving them active under a deleted task."""
    bid = _batch()
    parent = _task(batch_id=bid)
    sub = _task(parent=parent)
    recycle_service.undo_batch(bid)
    log = db.session.scalar(db.select(ImportLog).where(ImportLog.batch_id == bid))
    snap = dict(log.undo_snapshot)
    snap["tasks"] = {str(parent.id): "nonsense"}
    log.undo_snapshot = snap
    db.session.commit()
    recycle_service.restore_batch(bid)
    assert _get(parent.id).status == TaskStatus.DELETED
    assert _get(sub.id).status == TaskStatus.DELETED


def test_purge_removes_the_subtasks_with_the_batch(app):
    bid = _batch()
    parent = _task(batch_id=bid)
    sub = _task(parent=parent)
    keep = _task(parent=parent, status=TaskStatus.ARCHIVED)
    recycle_service.undo_batch(bid)
    result = recycle_service.purge_batch(bid, recycle_service._CONFIRMATION_TOKEN)
    assert db.session.get(Task, parent.id) is None
    assert db.session.get(Task, sub.id) is None
    # A done subtask never went to the bin; it outlives its parent.
    assert _get(keep.id).status == TaskStatus.ARCHIVED
    assert result["subtasks_purged"] == 1


def test_a_batch_without_added_subtasks_is_unchanged(app):
    """The quiet case: nothing extra recorded, counted or touched."""
    bid = _batch()
    parent = _task(batch_id=bid)
    other = _task(title="unrelated")
    result = recycle_service.undo_batch(bid)
    assert _snapshot(bid)["subtasks"] == []
    assert result["subtasks_removed"] == 0
    assert _get(other.id).status == TaskStatus.ACTIVE
    recycle_service.restore_batch(bid)
    assert _get(parent.id).status == TaskStatus.ACTIVE


def test_a_batch_subtask_is_handled_as_a_batch_row(app):
    """An imported subtask of an imported parent is in the batch already —
    it is not listed twice."""
    bid = _batch()
    parent = _task(batch_id=bid)
    sub = _task(batch_id=bid, parent=parent)
    recycle_service.undo_batch(bid)
    snap = _snapshot(bid)
    assert snap["subtasks"] == []
    assert str(sub.id) in snap["tasks"]
    recycle_service.restore_batch(bid)
    assert _get(sub.id).status == TaskStatus.ACTIVE


def test_an_undone_subtask_is_not_listed_on_its_own_in_the_bin(app):
    """deleted_with_parent keeps it out of the Deleted tasks list and count,
    like a #433 parent delete."""
    bid = _batch()
    parent = _task(batch_id=bid)
    _task(parent=parent)
    before = recycle_service.bin_summary()
    recycle_service.undo_batch(bid)
    after = recycle_service.bin_summary()
    assert after.get("deleted_task_count", 0) == before.get("deleted_task_count", 0)
