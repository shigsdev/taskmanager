"""Integration tests for the weekly review flow (Step 12).

The weekly review lets the user step through tasks that haven't been
touched in 7+ days ("stale" tasks). For each task they choose an action:

- **keep**   — leave in current tier, stamp last_reviewed = today
- **freeze** — move to Freezer tier, stamp last_reviewed = today
- **delete** — soft-delete the task, taking its open subtasks to the
  Recycle Bin with it (#433)
- **snooze** — stamp last_reviewed = today; the same effect as keep
  today (Help says so too)

Every action refuses a task that isn't open — deleted, completed or
cancelled elsewhere — with a 422 that says to reload (#512).

These tests verify:
1. The API correctly identifies stale tasks (not reviewed in 7+ days)
2. Each review action modifies the task correctly
3. The review page renders with the expected HTML structure
4. Edge cases: empty review queue, invalid actions, missing tasks
"""
from __future__ import annotations

from datetime import timedelta

import pytest

import auth
from models import Task, TaskStatus, TaskType, Tier, db
from utils import local_today_date


# #240 (2026-05-27): tests previously used `date.today()` which returns
# UTC on CI runners. The server stamps `last_reviewed` via
# `local_today_date()` (DIGEST_TZ — America/New_York by default), so
# at the UTC↔ET midnight boundary the assertions `body["task"][
# "last_reviewed"] == _today().isoformat()` would fail with
# `2026-05-26 == 2026-05-27` style mismatches. Same fixture timing
# class as #181 (2026-05-09). Routing all date arithmetic through
# `local_today_date()` keeps the test math aligned with the server's
# view regardless of the runner's clock.
def _today() -> object:  # noqa: ANN201 — small wrapper
    return local_today_date()


def _make_task(**overrides) -> Task:
    """Helper to create a task directly in the database."""
    fields = {"title": "Review test", "type": TaskType.WORK}
    fields.update(overrides)
    task = Task(**fields)
    db.session.add(task)
    db.session.commit()
    return task


# --- Stale task identification ------------------------------------------------


class TestStaleTasksAPI:
    """Verify GET /api/review returns the right tasks.

    A task is "stale" if it has never been reviewed (last_reviewed is NULL)
    or was last reviewed more than 7 days ago.
    """

    def test_never_reviewed_task_is_stale(self, authed_client, app):
        """A task with last_reviewed = NULL should appear in the review list."""
        with app.app_context():
            _make_task(title="Never reviewed", last_reviewed=None)

        resp = authed_client.get("/api/review")
        assert resp.status_code == 200
        titles = [t["title"] for t in resp.get_json()]
        assert "Never reviewed" in titles

    def test_old_reviewed_task_is_stale(self, authed_client, app):
        """A task reviewed 8 days ago should appear in the review list."""
        with app.app_context():
            _make_task(
                title="Old review",
                last_reviewed=_today() - timedelta(days=8),
            )

        resp = authed_client.get("/api/review")
        titles = [t["title"] for t in resp.get_json()]
        assert "Old review" in titles

    def test_recently_reviewed_task_not_stale(self, authed_client, app):
        """A task reviewed 3 days ago should NOT appear in the review list."""
        with app.app_context():
            _make_task(
                title="Fresh review",
                last_reviewed=_today() - timedelta(days=3),
            )

        resp = authed_client.get("/api/review")
        titles = [t["title"] for t in resp.get_json()]
        assert "Fresh review" not in titles

    def test_reviewed_exactly_7_days_ago_is_stale(self, authed_client, app):
        """A task reviewed exactly 7 days ago should appear (boundary case)."""
        with app.app_context():
            _make_task(
                title="Boundary",
                last_reviewed=_today() - timedelta(days=7),
            )

        resp = authed_client.get("/api/review")
        titles = [t["title"] for t in resp.get_json()]
        assert "Boundary" in titles

    def test_deleted_task_excluded(self, authed_client, app):
        """Deleted tasks should not appear in the review queue."""
        with app.app_context():
            _make_task(
                title="Deleted",
                last_reviewed=None,
                status=TaskStatus.DELETED,
            )

        resp = authed_client.get("/api/review")
        titles = [t["title"] for t in resp.get_json()]
        assert "Deleted" not in titles

    def test_archived_task_excluded(self, authed_client, app):
        """Archived (completed) tasks should not appear in the review queue."""
        with app.app_context():
            _make_task(
                title="Archived",
                last_reviewed=None,
                status=TaskStatus.ARCHIVED,
            )

        resp = authed_client.get("/api/review")
        titles = [t["title"] for t in resp.get_json()]
        assert "Archived" not in titles

    def test_empty_review_queue(self, authed_client, app):
        """When all tasks are freshly reviewed, the list should be empty."""
        with app.app_context():
            _make_task(
                title="Fresh",
                last_reviewed=_today(),
            )

        resp = authed_client.get("/api/review")
        assert resp.get_json() == []


# --- Review actions -----------------------------------------------------------


class TestReviewKeepAction:
    """Verify the 'keep' action: task stays in its tier, last_reviewed = today."""

    def test_keep_stamps_last_reviewed(self, authed_client, app):
        with app.app_context():
            task = _make_task(title="Keep me", tier=Tier.TODAY, last_reviewed=None)
            task_id = str(task.id)

        resp = authed_client.post(
            f"/api/review/{task_id}",
            json={"action": "keep"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["action"] == "keep"
        assert body["task"]["last_reviewed"] == _today().isoformat()
        assert body["task"]["tier"] == "today"  # unchanged

    def test_keep_does_not_change_tier(self, authed_client, app):
        with app.app_context():
            task = _make_task(title="Stay", tier=Tier.BACKLOG)
            task_id = str(task.id)

        resp = authed_client.post(
            f"/api/review/{task_id}", json={"action": "keep"}
        )
        assert resp.get_json()["task"]["tier"] == "backlog"


class TestReviewFreezeAction:
    """Verify the 'freeze' action: task moves to Freezer tier."""

    def test_freeze_moves_to_freezer(self, authed_client, app):
        with app.app_context():
            task = _make_task(title="Freeze me", tier=Tier.BACKLOG)
            task_id = str(task.id)

        resp = authed_client.post(
            f"/api/review/{task_id}", json={"action": "freeze"}
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["task"]["tier"] == "freezer"
        assert body["task"]["last_reviewed"] == _today().isoformat()

    def test_freeze_from_today_tier(self, authed_client, app):
        with app.app_context():
            task = _make_task(title="Was today", tier=Tier.TODAY)
            task_id = str(task.id)

        resp = authed_client.post(
            f"/api/review/{task_id}", json={"action": "freeze"}
        )
        assert resp.get_json()["task"]["tier"] == "freezer"


class TestReviewDeleteAction:
    """Verify the 'delete' action: soft-deletes the task."""

    def test_delete_sets_status_deleted(self, authed_client, app):
        with app.app_context():
            task = _make_task(title="Delete me")
            task_id = str(task.id)

        resp = authed_client.post(
            f"/api/review/{task_id}", json={"action": "delete"}
        )
        assert resp.status_code == 200
        assert resp.get_json()["task"]["status"] == "deleted"

    def test_deleted_task_no_longer_in_review(self, authed_client, app):
        with app.app_context():
            task = _make_task(title="Gone")
            task_id = str(task.id)

        authed_client.post(f"/api/review/{task_id}", json={"action": "delete"})

        resp = authed_client.get("/api/review")
        titles = [t["title"] for t in resp.get_json()]
        assert "Gone" not in titles


class TestReviewSnoozeAction:
    """Verify the 'snooze' action: stamps last_reviewed but keeps tier."""

    def test_snooze_stamps_last_reviewed(self, authed_client, app):
        with app.app_context():
            task = _make_task(title="Snooze me", tier=Tier.THIS_WEEK)
            task_id = str(task.id)

        resp = authed_client.post(
            f"/api/review/{task_id}", json={"action": "snooze"}
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["task"]["last_reviewed"] == _today().isoformat()
        assert body["task"]["tier"] == "this_week"  # unchanged

    def test_snoozed_task_not_in_review_queue(self, authed_client, app):
        """After snoozing, the task should not appear in the review list
        (because last_reviewed is now today, which is < 7 days ago)."""
        with app.app_context():
            task = _make_task(title="Snoozed")
            task_id = str(task.id)

        authed_client.post(f"/api/review/{task_id}", json={"action": "snooze"})

        resp = authed_client.get("/api/review")
        titles = [t["title"] for t in resp.get_json()]
        assert "Snoozed" not in titles


# --- Error handling -----------------------------------------------------------


class TestReviewErrors:
    """Verify error handling for invalid review requests."""

    def test_invalid_action_rejected(self, authed_client, app):
        with app.app_context():
            task = _make_task()
            task_id = str(task.id)

        resp = authed_client.post(
            f"/api/review/{task_id}", json={"action": "explode"}
        )
        assert resp.status_code == 422

    def test_missing_action_rejected(self, authed_client, app):
        with app.app_context():
            task = _make_task()
            task_id = str(task.id)

        resp = authed_client.post(
            f"/api/review/{task_id}", json={}
        )
        assert resp.status_code == 422

    def test_nonexistent_task_404(self, authed_client):
        import uuid

        fake_id = str(uuid.uuid4())
        resp = authed_client.post(
            f"/api/review/{fake_id}", json={"action": "keep"}
        )
        assert resp.status_code == 404

    def test_no_json_body_400(self, authed_client, app):
        with app.app_context():
            task = _make_task()
            task_id = str(task.id)

        resp = authed_client.post(
            f"/api/review/{task_id}",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400


# --- Review page HTML ---------------------------------------------------------


class TestReviewPageView:
    """Verify the /review page renders with the expected structure.

    These tests check that the HTML template contains the DOM elements
    that the review.js JavaScript needs to work correctly.
    """

    def test_review_page_renders_200(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        resp = client.get("/review")
        assert resp.status_code == 200

    def test_review_page_has_container(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/review").data.decode()
        assert 'id="reviewContainer"' in html

    def test_review_page_has_loading_state(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/review").data.decode()
        assert 'id="reviewLoading"' in html

    def test_review_page_has_empty_state(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/review").data.decode()
        assert 'id="reviewEmpty"' in html

    def test_review_page_has_review_card(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/review").data.decode()
        assert 'id="reviewCard"' in html
        assert 'id="reviewTaskTitle"' in html

    def test_review_page_has_progress_bar(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/review").data.decode()
        assert 'id="reviewProgressFill"' in html
        assert 'id="reviewProgressText"' in html

    def test_review_page_has_action_buttons(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/review").data.decode()
        assert 'data-action="keep"' in html
        assert 'data-action="freeze"' in html
        assert 'data-action="snooze"' in html
        assert 'data-action="delete"' in html

    def test_review_page_has_summary_section(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/review").data.decode()
        assert 'id="reviewSummary"' in html
        assert 'id="reviewSummaryStats"' in html

    def test_review_page_loads_review_js(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/review").data.decode()
        assert "review.js" in html

    def test_review_page_has_back_link(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/review").data.decode()
        assert "Back to Tasks" in html

    def test_review_page_requires_auth(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/review")
        assert resp.status_code == 302

    def test_review_page_rejects_wrong_email(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "bad@example.com")
        resp = client.get("/review")
        assert resp.status_code == 403


# --- Nav link present on other pages ------------------------------------------


class TestReviewNavLink:
    """Verify the Weekly Review link appears in the navigation."""

    def test_index_has_review_link(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert "/review" in html

    def test_goals_has_review_link(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/goals").data.decode()
        assert "/review" in html


# --- #512: what the 2026-10-19 refresh found ----------------------------------


class TestReviewRefusesTasksThatAreNotOpen:
    """A stale /review tab must not move a task that was deleted or
    finished elsewhere (#474's rule, which the review route skipped):
    Freeze on a binned task used to set Freezer, so a later Restore
    landed it there."""

    @pytest.mark.parametrize("status,word", [
        (TaskStatus.DELETED, "Recycle Bin"),
        (TaskStatus.ARCHIVED, "completed"),
        (TaskStatus.CANCELLED, "cancelled"),
    ])
    @pytest.mark.parametrize("action", ["keep", "freeze", "snooze", "delete"])
    def test_every_action_is_refused_and_changes_nothing(
            self, authed_client, app, status, word, action):
        with app.app_context():
            t = _make_task(tier=Tier.BACKLOG, status=status)
            t_id = t.id
        resp = authed_client.post(f"/api/review/{t_id}", json={"action": action})
        assert resp.status_code == 422
        msg = resp.get_json()["error"]
        assert word in msg and "reload" in msg.lower()
        with app.app_context():
            after = db.session.get(Task, t_id)
            assert (after.status, after.tier, after.last_reviewed) == (
                status, Tier.BACKLOG, None)


class TestReviewDeleteTakesSubtasks:

    def test_open_subtasks_go_with_the_parent_and_come_back(self, authed_client, app):
        with app.app_context():
            parent = _make_task(title="parent", tier=Tier.BACKLOG)
            open_sub = _make_task(title="open", tier=Tier.BACKLOG, parent_id=parent.id)
            done_sub = _make_task(title="done", tier=Tier.BACKLOG, parent_id=parent.id,
                                  status=TaskStatus.ARCHIVED)
            ids = parent.id, open_sub.id, done_sub.id
        assert authed_client.post(f"/api/review/{ids[0]}",
                                  json={"action": "delete"}).status_code == 200
        with app.app_context():
            p, o, d = (db.session.get(Task, i) for i in ids)
            assert (p.status, o.status, d.status) == (
                TaskStatus.DELETED, TaskStatus.DELETED, TaskStatus.ARCHIVED)
            assert o.deleted_with_parent is True

    def test_deleting_a_binned_subtask_again_keeps_it_with_its_parent(self, app):
        """#512: _soft_delete re-ran on an already-deleted subtask and
        cleared deleted_with_parent, so restoring the parent left it in
        the bin. A second delete (DELETE /api/tasks, a stale tab) is now
        a no-op."""
        from task_service import delete_task, update_task

        parent = _make_task(title="parent", tier=Tier.BACKLOG)
        sub = _make_task(title="sub", tier=Tier.BACKLOG, parent_id=parent.id)
        delete_task(parent.id)
        assert sub.deleted_with_parent is True
        delete_task(sub.id)                       # the stale second delete
        assert sub.deleted_with_parent is True
        update_task(parent.id, {"status": "active"})
        db.session.expire_all()
        assert db.session.get(Task, sub.id).status == TaskStatus.ACTIVE


class TestReviewQueueGaps:

    def test_cancelled_task_is_not_stale(self, authed_client, app):
        with app.app_context():
            _make_task(status=TaskStatus.CANCELLED)
        assert authed_client.get("/api/review").get_json() == []

    def test_oldest_untouched_comes_first(self, authed_client, app):
        from datetime import UTC, datetime

        with app.app_context():
            newer = _make_task(title="newer")
            older = _make_task(title="older")
            newer.updated_at = datetime(2026, 5, 2, 12, tzinfo=UTC)
            older.updated_at = datetime(2026, 5, 1, 12, tzinfo=UTC)
            db.session.commit()
        titles = [t["title"] for t in authed_client.get("/api/review").get_json()]
        assert titles == ["older", "newer"]

    def test_bad_id_is_404_and_a_list_body_is_400(self, authed_client, app):
        assert authed_client.post("/api/review/not-a-uuid",
                                  json={"action": "keep"}).status_code == 404
        with app.app_context():
            t_id = _make_task().id
        assert authed_client.post(f"/api/review/{t_id}", json=[1]).status_code == 400

    @pytest.mark.parametrize("who,code", [(None, 401), ("intruder@example.com", 403)])
    def test_the_api_needs_the_owner(self, client, app, monkeypatch, who, code):
        with app.app_context():
            t_id = _make_task().id
        monkeypatch.setattr(auth, "get_current_user_email", lambda: who)
        assert client.get("/api/review").status_code == code
        assert client.post(f"/api/review/{t_id}",
                           json={"action": "keep"}).status_code == code
