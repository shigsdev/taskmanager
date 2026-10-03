"""#369: the import-undo confirm names the repeating tasks the undo pauses.

Spec: docs/design/369-undo-confirm-names-paused-templates.md. The undo
archives the batch's active projects and goals (#356 / #368), and that
pauses every running template on them. ``undo_impact`` answers "which
ones?" before the undo, read-only, so Settings can say so in the
confirm. The parity test is the load-bearing one: the dialog may never
list more or fewer templates than the undo really pauses.
"""
from __future__ import annotations

import uuid

import pytest

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
from recurring_service import templates_paused_by_archive


def _batch():
    batch_id = uuid.uuid4()
    log = ImportLog(source="t", task_count=1, batch_id=batch_id)
    db.session.add(log)
    db.session.commit()
    return batch_id


def _goal(batch_id=None, *, active: bool = True) -> Goal:
    g = Goal(title="g", category=GoalCategory.WORK, priority=GoalPriority.SHOULD,
             batch_id=batch_id, is_active=active)
    db.session.add(g)
    db.session.commit()
    return g


def _project(batch_id=None, *, active: bool = True) -> Project:
    p = Project(name="p", batch_id=batch_id, is_active=active)
    db.session.add(p)
    db.session.commit()
    return p


def _template(title="routine", *, project=None, goal=None, active=True,
              by_project=False, by_goal=False) -> RecurringTask:
    rt = RecurringTask(title=title, frequency=RecurringFrequency.DAILY,
                       type=TaskType.WORK, is_active=active,
                       project_id=project.id if project else None,
                       goal_id=goal.id if goal else None,
                       paused_by_project_archive=by_project,
                       paused_by_goal_archive=by_goal)
    db.session.add(rt)
    db.session.commit()
    return rt


def _listed(batch_id) -> list[str]:
    return [t["id"] for t in recycle_service.undo_impact(batch_id)["paused_templates"]]


class TestUndoImpact:
    def test_template_on_batch_project_listed(self, app):
        bid = _batch()
        rt = _template(project=_project(bid))
        assert _listed(bid) == [str(rt.id)]

    def test_template_on_batch_goal_listed(self, app):
        bid = _batch()
        rt = _template(goal=_goal(bid))
        assert _listed(bid) == [str(rt.id)]

    def test_template_on_both_listed_once(self, app):
        bid = _batch()
        rt = _template(project=_project(bid), goal=_goal(bid))
        assert _listed(bid) == [str(rt.id)]

    def test_user_paused_template_not_listed(self, app):
        bid = _batch()
        _template(project=_project(bid), active=False)
        assert _listed(bid) == []

    def test_template_paused_by_other_archive_not_listed(self, app):
        # Already stopped by its (outside) goal's archive: the undo only
        # adds a marker, it doesn't stop anything, so nothing to warn of.
        bid = _batch()
        _template(project=_project(bid), goal=_goal(active=False),
                  active=False, by_goal=True)
        assert _listed(bid) == []

    def test_template_outside_batch_not_listed(self, app):
        bid = _batch()
        _project(bid)
        _template(project=_project(), goal=_goal())
        assert _listed(bid) == []

    def test_already_archived_batch_project_skipped(self, app):
        # _set_project_active is transition-guarded: the undo skips a
        # project the user had already archived, so its (user-resumed)
        # template keeps running and must not be listed.
        bid = _batch()
        _template(project=_project(bid, active=False))
        assert _listed(bid) == []

    def test_listed_in_title_order_with_titles(self, app):
        bid = _batch()
        p = _project(bid)
        _template("Water plants", project=p)
        _template("Backup laptop", project=p)
        titles = [t["title"] for t in
                  recycle_service.undo_impact(bid)["paused_templates"]]
        assert titles == ["Backup laptop", "Water plants"]

    def test_impact_matches_what_undo_actually_pauses(self, app):
        bid = _batch()
        p, g = _project(bid), _goal(bid)
        archived_p = _project(bid, active=False)
        for kwargs in (
            {"project": p},
            {"goal": g},
            {"project": p, "goal": g},
            {"project": p, "active": False},
            {"project": _project(), "goal": _goal()},
            {"project": archived_p},
            {"project": p, "goal": _goal(active=False), "active": False,
             "by_goal": True},
        ):
            _template(**kwargs)

        listed = set(_listed(bid))
        before = {str(rt.id): rt.is_active for rt in RecurringTask.query.all()}
        recycle_service.undo_batch(bid)
        db.session.expire_all()
        paused = {str(rt.id) for rt in RecurringTask.query.all()
                  if before[str(rt.id)] and not rt.is_active}

        assert paused, "fixture should pause something"
        assert listed == paused

    def test_impact_is_read_only(self, app):
        bid = _batch()
        rt = _template(project=_project(bid), goal=_goal(bid))
        recycle_service.undo_impact(bid)
        assert not db.session.dirty
        db.session.expire_all()
        rt = db.session.get(RecurringTask, rt.id)
        assert (rt.is_active, rt.paused_by_project_archive,
                rt.paused_by_goal_archive) == (True, False, False)
        log = db.session.scalar(db.select(ImportLog).where(ImportLog.batch_id == bid))
        assert log.undone_at is None
        assert all(p.is_active for p in Project.query.all())

    def test_unknown_batch_raises_not_found(self, app):
        with pytest.raises(recycle_service.BatchNotFoundError):
            recycle_service.undo_impact(uuid.uuid4())

    def test_already_undone_raises_state_error(self, app):
        bid = _batch()
        recycle_service.undo_batch(bid)
        with pytest.raises(recycle_service.BatchStateError):
            recycle_service.undo_impact(bid)


class TestTemplatesPausedByArchive:
    def test_empty_inputs_return_empty_list(self, app):
        _template(project=_project())
        assert templates_paused_by_archive([], []) == []

    def test_matches_project_or_goal(self, app):
        p, g = _project(), _goal()
        a = _template("a", project=p)
        b = _template("b", goal=g)
        _template("c", project=_project())
        got = templates_paused_by_archive([p.id], [g.id])
        assert [rt.id for rt in got] == [a.id, b.id]


class TestImpactRoute:
    def test_impact_route_200_shape(self, authed_client, app):
        bid = _batch()
        rt = _template("Water plants", project=_project(bid))
        resp = authed_client.get(f"/api/recycle-bin/impact/{bid}")
        assert resp.status_code == 200
        assert resp.get_json() == {
            "batch_id": str(bid),
            "paused_templates": [{"id": str(rt.id), "title": "Water plants"}],
        }

    def test_impact_400_bad_id(self, authed_client):
        resp = authed_client.get("/api/recycle-bin/impact/not-a-uuid")
        assert resp.status_code == 400

    def test_impact_404_unknown_batch(self, authed_client):
        resp = authed_client.get(f"/api/recycle-bin/impact/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_impact_409_when_already_undone(self, authed_client, app):
        bid = _batch()
        recycle_service.undo_batch(bid)
        resp = authed_client.get(f"/api/recycle-bin/impact/{bid}")
        assert resp.status_code == 409

    def test_impact_requires_login(self, client, app):
        bid = _batch()
        resp = client.get(f"/api/recycle-bin/impact/{bid}")
        assert resp.status_code in (302, 401, 403)
