"""#493: a new subtask goes only under an ACTIVE parent.

`create_task` and `update_task` checked that the parent exists and isn't
itself a subtask, not its status: `POST /api/tasks {parent_id: <a task in
the Recycle Bin>}` made an active subtask under a deleted parent. User
decision 2026-10-16: active parents only — completed, cancelled and
deleted parents are refused with a reason. A subtask that already sits
under a closed parent (a repeating task's subtasks stay open when it
closes) still saves with that parent unchanged.
"""
from __future__ import annotations

import uuid

import pytest

from models import Task, TaskStatus, db


def _task(client, title, **extra):
    r = client.post("/api/tasks", json={"title": title, "type": "work", **extra})
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id"]


def _close(app, task_id, status):
    with app.app_context():
        t = db.session.get(Task, uuid.UUID(task_id))
        t.status = status
        db.session.commit()


REASONS = {
    TaskStatus.ARCHIVED: "That task is completed — re-open it first.",
    TaskStatus.CANCELLED: "That task is cancelled — re-open it first.",
    TaskStatus.DELETED: "That task is in the Recycle Bin — restore it there first.",
}


class TestCreateUnderAParent:
    @pytest.mark.parametrize("status", list(REASONS))
    def test_a_closed_parent_is_refused_with_its_reason(self, app, authed_client, status):
        parent = _task(authed_client, "S493 parent")
        _close(app, parent, status)
        r = authed_client.post("/api/tasks", json={
            "title": "S493 child", "type": "work", "parent_id": parent})
        assert r.status_code == 422
        assert r.get_json()["error"] == REASONS[status]
        with app.app_context():
            assert not Task.query.filter_by(title="S493 child").first()

    def test_an_active_parent_still_takes_a_subtask(self, app, authed_client):
        # The quiet case.
        parent = _task(authed_client, "S493 open parent")
        child = _task(authed_client, "S493 open child", parent_id=parent)
        with app.app_context():
            assert str(db.session.get(Task, uuid.UUID(child)).parent_id) == parent


class TestMoveUnderAParent:
    @pytest.mark.parametrize("status", list(REASONS))
    def test_reparenting_onto_a_closed_task_is_refused(self, app, authed_client, status):
        parent = _task(authed_client, "S493 closed target")
        _close(app, parent, status)
        loose = _task(authed_client, "S493 loose")
        r = authed_client.patch(f"/api/tasks/{loose}", json={"parent_id": parent})
        assert r.status_code == 422
        assert r.get_json()["error"] == REASONS[status]

    def test_an_existing_subtask_of_a_closed_parent_still_saves(self, app, authed_client):
        # The panel sends parent_id on every Save. A repeating task's
        # subtasks stay open when it closes, so this one must keep saving.
        parent = _task(authed_client, "S493 closed weekly")
        child = _task(authed_client, "S493 still open", parent_id=parent)
        _close(app, parent, TaskStatus.ARCHIVED)
        r = authed_client.patch(f"/api/tasks/{child}", json={
            "parent_id": parent, "title": "S493 still open, renamed"})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["title"] == "S493 still open, renamed"

    def test_clearing_the_parent_is_always_fine(self, app, authed_client):
        parent = _task(authed_client, "S493 closed parent 2")
        child = _task(authed_client, "S493 child 2", parent_id=parent)
        _close(app, parent, TaskStatus.DELETED)
        r = authed_client.patch(f"/api/tasks/{child}", json={"parent_id": None})
        assert r.status_code == 200, r.get_json()
