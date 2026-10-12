"""#433 — closing or deleting a parent no longer strands its open subtasks.

Only POST /complete and /cancel used to handle open subtasks. A plain
PATCH (bulk Mark complete / cancelled, multi-drag to Completed, the Goals
tick box, approved reflection proposals) and every delete left them ACTIVE
under a closed or deleted parent. Now:

- PATCH to archived / cancelled on a parent with open subtasks is refused
  unless the request says ``close_subtasks: true``; a repeating task keeps
  its subtasks open (#230).
- Delete takes the open subtasks to the Recycle Bin, marked
  ``deleted_with_parent``; restoring the parent brings exactly those back.

Spec: docs/design/433-subtasks-close-with-parent.md.
"""
from __future__ import annotations

from datetime import date

from models import (
    RecurringTask,
    Task,
    TaskStatus,
    TaskType,
    Tier,
    db,
)


def _task(**overrides) -> Task:
    fields = {"title": "Seed", "type": TaskType.WORK, "tier": Tier.TODAY}
    fields.update(overrides)
    task = Task(**fields)
    db.session.add(task)
    db.session.commit()
    return task


def _family(n_open: int = 2, *, done: int = 0, cancelled: int = 0, **parent_kw):
    """A parent with `n_open` active subtasks (+ optional closed ones)."""
    parent = _task(title="Parent", **parent_kw)
    subs = [_task(title=f"open {i}", parent_id=parent.id) for i in range(n_open)]
    closed = [
        _task(title=f"done {i}", parent_id=parent.id, status=TaskStatus.ARCHIVED)
        for i in range(done)
    ] + [
        _task(title=f"cancelled {i}", parent_id=parent.id, status=TaskStatus.CANCELLED)
        for i in range(cancelled)
    ]
    return parent, subs, closed


def _status(task_id) -> TaskStatus:
    db.session.expire_all()
    return db.session.get(Task, task_id).status


def _template() -> RecurringTask:
    t = RecurringTask(
        title="Weekly prep", type=TaskType.WORK, frequency="weekly",
        day_of_week=0, start_date=date(2026, 1, 1),
    )
    db.session.add(t)
    db.session.commit()
    return t


class TestCloseGuard:
    def test_patch_complete_on_a_parent_with_open_subtasks_is_refused(self, authed_client):
        parent, subs, _ = _family(2)
        resp = authed_client.patch(f"/api/tasks/{parent.id}", json={"status": "archived"})
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["field"] == "subtasks"
        assert "2 open subtask(s)" in body["error"]
        assert _status(parent.id) == TaskStatus.ACTIVE
        assert all(_status(s.id) == TaskStatus.ACTIVE for s in subs)

    def test_patch_cancel_on_a_parent_with_open_subtasks_is_refused(self, authed_client):
        parent, subs, _ = _family(1)
        resp = authed_client.patch(
            f"/api/tasks/{parent.id}",
            json={"status": "cancelled", "cancellation_reason": "nope"},
        )
        assert resp.status_code == 422
        assert _status(parent.id) == TaskStatus.ACTIVE

    def test_close_subtasks_completes_them_together(self, authed_client):
        parent, subs, closed = _family(2, cancelled=1)
        resp = authed_client.patch(
            f"/api/tasks/{parent.id}",
            json={"status": "archived", "close_subtasks": True},
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "archived"
        assert all(_status(s.id) == TaskStatus.ARCHIVED for s in subs)
        # An already-cancelled subtask keeps its own ending.
        assert _status(closed[0].id) == TaskStatus.CANCELLED

    def test_close_subtasks_cancels_them_together(self, authed_client):
        parent, subs, _ = _family(2)
        resp = authed_client.patch(
            f"/api/tasks/{parent.id}",
            json={"status": "cancelled", "close_subtasks": True,
                  "cancellation_reason": "dropped"},
        )
        assert resp.status_code == 200
        assert all(_status(s.id) == TaskStatus.CANCELLED for s in subs)

    def test_a_parent_whose_subtasks_are_all_closed_completes_freely(self, authed_client):
        parent, _, _ = _family(0, done=2)
        resp = authed_client.patch(f"/api/tasks/{parent.id}", json={"status": "archived"})
        assert resp.status_code == 200

    def test_a_subtask_itself_completes_freely(self, authed_client):
        parent, subs, _ = _family(2)
        resp = authed_client.patch(f"/api/tasks/{subs[0].id}", json={"status": "archived"})
        assert resp.status_code == 200
        assert _status(parent.id) == TaskStatus.ACTIVE
        assert _status(subs[1].id) == TaskStatus.ACTIVE

    def test_a_repeating_parent_closes_and_keeps_its_subtasks_open(self, authed_client):
        # #230: subtasks of a weekly task survive its close-out.
        tmpl = _template()
        parent, subs, _ = _family(2, recurring_task_id=tmpl.id)
        resp = authed_client.patch(f"/api/tasks/{parent.id}", json={"status": "archived"})
        assert resp.status_code == 200
        assert all(_status(s.id) == TaskStatus.ACTIVE for s in subs)
        # Even when asked to close them.
        p2, subs2, _ = _family(1, recurring_task_id=tmpl.id)
        resp = authed_client.patch(
            f"/api/tasks/{p2.id}", json={"status": "archived", "close_subtasks": True},
        )
        assert resp.status_code == 200
        assert _status(subs2[0].id) == TaskStatus.ACTIVE

    def test_close_subtasks_is_not_an_unknown_field_on_a_plain_task(self, authed_client):
        t = _task()
        resp = authed_client.patch(
            f"/api/tasks/{t.id}", json={"status": "archived", "close_subtasks": True},
        )
        assert resp.status_code == 200


class TestBulkClose:
    def test_bulk_complete_without_the_flag_refuses_only_the_parent(self, authed_client):
        parent, subs, _ = _family(2)
        plain = _task(title="plain")
        resp = authed_client.patch("/api/tasks/bulk", json={
            "task_ids": [str(parent.id), str(plain.id)],
            "updates": {"status": "archived"},
        })
        body = resp.get_json()
        assert body["updated"] == 1
        assert [e["id"] for e in body["errors"]] == [str(parent.id)]
        assert body["errors"][0]["field"] == "subtasks"
        assert _status(plain.id) == TaskStatus.ARCHIVED
        assert _status(parent.id) == TaskStatus.ACTIVE
        assert all(_status(s.id) == TaskStatus.ACTIVE for s in subs)

    def test_bulk_complete_with_the_flag_closes_the_subtasks(self, authed_client):
        parent, subs, _ = _family(2)
        plain = _task(title="plain")
        resp = authed_client.patch("/api/tasks/bulk", json={
            "task_ids": [str(parent.id), str(plain.id)],
            "updates": {"status": "archived", "close_subtasks": True},
        })
        assert resp.get_json() == {"updated": 2, "not_found": [], "errors": []}
        assert all(_status(s.id) == TaskStatus.ARCHIVED for s in subs)

    def test_bulk_selection_holding_a_parent_and_its_subtask(self, authed_client):
        parent, subs, _ = _family(2)
        resp = authed_client.patch("/api/tasks/bulk", json={
            "task_ids": [str(subs[0].id), str(parent.id)],
            "updates": {"status": "cancelled", "close_subtasks": True},
        })
        assert resp.get_json()["updated"] == 2
        assert all(_status(s.id) == TaskStatus.CANCELLED for s in subs)


class TestDeleteTakesSubtasksAlong:
    def test_delete_moves_open_subtasks_to_the_bin_with_the_parent(self, authed_client):
        parent, subs, closed = _family(2, done=1)
        resp = authed_client.delete(f"/api/tasks/{parent.id}")
        assert resp.status_code == 204
        db.session.expire_all()
        for s in subs:
            row = db.session.get(Task, s.id)
            assert row.status == TaskStatus.DELETED
            assert row.deleted_with_parent is True
        done = db.session.get(Task, closed[0].id)
        assert done.status == TaskStatus.ARCHIVED
        assert done.deleted_with_parent is False
        assert db.session.get(Task, parent.id).deleted_with_parent is False

    def test_a_repeating_parent_takes_its_subtasks_along_too(self, authed_client):
        tmpl = _template()
        parent, subs, _ = _family(1, recurring_task_id=tmpl.id)
        authed_client.delete(f"/api/tasks/{parent.id}")
        assert _status(subs[0].id) == TaskStatus.DELETED

    def test_patch_status_deleted_takes_them_along_too(self, authed_client):
        parent, subs, _ = _family(1)
        resp = authed_client.patch(f"/api/tasks/{parent.id}", json={"status": "deleted"})
        assert resp.status_code == 200
        db.session.expire_all()
        assert db.session.get(Task, subs[0].id).deleted_with_parent is True

    def test_review_delete_takes_them_along(self, app):
        from review_service import review_task
        parent, subs, _ = _family(2)
        review_task(db.session.get(Task, parent.id), "delete")
        db.session.expire_all()
        assert all(
            db.session.get(Task, s.id).status == TaskStatus.DELETED
            and db.session.get(Task, s.id).deleted_with_parent
            for s in subs
        )

    def test_deleting_a_subtask_alone_is_not_marked(self, authed_client):
        parent, subs, _ = _family(1)
        authed_client.delete(f"/api/tasks/{subs[0].id}")
        db.session.expire_all()
        row = db.session.get(Task, subs[0].id)
        assert row.status == TaskStatus.DELETED
        assert row.deleted_with_parent is False
        assert _status(parent.id) == TaskStatus.ACTIVE


class TestRestoreBringsThemBack:
    def test_restore_returns_exactly_the_subtasks_deleted_with_it(self, authed_client):
        parent, subs, _ = _family(2)
        alone = _task(title="deleted on its own", parent_id=parent.id)
        authed_client.delete(f"/api/tasks/{alone.id}")
        authed_client.delete(f"/api/tasks/{parent.id}")

        resp = authed_client.patch(f"/api/tasks/{parent.id}", json={"status": "active"})
        assert resp.status_code == 200
        db.session.expire_all()
        for s in subs:
            row = db.session.get(Task, s.id)
            assert row.status == TaskStatus.ACTIVE
            assert row.deleted_with_parent is False
        assert _status(alone.id) == TaskStatus.DELETED
        assert resp.get_json()["subtask_count"] == 2

    def test_completing_a_deleted_parent_brings_nothing_back(self, authed_client):
        # #463's path: only Restore (deleted → active) returns subtasks.
        parent, subs, _ = _family(1)
        authed_client.delete(f"/api/tasks/{parent.id}")
        authed_client.patch(f"/api/tasks/{parent.id}", json={"status": "archived"})
        assert _status(subs[0].id) == TaskStatus.DELETED


class TestSerializerAndBin:
    def test_full_view_exposes_the_new_fields(self, authed_client):
        tmpl = _template()
        parent, subs, _ = _family(1, recurring_task_id=tmpl.id)
        body = authed_client.get(f"/api/tasks/{parent.id}").get_json()
        assert body["recurring_task_id"] == str(tmpl.id)
        assert body["deleted_with_parent"] is False

    def test_deleted_list_marks_the_subtasks_that_went_along(self, authed_client):
        parent, subs, _ = _family(2)
        authed_client.delete(f"/api/tasks/{parent.id}")
        rows = authed_client.get("/api/tasks?status=deleted").get_json()
        by_id = {r["id"]: r for r in rows}
        assert by_id[str(parent.id)]["deleted_with_parent"] is False
        assert all(by_id[str(s.id)]["deleted_with_parent"] for s in subs)

    def test_bin_count_counts_the_parent_once(self, authed_client):
        parent, _, _ = _family(3)
        authed_client.delete(f"/api/tasks/{parent.id}")
        loner = _task(title="loner")
        authed_client.delete(f"/api/tasks/{loner.id}")
        summary = authed_client.get("/api/recycle-bin/summary").get_json()
        assert summary["deleted_task_count"] == 2
