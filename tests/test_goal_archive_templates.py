"""#368: archiving a goal pauses its repeating templates.

Spec: docs/design/368-goal-archive-pauses-templates.md. Mirrors #353
(tests/test_project_archive_templates.py) for the second parent. A
template carries one marker per parent (`paused_by_project_archive`,
`paused_by_goal_archive`) and restarts only when neither is left, so a
template on an archived project AND an archived goal stays paused until
both come back.

`_state` returns `(is_active, project marker, goal marker)`.
"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

import recycle_service
from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    ImportLog,
    Project,
    RecurringFrequency,
    RecurringTask,
    ReflectionInputMode,
    TaskType,
    db,
)
from recurring_service import cascade_parent_archive

_MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "migrations" / "versions"
    / "s8a9b0c1d2e3_recurring_paused_by_goal_archive.py"
)


def _goal(title: str, *, active: bool = True) -> Goal:
    g = Goal(title=title, category=GoalCategory.WORK,
             priority=GoalPriority.MUST, is_active=active)
    db.session.add(g)
    db.session.commit()
    return g


def _project(name: str, *, active: bool = True) -> Project:
    p = Project(name=name, is_active=active)
    db.session.add(p)
    db.session.commit()
    return p


def _recurring(title: str, *, project: Project | None = None,
               goal: Goal | None = None, **kw) -> RecurringTask:
    rt = RecurringTask(
        title=title,
        frequency=kw.pop("frequency", RecurringFrequency.DAILY),
        type=kw.pop("type", TaskType.WORK),
        project_id=project.id if project else None,
        goal_id=goal.id if goal else None,
        **kw,
    )
    db.session.add(rt)
    db.session.commit()
    return rt


def _state(rt_id) -> tuple[bool, bool, bool]:
    rt = db.session.get(RecurringTask, rt_id)
    db.session.refresh(rt)
    return rt.is_active, rt.paused_by_project_archive, rt.paused_by_goal_archive


# --- migration backfill (spec §4.4) ------------------------------------------


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_368", _MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_backfill_pauses_active_templates_on_archived_goals(app):
    with app.app_context():
        g_off = _goal("Old goal", active=False)
        g_on = _goal("Live goal")
        p_off = _project("Old project", active=False)
        a = _recurring("a", goal=g_off)
        b = _recurring("b", goal=g_off, is_active=False)
        c = _recurring("c", goal=g_off, project=p_off, is_active=False,
                       paused_by_project_archive=True)
        d = _recurring("d", goal=g_on)
        ids = a.id, b.id, c.id, d.id

        for stmt in _load_migration().BACKFILL_SQL:
            db.session.execute(sa.text(stmt))
        db.session.commit()

        assert _state(ids[0]) == (False, False, True)
        # Already paused by the user: we can't know why, so not ours.
        assert _state(ids[1]) == (False, False, False)
        # Paused by its project's archive: gains the goal marker so the
        # project's unarchive alone can't wake it.
        assert _state(ids[2]) == (False, True, True)
        assert _state(ids[3]) == (True, False, False)


# --- the shared cascade on every goal archive path (spec §4.2) ----------------


def _archive_goal(client, gid):
    return client.delete(f"/api/goals/{gid}")


def _archive_goal_patch(client, gid):
    return client.patch(f"/api/goals/{gid}", json={"is_active": False})


def _unarchive_goal(client, gid):
    return client.patch(f"/api/goals/{gid}", json={"is_active": True})


def _archive_project(client, pid):
    return client.patch(f"/api/projects/{pid}", json={"is_active": False})


def _unarchive_project(client, pid):
    return client.patch(f"/api/projects/{pid}", json={"is_active": True})


def _ok(resp):
    # PATCH answers 200, the archive DELETE answers 204.
    assert resp.status_code in (200, 204), resp.get_data(as_text=True)


def test_archive_goal_pauses_active_template_and_marks_it(authed_client, app):
    with app.app_context():
        g = _goal("Fitness")
        gid, rt_id = g.id, _recurring("stretch", goal=g).id

    _ok(_archive_goal(authed_client, gid))
    with app.app_context():
        assert _state(rt_id) == (False, False, True)

    _ok(_unarchive_goal(authed_client, gid))
    with app.app_context():
        assert _state(rt_id) == (True, False, False)


@pytest.mark.parametrize("archive", [_archive_goal, _archive_goal_patch])
def test_patch_and_delete_archive_goal_identical(authed_client, app, archive):
    with app.app_context():
        g = _goal("Fitness")
        gid, rt_id = g.id, _recurring("stretch", goal=g).id

    _ok(archive(authed_client, gid))
    with app.app_context():
        assert _state(rt_id) == (False, False, True)


def test_user_paused_template_untouched_by_goal_archive_and_unarchive(
    authed_client, app,
):
    with app.app_context():
        g = _goal("Fitness")
        gid = g.id
        rt_id = _recurring("stretch", goal=g, is_active=False).id

    _ok(_archive_goal(authed_client, gid))
    with app.app_context():
        assert _state(rt_id) == (False, False, False)
    _ok(_unarchive_goal(authed_client, gid))
    with app.app_context():
        assert _state(rt_id) == (False, False, False)


def test_redelete_archived_goal_does_not_repause(authed_client, app):
    # Review Focus 3: a second DELETE (another tab, a double click) on an
    # already-archived goal is not a transition, so it must not re-pause
    # a template the user turned back on by hand.
    with app.app_context():
        g = _goal("Fitness")
        gid, rt_id = g.id, _recurring("stretch", goal=g).id

    _ok(_archive_goal(authed_client, gid))
    _ok(authed_client.patch(f"/api/recurring/{rt_id}", json={"is_active": True}))
    _ok(_archive_goal(authed_client, gid))

    with app.app_context():
        assert _state(rt_id) == (True, False, False)


def test_goal_only_template_resumes_on_unarchive(authed_client, app):
    # Review Focus 1: no project at all must count as "no archived
    # project", not as a parent that's still away.
    with app.app_context():
        g = _goal("Fitness")
        gid = g.id
        rt = _recurring("stretch", goal=g)
        assert rt.project_id is None
        rt_id = rt.id

    _ok(_archive_goal(authed_client, gid))
    _ok(_unarchive_goal(authed_client, gid))
    with app.app_context():
        assert _state(rt_id) == (True, False, False)


def _overlap(app):
    """A template on a live project P and a live goal G."""
    with app.app_context():
        p, g = _project("P"), _goal("G")
        return p.id, g.id, _recurring("routine", project=p, goal=g).id


def test_overlap_unarchive_project_first(authed_client, app):
    pid, gid, rt_id = _overlap(app)
    _ok(_archive_project(authed_client, pid))
    _ok(_archive_goal(authed_client, gid))
    with app.app_context():
        assert _state(rt_id) == (False, True, True)

    _ok(_unarchive_project(authed_client, pid))
    with app.app_context():
        assert _state(rt_id) == (False, False, True)

    _ok(_unarchive_goal(authed_client, gid))
    with app.app_context():
        assert _state(rt_id) == (True, False, False)


def test_overlap_unarchive_goal_first(authed_client, app):
    pid, gid, rt_id = _overlap(app)
    _ok(_archive_project(authed_client, pid))
    _ok(_archive_goal(authed_client, gid))

    _ok(_unarchive_goal(authed_client, gid))
    with app.app_context():
        assert _state(rt_id) == (False, True, False)

    _ok(_unarchive_project(authed_client, pid))
    with app.app_context():
        assert _state(rt_id) == (True, False, False)


def test_overlap_goal_archived_first_then_project(authed_client, app):
    pid, gid, rt_id = _overlap(app)
    _ok(_archive_goal(authed_client, gid))
    with app.app_context():
        assert _state(rt_id) == (False, False, True)

    _ok(_archive_project(authed_client, pid))
    with app.app_context():
        assert _state(rt_id) == (False, True, True)


def test_reflection_apply_goal_update_and_delete_pause_templates(app):
    # The Claude-proposal apply path calls update_goal / delete_goal
    # directly, so the cascade has to live in the service layer.
    with app.app_context():
        from reflection_service import apply_selected_actions, save_reflection

        g1, g2 = _goal("Updated away"), _goal("Deleted away")
        rt1 = _recurring("one", goal=g1).id
        rt2 = _recurring("two", goal=g2).id
        reflection = save_reflection(
            transcript="wrap these up",
            input_mode=ReflectionInputMode.TYPED,
            proposed={"explicit": [], "suggested": []},
        )
        summary = apply_selected_actions(reflection, [
            {"op": "update", "entity": "goal", "id": str(g1.id),
             "payload": {"is_active": False}},
            {"op": "delete", "entity": "goal", "id": str(g2.id)},
        ])

        assert summary["errors"] == []
        assert _state(rt1) == (False, False, True)
        assert _state(rt2) == (False, False, True)


def _batch_with_goal(title: str):
    """An import batch holding one goal, in the live state."""
    batch_id = uuid.uuid4()
    g = Goal(title=title, category=GoalCategory.WORK,
             priority=GoalPriority.SHOULD, batch_id=batch_id)
    db.session.add(g)
    db.session.add(ImportLog(source="t", task_count=1, batch_id=batch_id))
    db.session.commit()
    return batch_id, g


def test_undo_batch_pauses_goal_templates(app):
    with app.app_context():
        bid, g = _batch_with_goal("Imported goal")
        rt_id = _recurring("routine", goal=g).id

        recycle_service.undo_batch(bid)
        assert _state(rt_id) == (False, False, True)


def test_restore_batch_resumes_goal_templates(app):
    with app.app_context():
        bid, g = _batch_with_goal("Imported goal")
        rt_id = _recurring("routine", goal=g).id

        recycle_service.undo_batch(bid)
        recycle_service.restore_batch(bid)
        assert _state(rt_id) == (True, False, False)


def test_cascade_parent_archive_rejects_unknown_parent(app):
    with app.app_context(), pytest.raises(ValueError):
        cascade_parent_archive("milestone", uuid.uuid4(), True)


# --- marker hygiene (spec §4.3) -----------------------------------------------
#
# Anything the user does to the template itself overrides "paused because
# a parent was archived". Clearing a marker never resumes on its own.


def _both_archived(client, app):
    pid, gid, rt_id = _overlap(app)
    _ok(_archive_project(client, pid))
    _ok(_archive_goal(client, gid))
    with app.app_context():
        assert _state(rt_id) == (False, True, True)
    return pid, gid, rt_id


def test_manual_resume_clears_both_markers(authed_client, app):
    pid, gid, rt_id = _both_archived(authed_client, app)

    _ok(authed_client.patch(f"/api/recurring/{rt_id}", json={"is_active": True}))
    with app.app_context():
        assert _state(rt_id) == (True, False, False)

    _ok(_unarchive_project(authed_client, pid))
    _ok(_unarchive_goal(authed_client, gid))
    with app.app_context():
        assert _state(rt_id) == (True, False, False)


def test_bulk_recurring_patch_clears_both_markers(authed_client, app):
    # Review Focus 2: the /recurring bulk toolbar goes through
    # update_recurring per row, so it has to clear both markers too.
    _, _, rt_id = _both_archived(authed_client, app)

    _ok(authed_client.patch("/api/recurring/bulk", json={
        "template_ids": [str(rt_id)], "updates": {"is_active": True},
    }))
    with app.app_context():
        assert _state(rt_id) == (True, False, False)


def test_delete_template_clears_both_markers(authed_client, app):
    pid, gid, rt_id = _both_archived(authed_client, app)

    _ok(authed_client.delete(f"/api/recurring/{rt_id}"))
    with app.app_context():
        assert _state(rt_id) == (False, False, False)

    _ok(_unarchive_project(authed_client, pid))
    _ok(_unarchive_goal(authed_client, gid))
    with app.app_context():
        assert _state(rt_id) == (False, False, False)


def test_goal_change_clears_only_goal_marker(authed_client, app):
    _, _, rt_id = _both_archived(authed_client, app)
    with app.app_context():
        other = _goal("Elsewhere").id

    _ok(authed_client.patch(f"/api/recurring/{rt_id}", json={"goal_id": str(other)}))
    with app.app_context():
        assert _state(rt_id) == (False, True, False)


def test_resending_same_goal_id_keeps_goal_marker(authed_client, app):
    # Review Focus 5: the /recurring editor re-sends goal_id on every Save.
    _, gid, rt_id = _both_archived(authed_client, app)

    _ok(authed_client.patch(f"/api/recurring/{rt_id}", json={"goal_id": str(gid)}))
    with app.app_context():
        assert _state(rt_id) == (False, True, True)


def test_project_move_to_new_goal_clears_goal_marker(authed_client, app):
    # #352's cascade re-points the project's templates at the new goal.
    # That's a goal change, so the old goal's marker goes; the template
    # stays paused (clearing never resumes).
    with app.app_context():
        g1, g2 = _goal("Old"), _goal("New")
        p = Project(name="P", goal_id=g1.id)
        db.session.add(p)
        db.session.commit()
        pid, gid1, gid2 = p.id, g1.id, g2.id
        rt_id = _recurring("routine", project=p, goal=g1).id

    _ok(_archive_goal(authed_client, gid1))
    with app.app_context():
        assert _state(rt_id) == (False, False, True)

    _ok(authed_client.patch(f"/api/projects/{pid}", json={"goal_id": str(gid2)}))
    with app.app_context():
        assert _state(rt_id) == (False, False, False)
        assert db.session.get(RecurringTask, rt_id).goal_id == gid2


def test_project_move_onto_templates_own_goal_keeps_goal_marker(app):
    # Final review: a template that already sits on the project's NEW
    # goal has no goal change, so its marker must survive the #352
    # cascade, or unarchiving that goal would silently leave it paused.
    # Reachable through the reflection path's update_project.
    from goal_service import update_goal
    from project_service import update_project

    with app.app_context():
        g = _goal("G")
        p = _project("P")
        rt_id = _recurring("routine", project=p, goal=g).id
        update_goal(g.id, {"is_active": False})
        assert _state(rt_id) == (False, False, True)

        update_project(p.id, {"goal_id": str(g.id)})
        assert _state(rt_id) == (False, False, True)

        update_goal(g.id, {"is_active": True})
        assert _state(rt_id) == (True, False, False)


def _fk_on():
    # SQLite enforces ON DELETE SET NULL only with the pragma on (the
    # tests/test_recycle_bin.py pattern); Postgres always does.
    db.session.execute(sa.text("PRAGMA foreign_keys=ON"))


def test_purge_goal_clears_only_goal_marker_and_resumes_nothing(app):
    from project_service import update_project

    with app.app_context():
        _fk_on()
        bid, g = _batch_with_goal("Imported goal")
        p = _project("Mine")
        rt_id = _recurring("routine", project=p, goal=g).id
        update_project(p.id, {"is_active": False})
        recycle_service.undo_batch(bid)
        assert _state(rt_id) == (False, True, True)

        recycle_service.purge_batch(bid, "DELETE")
        assert _state(rt_id) == (False, True, False)
        assert db.session.get(RecurringTask, rt_id).goal_id is None

        # The project marker survived the purge, so the project's
        # unarchive still brings it back.
        update_project(p.id, {"is_active": True})
        assert _state(rt_id) == (True, False, False)
