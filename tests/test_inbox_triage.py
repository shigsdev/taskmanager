"""Integration tests for the inbox + triage flow.

These tests verify the full lifecycle: tasks land in inbox by default,
can be moved to other tiers (triaged), and the inbox empties out.
This corresponds to the spec's "Inbox (Default Landing View)" section.

Key terms:
- Triage: the act of reviewing inbox items and deciding where they go
  (Today, This Week, Backlog, or Freezer).
- Tier: one of the five buckets a task can live in (inbox, today,
  this_week, backlog, freezer).
"""
from __future__ import annotations

from models import Task, TaskStatus, TaskType, Tier, db


def _make_task(**overrides) -> Task:
    """Helper to create a task directly in the database for testing."""
    fields = {"title": "Inbox item", "type": TaskType.WORK}
    fields.update(overrides)
    task = Task(**fields)
    db.session.add(task)
    db.session.commit()
    return task


# --- New tasks default to inbox -----------------------------------------------


class TestInboxDefaults:
    """Verify that all new tasks land in the inbox unless told otherwise."""

    def test_task_created_via_api_defaults_to_inbox(self, authed_client):
        resp = authed_client.post(
            "/api/tasks", json={"title": "New thing", "type": "work"}
        )
        assert resp.status_code == 201
        assert resp.get_json()["tier"] == "inbox"

    def test_task_created_with_explicit_tier_skips_inbox(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={"title": "Urgent", "type": "work", "tier": "today"},
        )
        assert resp.status_code == 201
        assert resp.get_json()["tier"] == "today"

    def test_task_model_defaults_to_inbox(self, app):
        with app.app_context():
            task = Task(title="Direct", type=TaskType.WORK)
            db.session.add(task)
            db.session.commit()
            assert task.tier is Tier.INBOX


# --- Triage: moving tasks out of inbox ----------------------------------------


class TestTriageSingleTask:
    """Verify triaging (moving) a single task from inbox to another tier."""

    def test_move_inbox_to_today(self, authed_client, app):
        with app.app_context():
            task = _make_task(title="Triage me", tier=Tier.INBOX)
            task_id = str(task.id)

        # Triage: move from inbox to today
        resp = authed_client.patch(
            f"/api/tasks/{task_id}", json={"tier": "today"}
        )
        assert resp.status_code == 200
        assert resp.get_json()["tier"] == "today"

        # Confirm it's no longer in inbox
        resp = authed_client.get("/api/tasks?tier=inbox")
        inbox_ids = [t["id"] for t in resp.get_json()]
        assert task_id not in inbox_ids

    def test_move_inbox_to_this_week(self, authed_client, app):
        with app.app_context():
            task = _make_task(tier=Tier.INBOX)
            task_id = str(task.id)
        resp = authed_client.patch(
            f"/api/tasks/{task_id}", json={"tier": "this_week"}
        )
        assert resp.get_json()["tier"] == "this_week"

    def test_move_inbox_to_backlog(self, authed_client, app):
        with app.app_context():
            task = _make_task(tier=Tier.INBOX)
            task_id = str(task.id)
        resp = authed_client.patch(
            f"/api/tasks/{task_id}", json={"tier": "backlog"}
        )
        assert resp.get_json()["tier"] == "backlog"

    def test_move_inbox_to_freezer(self, authed_client, app):
        with app.app_context():
            task = _make_task(tier=Tier.INBOX)
            task_id = str(task.id)
        resp = authed_client.patch(
            f"/api/tasks/{task_id}", json={"tier": "freezer"}
        )
        assert resp.get_json()["tier"] == "freezer"


# --- Bulk triage: moving multiple tasks at once --------------------------------


class TestBulkTriage:
    """Verify that multiple inbox tasks can be triaged in batch.

    In the UI, the user checks several inbox items and assigns them
    all to the same tier at once. Under the hood, this sends one
    PATCH request per task (the JS does this in parallel). We test
    the same pattern here.
    """

    def test_bulk_move_three_tasks_to_today(self, authed_client, app):
        with app.app_context():
            t1 = _make_task(title="Bulk 1", tier=Tier.INBOX)
            t2 = _make_task(title="Bulk 2", tier=Tier.INBOX)
            t3 = _make_task(title="Bulk 3", tier=Tier.INBOX)
            ids = [str(t1.id), str(t2.id), str(t3.id)]

        # Move all three to today (simulating bulk triage)
        for task_id in ids:
            resp = authed_client.patch(
                f"/api/tasks/{task_id}", json={"tier": "today"}
            )
            assert resp.status_code == 200

        # Inbox should now be empty
        resp = authed_client.get("/api/tasks?tier=inbox")
        assert resp.get_json() == []

        # Today should have all three
        resp = authed_client.get("/api/tasks?tier=today")
        today_titles = [t["title"] for t in resp.get_json()]
        assert "Bulk 1" in today_titles
        assert "Bulk 2" in today_titles
        assert "Bulk 3" in today_titles

    def test_bulk_triage_to_different_tiers(self, authed_client, app):
        """Each task in a batch can go to a different tier."""
        with app.app_context():
            t1 = _make_task(title="Goes today", tier=Tier.INBOX)
            t2 = _make_task(title="Goes backlog", tier=Tier.INBOX)
            id1, id2 = str(t1.id), str(t2.id)

        authed_client.patch(f"/api/tasks/{id1}", json={"tier": "today"})
        authed_client.patch(f"/api/tasks/{id2}", json={"tier": "backlog"})

        resp = authed_client.get("/api/tasks?tier=inbox")
        assert resp.get_json() == []


# --- Inbox listing and filtering ----------------------------------------------


class TestInboxFiltering:
    """Verify that the API correctly filters to show only inbox tasks."""

    def test_filter_by_inbox_tier(self, authed_client, app):
        with app.app_context():
            _make_task(title="In inbox", tier=Tier.INBOX)
            _make_task(title="In today", tier=Tier.TODAY)
            _make_task(title="In backlog", tier=Tier.BACKLOG)

        resp = authed_client.get("/api/tasks?tier=inbox")
        assert resp.status_code == 200
        titles = [t["title"] for t in resp.get_json()]
        assert titles == ["In inbox"]

    def test_inbox_excludes_deleted_tasks(self, authed_client, app):
        with app.app_context():
            _make_task(title="Active inbox", tier=Tier.INBOX)
            _make_task(
                title="Deleted inbox",
                tier=Tier.INBOX,
                status=TaskStatus.DELETED,
            )

        resp = authed_client.get("/api/tasks?tier=inbox")
        titles = [t["title"] for t in resp.get_json()]
        assert titles == ["Active inbox"]

    def test_inbox_excludes_archived_tasks(self, authed_client, app):
        with app.app_context():
            _make_task(title="Active", tier=Tier.INBOX)
            _make_task(
                title="Archived",
                tier=Tier.INBOX,
                status=TaskStatus.ARCHIVED,
            )

        resp = authed_client.get("/api/tasks?tier=inbox")
        titles = [t["title"] for t in resp.get_json()]
        assert titles == ["Active"]


# --- Complete from inbox (skip triage) ----------------------------------------


class TestInboxComplete:
    """A user might complete a task directly from inbox without triaging."""

    def test_complete_task_from_inbox(self, authed_client, app):
        with app.app_context():
            task = _make_task(title="Quick win", tier=Tier.INBOX)
            task_id = str(task.id)

        # Complete it (archive) directly from inbox
        resp = authed_client.patch(
            f"/api/tasks/{task_id}", json={"status": "archived"}
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "archived"

        # No longer appears in inbox (default filter is active only)
        resp = authed_client.get("/api/tasks?tier=inbox")
        assert resp.get_json() == []

    def test_delete_task_from_inbox(self, authed_client, app):
        with app.app_context():
            task = _make_task(title="Junk", tier=Tier.INBOX)
            task_id = str(task.id)

        resp = authed_client.delete(f"/api/tasks/{task_id}")
        assert resp.status_code == 204

        resp = authed_client.get("/api/tasks?tier=inbox")
        assert resp.get_json() == []
