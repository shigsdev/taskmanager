"""Tests for the bulk-import undo + recycle bin feature.

Covers:
- Schema: batch_id is stamped by import_service, scan_service (new for scan),
  and survives roundtrip.
- Regular delete severs batch membership so undo/restore never resurrects
  a user-trashed task or goal.
- recycle_service: list_bin, undo, restore, purge, empty with cascade rules
  and state-transition errors.
- recycle_api: auth, 400/404/409 edge cases, typed-DELETE confirmation.
- Filter correctness: soft-deleted items don't leak into list_tasks,
  list_goals, or digest-style queries.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

import auth
import recycle_service
from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    ImportLog,
    Task,
    TaskStatus,
    TaskType,
    Tier,
    db,
)

# --- Helpers -----------------------------------------------------------------


def _make_batch(
    task_titles: list[str] | None = None,
    goal_titles: list[str] | None = None,
    source: str = "test_batch",
) -> uuid.UUID:
    """Create an ImportLog plus tasks/goals all sharing one batch_id."""
    batch_id = uuid.uuid4()
    for title in task_titles or []:
        db.session.add(
            Task(
                title=title,
                type=TaskType.WORK,
                tier=Tier.INBOX,
                batch_id=batch_id,
            )
        )
    for title in goal_titles or []:
        db.session.add(
            Goal(
                title=title,
                category=GoalCategory.WORK,
                priority=GoalPriority.SHOULD,
                batch_id=batch_id,
            )
        )
    db.session.add(
        ImportLog(
            source=source,
            task_count=(len(task_titles or []) + len(goal_titles or [])),
            batch_id=batch_id,
        )
    )
    db.session.commit()
    return batch_id


# --- Schema roundtrip --------------------------------------------------------


class TestSchema:
    def test_task_batch_id_roundtrips(self, app):
        bid = uuid.uuid4()
        t = Task(title="x", type=TaskType.WORK, batch_id=bid)
        db.session.add(t)
        db.session.commit()
        fetched = db.session.get(Task, t.id)
        assert fetched.batch_id == bid

    def test_goal_batch_id_roundtrips(self, app):
        bid = uuid.uuid4()
        g = Goal(
            title="y",
            category=GoalCategory.WORK,
            priority=GoalPriority.SHOULD,
            batch_id=bid,
        )
        db.session.add(g)
        db.session.commit()
        fetched = db.session.get(Goal, g.id)
        assert fetched.batch_id == bid

    def test_import_log_batch_and_undone_roundtrip(self, app):
        bid = uuid.uuid4()
        log = ImportLog(source="s", task_count=1, batch_id=bid)
        db.session.add(log)
        db.session.commit()
        fetched = db.session.get(ImportLog, log.id)
        assert fetched.batch_id == bid
        assert fetched.undone_at is None


# --- import_service + scan_service stamp batch_id ----------------------------


class TestBatchStamping:
    def test_create_tasks_from_import_stamps_batch(self, app):
        from import_service import create_tasks_from_import

        candidates = [
            {"title": "a", "type": "work", "included": True},
            {"title": "b", "type": "work", "included": True},
        ]
        tasks = create_tasks_from_import(candidates, source="onenote_test")
        assert len(tasks) == 2
        # All tasks share the same batch_id
        assert tasks[0].batch_id is not None
        assert tasks[0].batch_id == tasks[1].batch_id
        # And the ImportLog was created with that batch_id
        log = db.session.scalar(
            select(ImportLog).where(ImportLog.source == "onenote_test")
        )
        assert log is not None
        assert log.batch_id == tasks[0].batch_id

    def test_create_goals_from_import_stamps_batch(self, app):
        from import_service import create_goals_from_import

        candidates = [
            {
                "title": "goal 1",
                "category": "work",
                "priority": "should",
                "included": True,
            },
        ]
        goals = create_goals_from_import(candidates, source="excel_test")
        assert len(goals) == 1
        assert goals[0].batch_id is not None
        log = db.session.scalar(
            select(ImportLog).where(ImportLog.source == "excel_test")
        )
        assert log.batch_id == goals[0].batch_id

    def test_scan_confirm_creates_import_log_and_stamps_batch(self, app):
        from scan_service import create_tasks_from_candidates

        candidates = [
            {"title": "scanned 1", "type": "work", "included": True},
            {"title": "scanned 2", "type": "personal", "included": True},
        ]
        tasks = create_tasks_from_candidates(candidates)
        assert len(tasks) == 2
        assert tasks[0].batch_id == tasks[1].batch_id
        # Scan now logs to ImportLog with a scan_ prefix so it can be undone.
        log = db.session.scalar(
            select(ImportLog).where(ImportLog.source.like("scan_%"))
        )
        assert log is not None
        assert log.batch_id == tasks[0].batch_id

    def test_scan_confirm_empty_candidates_does_not_log(self, app):
        from scan_service import create_tasks_from_candidates

        result = create_tasks_from_candidates([])
        assert result == []
        log = db.session.scalar(
            select(ImportLog).where(ImportLog.source.like("scan_%"))
        )
        assert log is None


# --- Regular delete severs batch membership ----------------------------------


class TestRegularDeleteSeversBatch:
    def test_delete_task_clears_batch_id(self, app):
        from task_service import delete_task

        bid = _make_batch(task_titles=["t1"])
        task = db.session.scalar(select(Task).where(Task.batch_id == bid))

        assert delete_task(task.id) is True

        db.session.refresh(task)
        assert task.status == TaskStatus.DELETED
        assert task.batch_id is None  # severed

    def test_delete_goal_clears_batch_id(self, app):
        from goal_service import delete_goal

        bid = _make_batch(goal_titles=["g1"])
        goal = db.session.scalar(select(Goal).where(Goal.batch_id == bid))

        assert delete_goal(goal.id) is True

        db.session.refresh(goal)
        assert goal.is_active is False
        assert goal.batch_id is None

    def test_review_delete_clears_batch_id(self, app):
        from review_service import review_task

        bid = _make_batch(task_titles=["t1"])
        task = db.session.scalar(select(Task).where(Task.batch_id == bid))

        review_task(task, "delete")

        db.session.refresh(task)
        assert task.status == TaskStatus.DELETED
        assert task.batch_id is None

    def test_user_trashed_task_not_resurrected_by_restore(self, app):
        """Critical safety property: a regular-deleted task in a batch
        is severed (batch_id=None), so if the batch is later undone and
        restored the user's explicit trash decision is preserved."""
        from task_service import delete_task

        bid = _make_batch(task_titles=["keep", "trash me"])
        trash_me = db.session.scalar(
            select(Task).where(Task.title == "trash me")
        )
        delete_task(trash_me.id)  # user explicitly trashes it

        # Now undo the whole batch
        recycle_service.undo_batch(bid)
        # "trash me" should NOT be touched by undo (it's no longer in the batch)
        db.session.refresh(trash_me)
        assert trash_me.status == TaskStatus.DELETED
        assert trash_me.batch_id is None

        # Restore the batch
        recycle_service.restore_batch(bid)
        # "keep" comes back, "trash me" still gone
        keep = db.session.scalar(select(Task).where(Task.title == "keep"))
        assert keep.status == TaskStatus.ACTIVE
        db.session.refresh(trash_me)
        assert trash_me.status == TaskStatus.DELETED


# --- recycle_service happy paths ---------------------------------------------


class TestUndoRestorePurge:
    def test_undo_soft_deletes_tasks_and_goals(self, app):
        bid = _make_batch(task_titles=["t1", "t2"], goal_titles=["g1"])

        result = recycle_service.undo_batch(bid)

        assert result["tasks_removed"] == 2
        assert result["goals_removed"] == 1
        # Tasks now DELETED
        tasks = list(
            db.session.scalars(select(Task).where(Task.batch_id == bid))
        )
        for t in tasks:
            assert t.status == TaskStatus.DELETED
        # Goals now inactive
        goals = list(
            db.session.scalars(select(Goal).where(Goal.batch_id == bid))
        )
        for g in goals:
            assert g.is_active is False
        # ImportLog marked undone
        log = db.session.scalar(
            select(ImportLog).where(ImportLog.batch_id == bid)
        )
        assert log.undone_at is not None

    def test_undo_twice_raises_state_error(self, app):
        bid = _make_batch(task_titles=["t1"])
        recycle_service.undo_batch(bid)
        with pytest.raises(recycle_service.BatchStateError):
            recycle_service.undo_batch(bid)

    def test_undo_nonexistent_batch_raises_not_found(self, app):
        with pytest.raises(recycle_service.BatchNotFoundError):
            recycle_service.undo_batch(uuid.uuid4())

    def test_restore_un_soft_deletes(self, app):
        bid = _make_batch(task_titles=["t1"], goal_titles=["g1"])
        recycle_service.undo_batch(bid)

        result = recycle_service.restore_batch(bid)

        assert result["tasks_restored"] == 1
        assert result["goals_restored"] == 1
        task = db.session.scalar(select(Task).where(Task.batch_id == bid))
        assert task.status == TaskStatus.ACTIVE
        goal = db.session.scalar(select(Goal).where(Goal.batch_id == bid))
        assert goal.is_active is True
        log = db.session.scalar(
            select(ImportLog).where(ImportLog.batch_id == bid)
        )
        assert log.undone_at is None

    def test_restore_when_not_undone_raises(self, app):
        bid = _make_batch(task_titles=["t1"])
        with pytest.raises(recycle_service.BatchStateError):
            recycle_service.restore_batch(bid)

    def test_purge_requires_undo_first(self, app):
        bid = _make_batch(task_titles=["t1"])
        with pytest.raises(recycle_service.BatchStateError):
            recycle_service.purge_batch(bid, "DELETE")

    def test_purge_requires_typed_confirmation(self, app):
        bid = _make_batch(task_titles=["t1"])
        recycle_service.undo_batch(bid)
        with pytest.raises(recycle_service.ConfirmationError):
            recycle_service.purge_batch(bid, None)
        with pytest.raises(recycle_service.ConfirmationError):
            recycle_service.purge_batch(bid, "delete")  # lowercase, no match
        with pytest.raises(recycle_service.ConfirmationError):
            recycle_service.purge_batch(bid, "yes")

    def test_purge_hard_deletes_and_nulls_goal_references(self, app):
        # Create a batch with a goal + tasks that reference the goal
        bid = _make_batch(task_titles=["t1"], goal_titles=["g1"])
        goal = db.session.scalar(select(Goal).where(Goal.batch_id == bid))
        task = db.session.scalar(select(Task).where(Task.batch_id == bid))
        task.goal_id = goal.id

        # An UNRELATED task (not in the batch) also references the goal
        unrelated = Task(title="u1", type=TaskType.WORK, goal_id=goal.id)
        db.session.add(unrelated)
        db.session.commit()

        recycle_service.undo_batch(bid)
        result = recycle_service.purge_batch(bid, "DELETE")

        assert result["tasks_purged"] == 1
        assert result["goals_purged"] == 1
        # Rows gone
        assert db.session.scalar(select(Task).where(Task.batch_id == bid)) is None
        assert db.session.scalar(select(Goal).where(Goal.batch_id == bid)) is None
        # The unrelated task had its goal_id nulled (no dangling FK)
        db.session.refresh(unrelated)
        assert unrelated.goal_id is None
        # ImportLog row preserved as audit, batch_id nulled
        log = db.session.scalar(
            select(ImportLog).where(ImportLog.source == "test_batch")
        )
        assert log is not None
        assert log.batch_id is None

    def test_empty_bin_purges_all_batches(self, app):
        b1 = _make_batch(task_titles=["a"], source="batch_1")
        b2 = _make_batch(goal_titles=["g"], source="batch_2")
        recycle_service.undo_batch(b1)
        recycle_service.undo_batch(b2)

        result = recycle_service.empty_bin("DELETE")

        assert result["batches_purged"] == 2
        assert result["tasks_purged"] == 1
        assert result["goals_purged"] == 1
        # Both batches' rows are gone
        assert db.session.scalar(select(Task).where(Task.batch_id == b1)) is None
        assert db.session.scalar(select(Goal).where(Goal.batch_id == b2)) is None

    def test_empty_bin_requires_confirmation(self, app):
        _make_batch(task_titles=["t"])
        with pytest.raises(recycle_service.ConfirmationError):
            recycle_service.empty_bin(None)

    def test_empty_bin_on_empty_bin_is_noop(self, app):
        result = recycle_service.empty_bin("DELETE")
        assert result == {"batches_purged": 0, "tasks_purged": 0, "goals_purged": 0}


# --- Listing / summary -------------------------------------------------------


class TestListing:
    def test_list_bin_excludes_live_batches(self, app):
        b1 = _make_batch(task_titles=["t"], source="live")
        b2 = _make_batch(task_titles=["t"], source="undone")
        recycle_service.undo_batch(b2)

        bin_entries = recycle_service.list_bin()
        sources = [b["source"] for b in bin_entries]

        assert "undone" in sources
        assert "live" not in sources
        assert str(b1) not in [b["batch_id"] for b in bin_entries]

    def test_list_bin_counts_tasks_and_goals(self, app):
        bid = _make_batch(task_titles=["a", "b"], goal_titles=["g"])
        recycle_service.undo_batch(bid)

        bin_entries = recycle_service.list_bin()
        assert len(bin_entries) == 1
        entry = bin_entries[0]
        assert entry["task_count"] == 2
        assert entry["goal_count"] == 1

    def test_bin_summary_aggregates(self, app):
        b1 = _make_batch(task_titles=["a", "b"])
        b2 = _make_batch(goal_titles=["g1", "g2", "g3"])
        recycle_service.undo_batch(b1)
        recycle_service.undo_batch(b2)

        summary = recycle_service.bin_summary()
        assert summary["batch_count"] == 2
        assert summary["task_count"] == 2
        assert summary["goal_count"] == 3

    def test_bin_summary_empty(self, app):
        summary = recycle_service.bin_summary()
        assert summary == {"batch_count": 0, "task_count": 0, "goal_count": 0}


# --- Filter correctness: undone items don't leak into normal views -----------


class TestFilterCorrectness:
    def test_list_tasks_hides_soft_deleted_batch_items(self, app):
        from task_service import list_tasks

        bid = _make_batch(task_titles=["visible"])
        assert len(list_tasks()) == 1

        recycle_service.undo_batch(bid)
        # list_tasks defaults to status=ACTIVE — undone items must not appear
        assert list_tasks() == []

    def test_list_goals_hides_soft_deleted_batch_items(self, app):
        from goal_service import list_goals

        bid = _make_batch(goal_titles=["visible"])
        assert len(list_goals()) == 1

        recycle_service.undo_batch(bid)
        assert list_goals() == []

    def test_digest_query_excludes_undone_tasks(self, app):
        """Regression guard for the digest email leaking recycle bin items."""
        bid = _make_batch(task_titles=["digest task"])
        recycle_service.undo_batch(bid)

        count = db.session.scalar(
            select(db.func.count())
            .select_from(Task)
            .where(Task.status == TaskStatus.ACTIVE)
        )
        assert count == 0


# --- API layer ---------------------------------------------------------------


class TestRecycleAPI:
    def test_list_requires_auth(self, client):
        resp = client.get("/api/recycle-bin")
        assert resp.status_code in (302, 401, 403)

    def test_list_empty(self, authed_client):
        resp = authed_client.get("/api/recycle-bin")
        assert resp.status_code == 200
        assert resp.get_json() == {"batches": []}

    def test_summary_endpoint(self, authed_client, app):
        bid = _make_batch(task_titles=["t"])
        recycle_service.undo_batch(bid)

        resp = authed_client.get("/api/recycle-bin/summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["batch_count"] == 1
        assert data["task_count"] == 1

    def test_undo_endpoint_happy_path(self, authed_client, app):
        bid = _make_batch(task_titles=["t1"])

        resp = authed_client.post(f"/api/recycle-bin/undo/{bid}")
        assert resp.status_code == 200
        assert resp.get_json()["tasks_removed"] == 1

    def test_undo_invalid_uuid(self, authed_client):
        resp = authed_client.post("/api/recycle-bin/undo/not-a-uuid")
        assert resp.status_code == 400

    def test_undo_nonexistent_batch(self, authed_client):
        resp = authed_client.post(f"/api/recycle-bin/undo/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_undo_already_undone_returns_409(self, authed_client, app):
        bid = _make_batch(task_titles=["t"])
        authed_client.post(f"/api/recycle-bin/undo/{bid}")
        resp = authed_client.post(f"/api/recycle-bin/undo/{bid}")
        assert resp.status_code == 409

    def test_restore_endpoint_happy_path(self, authed_client, app):
        bid = _make_batch(task_titles=["t1"])
        recycle_service.undo_batch(bid)

        resp = authed_client.post(f"/api/recycle-bin/restore/{bid}")
        assert resp.status_code == 200
        assert resp.get_json()["tasks_restored"] == 1

    def test_restore_live_batch_returns_409(self, authed_client, app):
        bid = _make_batch(task_titles=["t"])
        resp = authed_client.post(f"/api/recycle-bin/restore/{bid}")
        assert resp.status_code == 409

    def test_purge_requires_confirmation_in_body(self, authed_client, app):
        bid = _make_batch(task_titles=["t"])
        recycle_service.undo_batch(bid)

        resp = authed_client.post(f"/api/recycle-bin/purge/{bid}", json={})
        assert resp.status_code == 400

        resp = authed_client.post(
            f"/api/recycle-bin/purge/{bid}", json={"confirmation": "nope"}
        )
        assert resp.status_code == 400

    def test_purge_happy_path(self, authed_client, app):
        bid = _make_batch(task_titles=["t"])
        recycle_service.undo_batch(bid)

        resp = authed_client.post(
            f"/api/recycle-bin/purge/{bid}", json={"confirmation": "DELETE"}
        )
        assert resp.status_code == 200
        assert resp.get_json()["tasks_purged"] == 1

    def test_purge_live_batch_returns_409(self, authed_client, app):
        bid = _make_batch(task_titles=["t"])
        resp = authed_client.post(
            f"/api/recycle-bin/purge/{bid}", json={"confirmation": "DELETE"}
        )
        assert resp.status_code == 409

    def test_empty_endpoint_requires_confirmation(self, authed_client, app):
        bid = _make_batch(task_titles=["t"])
        recycle_service.undo_batch(bid)

        resp = authed_client.post("/api/recycle-bin/empty", json={})
        assert resp.status_code == 400

    def test_empty_endpoint_happy_path(self, authed_client, app):
        b1 = _make_batch(task_titles=["a"])
        b2 = _make_batch(goal_titles=["g"])
        recycle_service.undo_batch(b1)
        recycle_service.undo_batch(b2)

        resp = authed_client.post(
            "/api/recycle-bin/empty", json={"confirmation": "DELETE"}
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["batches_purged"] == 2

    def test_unauthed_cannot_undo(self, client, app):
        bid = _make_batch(task_titles=["t"])
        resp = client.post(f"/api/recycle-bin/undo/{bid}")
        assert resp.status_code in (302, 401, 403)

    def test_wrong_user_cannot_undo(self, client, app, monkeypatch):
        """Ensure the @login_required decorator checks AUTHORIZED_EMAIL."""
        bid = _make_batch(task_titles=["t"])
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "bad@example.com")
        resp = client.post(f"/api/recycle-bin/undo/{bid}")
        assert resp.status_code in (302, 401, 403)


# --- Settings API exposes new fields -----------------------------------------


class TestSettingsAPIExtensions:
    def test_imports_endpoint_includes_batch_id_and_undone_at(
        self, authed_client, app
    ):
        bid = _make_batch(task_titles=["t"], source="onenote_x")
        resp = authed_client.get("/api/settings/imports")
        assert resp.status_code == 200
        logs = resp.get_json()
        assert len(logs) == 1
        assert logs[0]["batch_id"] == str(bid)
        assert logs[0]["undone_at"] is None

    def test_imports_endpoint_shows_undone_state(self, authed_client, app):
        bid = _make_batch(task_titles=["t"])
        recycle_service.undo_batch(bid)
        resp = authed_client.get("/api/settings/imports")
        logs = resp.get_json()
        assert logs[0]["undone_at"] is not None


# --- Page route --------------------------------------------------------------


class TestRecycleBinPage:
    def test_page_requires_auth(self, client):
        resp = client.get("/recycle-bin")
        assert resp.status_code in (302, 401, 403)

    def test_page_renders_for_authed_user(self, authed_client):
        resp = authed_client.get("/recycle-bin")
        assert resp.status_code == 200
        assert b"Recycle Bin" in resp.data
        assert b"Empty Bin" in resp.data
