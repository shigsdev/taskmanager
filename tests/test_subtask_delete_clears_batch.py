"""#480: a subtask deleted by a status change lands in the Recycle Bin.

Every delete is meant to run through ``task_service._soft_delete``, which
clears ``batch_id`` — the bin's Deleted tasks list hides rows that still
carry one (they belong to an undone import shown above), and a later
Restore of the import would otherwise bring the task back. A PATCH
``status: "deleted"`` on a SUBTASK (the bulk toolbar's Delete, or any
update) skipped it: ``_apply_status_to_subtasks`` returned early for a
subtask before its DELETED branch, so an imported subtask kept its
``batch_id`` and was never listed.
"""
from __future__ import annotations

import uuid

from models import ImportLog, Task, TaskStatus, TaskType, Tier, db


def _imported_family():
    """An imported parent and subtask sharing one live import batch."""
    batch = uuid.uuid4()
    db.session.add(ImportLog(source="tasks_import", task_count=2, batch_id=batch))
    parent = Task(title="480 parent", type=TaskType.WORK, tier=Tier.TODAY, batch_id=batch)
    db.session.add(parent)
    db.session.flush()
    sub = Task(title="480 sub", type=TaskType.WORK, tier=Tier.TODAY,
               parent_id=parent.id, batch_id=batch)
    db.session.add(sub)
    db.session.commit()
    return batch, parent, sub


def _row(task_id) -> Task:
    db.session.expire_all()
    return db.session.get(Task, task_id)


def _deleted_listed(client) -> set[str]:
    """What the bin's Deleted tasks section draws from: deleted rows with
    no batch_id (recycle_bin_helpers.binDeletedTasks hides the rest)."""
    rows = client.get("/api/tasks?status=deleted").get_json()
    return {r["id"] for r in rows if not r.get("batch_id")}


def test_bulk_delete_of_an_imported_subtask_lists_it_in_the_bin(app, authed_client):
    with app.app_context():
        _, parent, sub = _imported_family()
        resp = authed_client.patch("/api/tasks/bulk", json={
            "task_ids": [str(sub.id)], "updates": {"status": "deleted"},
        })
        assert resp.get_json()["updated"] == 1
        row = _row(sub.id)
        assert row.status == TaskStatus.DELETED
        assert row.batch_id is None
        assert row.deleted_with_parent is False
        assert str(sub.id) in _deleted_listed(authed_client)
        assert _row(parent.id).status == TaskStatus.ACTIVE   # the parent is untouched


def test_single_patch_delete_of_an_imported_subtask_clears_its_batch(app, authed_client):
    with app.app_context():
        _, _, sub = _imported_family()
        resp = authed_client.patch(f"/api/tasks/{sub.id}", json={"status": "deleted"})
        assert resp.status_code == 200
        assert _row(sub.id).batch_id is None
        assert str(sub.id) in _deleted_listed(authed_client)


def test_restoring_the_import_batch_leaves_a_subtask_you_deleted(app, authed_client):
    # Why batch_id must go: an Undo + Restore of the import must not bring
    # back a subtask you binned yourself.
    import recycle_service

    with app.app_context():
        batch, parent, sub = _imported_family()
        authed_client.patch("/api/tasks/bulk", json={
            "task_ids": [str(sub.id)], "updates": {"status": "deleted"},
        })
        recycle_service.undo_batch(batch)
        recycle_service.restore_batch(batch)
        assert _row(parent.id).status == TaskStatus.ACTIVE
        assert _row(sub.id).status == TaskStatus.DELETED


def test_bulk_delete_of_a_parent_still_takes_its_subtasks(app, authed_client):
    # The quiet case (#433): unchanged.
    with app.app_context():
        _, parent, sub = _imported_family()
        authed_client.patch("/api/tasks/bulk", json={
            "task_ids": [str(parent.id)], "updates": {"status": "deleted"},
        })
        p, s = _row(parent.id), _row(sub.id)
        assert p.status == s.status == TaskStatus.DELETED
        assert p.batch_id is None and s.batch_id is None
        assert s.deleted_with_parent is True
