"""Integration tests for the inbox + triage flow.

These tests verify the full lifecycle: tasks land in inbox by default,
can be moved to other tiers (triaged), and the inbox empties out.
This corresponds to the spec's "Inbox (Default Landing View)" section.

Key terms:
- Triage: the act of reviewing inbox items and deciding where they go
  (Today, This Week, Backlog, or Freezer).
- Tier: one of the seven buckets a task can live in (inbox, today,
  tomorrow, this_week, next_week, backlog, freezer) — the tests below
  iterate ``Tier`` itself, so a new tier is covered automatically.

A task created WITH a due date files by that date instead of landing in
Inbox (#386) — that rule lives in ``tests/test_dated_task_skips_inbox.py``.
#413 refreshed this file (it had last changed in April, when there were
five tiers and bulk triage was one PATCH per task).
"""
from __future__ import annotations

import pytest

from models import Task, TaskStatus, TaskType, Tier, db

_TRIAGE_TARGETS = [t.value for t in Tier if t is not Tier.INBOX]


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

    @pytest.mark.parametrize("target", _TRIAGE_TARGETS)
    def test_move_inbox_to_every_other_tier(self, authed_client, app, target):
        with app.app_context():
            task = _make_task(title="Triage me", tier=Tier.INBOX)
            task_id = str(task.id)

        resp = authed_client.patch(f"/api/tasks/{task_id}", json={"tier": target})
        assert resp.status_code == 200
        assert resp.get_json()["tier"] == target

        # ...and it has left the inbox.
        inbox_ids = [t["id"] for t in authed_client.get("/api/tasks?tier=inbox").get_json()]
        assert task_id not in inbox_ids

    def test_every_tier_is_a_triage_target(self):
        # Guards the parametrization above against a tier being skipped.
        assert set(_TRIAGE_TARGETS) | {"inbox"} == {t.value for t in Tier}


# --- Bulk triage: moving multiple tasks at once --------------------------------


class TestBulkTriage:
    """Verify that multiple inbox tasks can be triaged in batch.

    In the UI, the user ticks several inbox items and assigns them all to
    one tier. The board sends ONE ``PATCH /api/tasks/bulk`` call
    (``static/app.js`` bulk toolbar) — the same path these tests drive.
    """

    def test_bulk_move_three_tasks_to_today(self, authed_client, app):
        with app.app_context():
            t1 = _make_task(title="Bulk 1", tier=Tier.INBOX)
            t2 = _make_task(title="Bulk 2", tier=Tier.INBOX)
            t3 = _make_task(title="Bulk 3", tier=Tier.INBOX)
            ids = [str(t1.id), str(t2.id), str(t3.id)]

        resp = authed_client.patch("/api/tasks/bulk", json={
            "task_ids": ids, "updates": {"tier": "today"},
        })
        assert resp.status_code == 200
        assert resp.get_json()["updated"] == 3

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

        # One bulk call per destination tier, as the toolbar does.
        for task_id, tier in ((id1, "today"), (id2, "backlog")):
            resp = authed_client.patch("/api/tasks/bulk", json={
                "task_ids": [task_id], "updates": {"tier": tier},
            })
            assert resp.get_json()["updated"] == 1

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

    @pytest.mark.parametrize("status", [
        TaskStatus.DELETED, TaskStatus.ARCHIVED, TaskStatus.CANCELLED,
    ])
    def test_inbox_lists_only_active_tasks(self, authed_client, app, status):
        with app.app_context():
            _make_task(title="Active inbox", tier=Tier.INBOX)
            _make_task(title=f"{status.value} inbox", tier=Tier.INBOX, status=status)

        resp = authed_client.get("/api/tasks?tier=inbox")
        titles = [t["title"] for t in resp.get_json()]
        assert titles == ["Active inbox"]

    def test_every_non_active_status_is_excluded(self):
        # Guards the parametrization above against a new status.
        assert {s for s in TaskStatus if s is not TaskStatus.ACTIVE} == {
            TaskStatus.DELETED, TaskStatus.ARCHIVED, TaskStatus.CANCELLED,
        }


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
