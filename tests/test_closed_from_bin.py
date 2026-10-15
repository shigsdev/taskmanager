"""#474 — completing or cancelling a task in the Recycle Bin brought it back.

A deleted task can't go straight to completed or cancelled: every path that
sets those statuses refuses with a clear 422 and leaves it (and the subtasks
that went to the bin with it) where they are. Restore is unchanged.
"""
from __future__ import annotations

import uuid

import voice_action_token
from models import Task, TaskStatus, db

MSG = "This task is in the Recycle Bin — restore it there first."


def _new(authed_client, title):
    return authed_client.post("/api/tasks", json={"title": title, "type": "work"}).get_json()["id"]


def _deleted_task(authed_client, *, with_subtask=False):
    tid = _new(authed_client, "Binned")
    sid = None
    if with_subtask:
        sid = authed_client.post("/api/tasks", json={
            "title": "Binned child", "type": "work", "parent_id": tid,
        }).get_json()["id"]
    r = authed_client.delete(f"/api/tasks/{tid}")
    assert r.status_code == 204
    return tid, sid


def _status(app, tid):
    with app.app_context():
        return db.session.get(Task, uuid.UUID(tid)).status


class TestBinnedTaskStaysBinned:
    def test_complete_refused(self, authed_client, app):
        tid, sid = _deleted_task(authed_client, with_subtask=True)
        r = authed_client.post(f"/api/tasks/{tid}/complete", json={"complete_subtasks": True})
        assert r.status_code == 422
        assert r.get_json()["error"] == MSG
        assert _status(app, tid) == TaskStatus.DELETED
        assert _status(app, sid) == TaskStatus.DELETED

    def test_cancel_refused(self, authed_client, app):
        tid, _ = _deleted_task(authed_client)
        r = authed_client.post(f"/api/tasks/{tid}/cancel", json={"cancellation_reason": "x"})
        assert r.status_code == 422
        assert r.get_json()["error"] == MSG
        assert _status(app, tid) == TaskStatus.DELETED

    def test_patch_to_completed_or_cancelled_refused(self, authed_client, app):
        tid, _ = _deleted_task(authed_client)
        for status in ("archived", "cancelled"):
            r = authed_client.patch(f"/api/tasks/{tid}", json={"status": status})
            assert r.status_code == 422, status
            assert r.get_json()["error"] == MSG
            assert _status(app, tid) == TaskStatus.DELETED

    def test_bulk_reports_the_row(self, authed_client, app):
        tid, _ = _deleted_task(authed_client)
        live = _new(authed_client, "Live")
        r = authed_client.patch("/api/tasks/bulk", json={
            "task_ids": [tid, live], "updates": {"status": "archived"},
        })
        body = r.get_json()
        assert body["updated"] == 1
        assert body["errors"] == [{"id": tid, "field": "status", "message": MSG}]
        assert _status(app, tid) == TaskStatus.DELETED
        assert _status(app, live) == TaskStatus.ARCHIVED

    def test_voice_shortcut_refused(self, authed_client, client, app):
        tid, _ = _deleted_task(authed_client)
        token = voice_action_token.mint(secret_key="test-secret", email="me@example.com", days=90)
        hdr = {"Authorization": f"Bearer {token}"}
        for action in ("complete", "cancel"):
            r = client.post(f"/api/voice-review/{tid}/{action}", headers=hdr)
            assert r.status_code == 422, action
            assert r.get_json()["error"] == MSG
        assert _status(app, tid) == TaskStatus.DELETED


class TestEverythingElseStillWorks:
    def test_restore_brings_it_back_with_its_subtask(self, authed_client, app):
        tid, sid = _deleted_task(authed_client, with_subtask=True)
        r = authed_client.patch(f"/api/tasks/{tid}", json={"status": "active"})
        assert r.status_code == 200
        assert _status(app, tid) == TaskStatus.ACTIVE
        assert _status(app, sid) == TaskStatus.ACTIVE

    def test_complete_active_and_already_completed(self, authed_client, app):
        tid = _new(authed_client, "Do it")
        assert authed_client.post(f"/api/tasks/{tid}/complete").status_code == 200
        assert authed_client.post(f"/api/tasks/{tid}/complete").status_code == 200
        assert _status(app, tid) == TaskStatus.ARCHIVED
        # A completed task can still be cancelled (and re-opened) as before.
        assert authed_client.post(f"/api/tasks/{tid}/cancel").status_code == 200
        assert _status(app, tid) == TaskStatus.CANCELLED

    def test_deleting_a_completed_task_still_works(self, authed_client, app):
        tid = _new(authed_client, "Done one")
        authed_client.post(f"/api/tasks/{tid}/complete")
        r = authed_client.patch(f"/api/tasks/{tid}", json={"status": "deleted"})
        assert r.status_code == 200
        assert _status(app, tid) == TaskStatus.DELETED

    def test_editing_a_binned_task_title_is_unchanged(self, authed_client, app):
        tid, _ = _deleted_task(authed_client)
        r = authed_client.patch(f"/api/tasks/{tid}", json={"title": "Renamed in the bin"})
        assert r.status_code == 200
        with app.app_context():
            t = db.session.get(Task, uuid.UUID(tid))
            assert (t.title, t.status) == ("Renamed in the bin", TaskStatus.DELETED)
