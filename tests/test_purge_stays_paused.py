"""#373: Purge and Empty Bin name the repeating tasks that stay paused.

Spec: docs/design/373-purge-names-paused-templates.md. A purge clears the
"resume when unarchived" marker for the projects and goals it deletes, so
a template the undo paused stays paused for good unless it's still
waiting on another archived parent. ``list_bin`` (per batch, for Purge)
and ``bin_summary`` (whole bin, for Empty) name those templates. The
parity tests are the load-bearing ones: the dialog may never name more or
fewer templates than the purge really leaves paused.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import recycle_service
from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    ImportLog,
    Project,
    RecurringFrequency,
    RecurringTask,
    TaskType,
    db,
)


def _batch() -> uuid.UUID:
    batch_id = uuid.uuid4()
    db.session.add(ImportLog(source="t", task_count=1, batch_id=batch_id))
    db.session.commit()
    return batch_id


def _project(batch_id) -> Project:
    p = Project(name="p", batch_id=batch_id, is_active=True)
    db.session.add(p)
    db.session.commit()
    return p


def _goal(batch_id) -> Goal:
    g = Goal(title="g", category=GoalCategory.WORK, priority=GoalPriority.SHOULD,
             batch_id=batch_id, is_active=True)
    db.session.add(g)
    db.session.commit()
    return g


def _template(title, *, project=None, goal=None, active=True) -> RecurringTask:
    rt = RecurringTask(title=title, frequency=RecurringFrequency.DAILY,
                       type=TaskType.WORK, is_active=active,
                       project_id=project.id if project else None,
                       goal_id=goal.id if goal else None)
    db.session.add(rt)
    db.session.commit()
    return rt


def _entry(batch_id) -> dict:
    return next(e for e in recycle_service.list_bin() if e["batch_id"] == str(batch_id))


def _titles(items) -> list[str]:
    return [t["title"] for t in items]


def _left_paused(ids) -> list[str]:
    """After a purge: the templates that are paused, not deleted and no
    longer waiting on any archived parent — what the dialog promised."""
    out = []
    for rt_id in ids:
        rt = db.session.get(RecurringTask, rt_id)
        db.session.refresh(rt)
        if (not rt.is_active and rt.deleted_at is None
                and not rt.paused_by_project_archive and not rt.paused_by_goal_archive):
            out.append(rt.title)
    return sorted(out)


class TestPurgeNamesTemplates:
    def test_template_the_undo_paused_is_named(self, app):
        bid = _batch()
        _template("Water plants", project=_project(bid))
        recycle_service.undo_batch(bid)
        assert _titles(_entry(bid)["stays_paused"]) == ["Water plants"]

    def test_goal_template_is_named(self, app):
        bid = _batch()
        _template("Read", goal=_goal(bid))
        recycle_service.undo_batch(bid)
        assert _titles(_entry(bid)["stays_paused"]) == ["Read"]

    def test_names_sorted_by_title_and_listed_once(self, app):
        bid = _batch()
        p, g = _project(bid), _goal(bid)
        _template("b", project=p, goal=g)
        _template("a", project=p)
        recycle_service.undo_batch(bid)
        assert _titles(_entry(bid)["stays_paused"]) == ["a", "b"]

    def test_hand_paused_template_not_named(self, app):
        # The user paused it before the undo: no marker, purge changes nothing.
        bid = _batch()
        _template("mine", project=_project(bid), active=False)
        recycle_service.undo_batch(bid)
        assert _entry(bid)["stays_paused"] == []

    def test_deleted_template_not_named(self, app):
        bid = _batch()
        rt = _template("gone", project=_project(bid))
        recycle_service.undo_batch(bid)
        rt.deleted_at = datetime.now(UTC)
        db.session.commit()
        assert _entry(bid)["stays_paused"] == []

    def test_template_still_waiting_on_another_parent_not_named(self, app):
        # Project in batch A, goal in batch B: purging A leaves the goal
        # marker, so it still resumes when B's goal comes back.
        a, b = _batch(), _batch()
        _template("both", project=_project(a), goal=_goal(b))
        recycle_service.undo_batch(a)
        recycle_service.undo_batch(b)
        assert _entry(a)["stays_paused"] == []
        assert _entry(b)["stays_paused"] == []

    def test_batch_with_no_templates_is_quiet(self, app):
        bid = _batch()
        _project(bid)
        recycle_service.undo_batch(bid)
        assert _entry(bid)["stays_paused"] == []

    def test_parity_with_purge(self, app):
        a, b = _batch(), _batch()
        pa, gb = _project(a), _goal(b)
        ids = [
            _template("only a", project=pa).id,
            _template("a and b", project=pa, goal=gb).id,
            _template("mine", project=pa, active=False).id,
        ]
        recycle_service.undo_batch(a)
        recycle_service.undo_batch(b)
        promised = sorted(_titles(_entry(a)["stays_paused"]))
        recycle_service.purge_batch(a, "DELETE")
        # "mine" was paused by hand and stays so, but purge didn't do that.
        assert promised == [t for t in _left_paused(ids) if t != "mine"]
        assert promised == ["only a"]


class TestEmptyNamesTemplates:
    def test_summary_names_across_batches(self, app):
        a, b = _batch(), _batch()
        _template("both", project=_project(a), goal=_goal(b))
        _template("only b", goal=_goal(b))
        recycle_service.undo_batch(a)
        recycle_service.undo_batch(b)
        assert _titles(recycle_service.bin_summary()["stays_paused"]) == ["both", "only b"]

    def test_summary_quiet_when_none(self, app):
        bid = _batch()
        _project(bid)
        recycle_service.undo_batch(bid)
        assert recycle_service.bin_summary()["stays_paused"] == []

    def test_summary_ignores_parent_still_live(self, app):
        # Goal live (not in the bin): the template keeps nothing from it.
        a = _batch()
        live = _goal(None)
        _template("x", project=_project(a), goal=live)
        recycle_service.undo_batch(a)
        assert _titles(recycle_service.bin_summary()["stays_paused"]) == ["x"]

    def test_parity_with_empty(self, app):
        a, b = _batch(), _batch()
        pa, gb = _project(a), _goal(b)
        ids = [
            _template("only a", project=pa).id,
            _template("a and b", project=pa, goal=gb).id,
        ]
        recycle_service.undo_batch(a)
        recycle_service.undo_batch(b)
        promised = sorted(_titles(recycle_service.bin_summary()["stays_paused"]))
        recycle_service.empty_bin("DELETE")
        assert promised == _left_paused(ids) == ["a and b", "only a"]


class TestAPI:
    def test_list_and_summary_carry_stays_paused(self, authed_client, app):
        bid = _batch()
        _template("Water plants", project=_project(bid))
        recycle_service.undo_batch(bid)
        rows = authed_client.get("/api/recycle-bin").get_json()["batches"]
        row = next(r for r in rows if r["batch_id"] == str(bid))
        assert _titles(row["stays_paused"]) == ["Water plants"]
        summary = authed_client.get("/api/recycle-bin/summary").get_json()
        assert _titles(summary["stays_paused"]) == ["Water plants"]
