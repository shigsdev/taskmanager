"""#494: the words around an import Undo count the subtasks you added.

Since #465 an Undo takes the open subtasks you added to its tasks, and
Restore / Purge bring them back / remove them — but the Undo confirm, the
Recycle Bin row and its Restore / Purge dialogs counted only the batch's
own rows. The server now says how many: ``undo_impact`` → ``subtasks``
(what an Undo would take), ``list_bin`` → ``subtask_count`` (those still
in the bin with their parent — what Restore / Purge act on).
"""
from __future__ import annotations

import uuid

import recycle_service
from models import ImportLog, Task, TaskStatus, TaskType, Tier, db


def _batch():
    batch_id = uuid.uuid4()
    db.session.add(ImportLog(source="t494", task_count=1, batch_id=batch_id))
    db.session.commit()
    return batch_id


def _task(*, batch_id=None, parent=None, status=TaskStatus.ACTIVE, title="t") -> Task:
    t = Task(title=title, type=TaskType.WORK, tier=Tier.INBOX, status=status,
             batch_id=batch_id, parent_id=parent.id if parent else None)
    db.session.add(t)
    db.session.commit()
    return t


def _entry(batch_id) -> dict:
    return next(e for e in recycle_service.list_bin() if e["batch_id"] == str(batch_id))


def test_impact_counts_the_open_subtasks_an_undo_would_take(app):
    bid = _batch()
    parent = _task(batch_id=bid)
    _task(parent=parent, title="added 1")
    _task(parent=parent, title="added 2")
    _task(parent=parent, title="done one", status=TaskStatus.ARCHIVED)  # stays put
    assert recycle_service.undo_impact(bid)["subtasks"] == 2


def test_the_bin_row_counts_them_and_restore_takes_them_off(app):
    bid = _batch()
    parent = _task(batch_id=bid)
    _task(parent=parent, title="added")
    recycle_service.undo_batch(bid)
    assert _entry(bid)["subtask_count"] == 1
    recycle_service.restore_batch(bid)
    assert all(e["batch_id"] != str(bid) for e in recycle_service.list_bin())


def test_one_restored_on_its_own_no_longer_counts(app):
    bid = _batch()
    parent = _task(batch_id=bid)
    sub = _task(parent=parent, title="added")
    recycle_service.undo_batch(bid)
    got = db.session.get(Task, sub.id)
    got.status = TaskStatus.ACTIVE
    got.deleted_with_parent = False
    db.session.commit()
    assert _entry(bid)["subtask_count"] == 0


def test_a_batch_with_no_added_subtasks_counts_none(app):
    # The quiet case.
    bid = _batch()
    _task(batch_id=bid)
    assert recycle_service.undo_impact(bid)["subtasks"] == 0
    recycle_service.undo_batch(bid)
    assert _entry(bid)["subtask_count"] == 0


def test_the_api_carries_both(app, authed_client):
    with app.app_context():
        bid = _batch()
        parent = _task(batch_id=bid)
        _task(parent=parent, title="added")
    r = authed_client.get(f"/api/recycle-bin/impact/{bid}")
    assert r.status_code == 200 and r.get_json()["subtasks"] == 1
    assert authed_client.post(f"/api/recycle-bin/undo/{bid}").status_code == 200
    rows = authed_client.get("/api/recycle-bin").get_json()
    rows = rows if isinstance(rows, list) else rows.get("batches", rows)
    row = next(e for e in rows if e["batch_id"] == str(bid))
    assert row["subtask_count"] == 1
