"""#353: archiving a project pauses its repeating tasks.

Spec: docs/design/353-project-archive-pauses-templates.md.

Before this, archiving a project never touched `RecurringTask`, and
`spawn_today_tasks` only checks the template's own `is_active` — so a
template kept creating fresh tasks inside a project the user had put
away. Two templates on prod sat on the archived "Community of Practice"
project, one still spawning.

The rule (spec §2): every path that archives a project pauses the
project's CURRENTLY-ACTIVE templates and flags them
(`paused_by_project_archive`); unarchiving resumes only the flagged
ones; anything the user does that overrides that intent clears the flag.
"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    ImportLog,
    Project,
    RecurringFrequency,
    RecurringTask,
    ReflectionInputMode,
    Task,
    TaskType,
    Tier,
    db,
)

_MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "migrations" / "versions"
    / "r7f8a9b0c1d2_recurring_paused_by_project_archive.py"
)


def _project(name: str, *, active: bool = True) -> Project:
    p = Project(name=name, is_active=active)
    db.session.add(p)
    db.session.commit()
    return p


def _recurring(title: str, project: Project | None, **kw) -> RecurringTask:
    rt = RecurringTask(
        title=title,
        frequency=kw.pop("frequency", RecurringFrequency.DAILY),
        type=kw.pop("type", TaskType.WORK),
        project_id=project.id if project else None,
        **kw,
    )
    db.session.add(rt)
    db.session.commit()
    return rt


def _state(rt_id) -> tuple[bool, bool]:
    rt = db.session.get(RecurringTask, rt_id)
    db.session.refresh(rt)
    return rt.is_active, rt.paused_by_project_archive


# --- migration backfill (spec §4.5, test 14) ---------------------------------
#
# The repo had no migration-data test pattern. The revision exposes its
# UPDATE as `BACKFILL_SQL` and this runs that exact string, so the test
# exercises the SQL that ships rather than a copy of it.


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_353", _MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_backfill_pauses_active_templates_on_archived_projects(app):
    with app.app_context():
        archived = _project("Community of Practice", active=False)
        live = _project("Live")
        a = _recurring("menti survey", archived)
        b = _recurring("check survey", archived, is_active=False)
        c = _recurring("standup", live)
        ids = a.id, b.id, c.id

        db.session.execute(sa.text(_load_migration().BACKFILL_SQL))
        db.session.commit()

        assert _state(ids[0]) == (False, True)
        # Already inactive: we can't know who paused it, so not ours.
        assert _state(ids[1]) == (False, False)
        assert _state(ids[2]) == (True, False)


# --- the shared cascade (spec §4.1, tests 1-9) -------------------------------


def _archive_patch(client, pid):
    return client.patch(f"/api/projects/{pid}", json={"is_active": False})


def _archive_delete(client, pid):
    return client.delete(f"/api/projects/{pid}")


def _unarchive(client, pid):
    return client.patch(f"/api/projects/{pid}", json={"is_active": True})


def test_archive_pauses_active_template_and_flags_it(authed_client, app):
    with app.app_context():
        p = _project("CoP")
        rt_id, pid = _recurring("menti survey", p).id, p.id

    assert _archive_patch(authed_client, pid).status_code == 200

    with app.app_context():
        assert _state(rt_id) == (False, True)


def test_archive_leaves_already_paused_template_unflagged(authed_client, app):
    # The user paused this one themselves. Unarchiving must not be able
    # to resume it, so archiving must not claim it.
    with app.app_context():
        p = _project("CoP")
        rt_id, pid = _recurring("old", p, is_active=False).id, p.id

    _archive_patch(authed_client, pid)

    with app.app_context():
        assert _state(rt_id) == (False, False)


def test_unarchive_resumes_only_flagged_templates(authed_client, app):
    with app.app_context():
        p = _project("CoP")
        ours = _recurring("ours", p).id
        theirs = _recurring("theirs", p, is_active=False).id
        pid = p.id

    _archive_patch(authed_client, pid)
    with app.app_context():
        assert _state(ours) == (False, True)  # paused by us, so ours to resume
    assert _unarchive(authed_client, pid).status_code == 200

    with app.app_context():
        assert _state(ours) == (True, False)
        assert _state(theirs) == (False, False)


@pytest.mark.parametrize("archive", [_archive_patch, _archive_delete])
def test_delete_and_patch_archive_have_identical_template_effect(
    authed_client, app, archive,
):
    with app.app_context():
        p = _project("CoP")
        active = _recurring("active", p).id
        paused = _recurring("paused", p, is_active=False).id
        pid = p.id

    assert archive(authed_client, pid).status_code in (200, 204)

    with app.app_context():
        assert db.session.get(Project, pid).is_active is False
        assert _state(active) == (False, True)
        assert _state(paused) == (False, False)


def test_bulk_patch_and_bulk_delete_cascade_per_row(authed_client, app):
    with app.app_context():
        projects = [_project(n) for n in ("A", "B", "C", "D")]
        rts = [_recurring(f"t{i}", p).id for i, p in enumerate(projects)]
        ids = [str(p.id) for p in projects]

    resp = authed_client.patch(
        "/api/projects/bulk",
        json={"project_ids": ids[:2], "updates": {"is_active": False}},
    )
    assert resp.status_code == 200
    resp = authed_client.delete(
        "/api/projects/bulk", json={"project_ids": ids[2:]},
    )
    assert resp.status_code == 200

    with app.app_context():
        for rt_id in rts:
            assert _state(rt_id) == (False, True)


def test_noop_archive_does_not_repause_a_manually_resumed_template(
    authed_client, app,
):
    # Archive, then the user turns one template back on while the
    # project stays archived. Re-sending is_active:false (a second tab, a
    # double click) is not a transition and must not undo their choice.
    with app.app_context():
        p = _project("CoP")
        rt_id, pid = _recurring("keep me", p).id, p.id

    _archive_patch(authed_client, pid)
    with app.app_context():
        assert _state(rt_id) == (False, True)
        rt = db.session.get(RecurringTask, rt_id)
        rt.is_active = True
        rt.paused_by_project_archive = False
        db.session.commit()

    assert _archive_patch(authed_client, pid).status_code == 200

    with app.app_context():
        assert _state(rt_id) == (True, False)


def test_templates_on_other_projects_untouched(authed_client, app):
    with app.app_context():
        target, other = _project("Target"), _project("Other")
        _recurring("going", target)
        stays = _recurring("stays", other).id
        loose = _recurring("no project", None).id
        pid = target.id

    _archive_patch(authed_client, pid)

    with app.app_context():
        assert _state(stays) == (True, False)
        assert _state(loose) == (True, False)


def test_reflection_apply_update_and_delete_pause_templates(app):
    # The Claude-proposal apply path calls update_project/delete_project
    # directly. This is why the cascade has to live in the service layer.
    with app.app_context():
        from reflection_service import apply_selected_actions, save_reflection

        p1, p2 = _project("Updated away"), _project("Deleted away")
        rt1, rt2 = _recurring("one", p1).id, _recurring("two", p2).id
        reflection = save_reflection(
            transcript="wrap these up",
            input_mode=ReflectionInputMode.TYPED,
            proposed={"explicit": [], "suggested": []},
        )
        summary = apply_selected_actions(reflection, [
            {"op": "update", "entity": "project", "id": str(p1.id),
             "payload": {"is_active": False}},
            {"op": "delete", "entity": "project", "id": str(p2.id)},
        ])

        assert summary["errors"] == []
        assert _state(rt1) == (False, True)
        assert _state(rt2) == (False, True)


@pytest.mark.parametrize("archive", [_archive_patch, _archive_delete])
def test_archive_preserves_task_project_and_goal_links(
    authed_client, app, archive,
):
    # Reverses PR63 #129's detach (ADR-038): both paths now keep the
    # link, which is what makes Delete-then-unarchive lossless.
    with app.app_context():
        g = Goal(title="G", category=GoalCategory.WORK,
                 priority=GoalPriority.MUST)
        db.session.add(g)
        db.session.commit()
        p = _project("CoP")
        t = Task(title="t", type=TaskType.WORK, tier=Tier.INBOX,
                 project_id=p.id, goal_id=g.id)
        db.session.add(t)
        db.session.commit()
        tid, pid, gid = t.id, p.id, g.id

    archive(authed_client, pid)

    with app.app_context():
        task = db.session.get(Task, tid)
        assert task.project_id == pid
        assert task.goal_id == gid


# --- Review Focus pins --------------------------------------------------------


def test_bulk_archive_row_failure_rolls_back_only_that_rows_pause(
    authed_client, app, monkeypatch,
):
    # bulk_update_projects rolls back a row that raises. The pause is
    # issued in that row's transaction, so it must roll back with it,
    # while the earlier row's committed pause stays.
    import project_service

    with app.app_context():
        good, bad = _project("Good"), _project("Bad")
        good_rt = _recurring("g", good).id
        bad_rt = _recurring("b", bad).id
        good_id, bad_id = good.id, bad.id

    real = project_service.update_project

    def flaky(project_id, data):
        if project_id == bad_id:
            # A genuinely invalid field, validated AFTER is_active, so
            # the cascade has already run when the row fails.
            data = {**data, "priority_order": "not-a-number"}
        return real(project_id, data)

    monkeypatch.setattr(project_service, "update_project", flaky)

    resp = authed_client.patch(
        "/api/projects/bulk",
        json={"project_ids": [str(good_id), str(bad_id)],
              "updates": {"is_active": False}},
    )
    assert resp.status_code == 200
    assert len(resp.get_json()["errors"]) == 1

    with app.app_context():
        assert _state(good_rt) == (False, True)
        assert _state(bad_rt) == (True, False)
        assert db.session.get(Project, bad_id).is_active is True


def test_recurring_editor_save_payload_keeps_flag(authed_client, app):
    # Review Focus 1. The /recurring editor's Save sends
    # recurringHelpers.buildRecurringEditPayload's shape: it ALWAYS
    # re-sends project_id (unchanged) and never sends is_active. Without
    # the actual-change guard, an ordinary edit would cancel the
    # archive-pause and unarchive would no longer resume the template.
    with app.app_context():
        p = _project("CoP")
        rt_id, pid = _recurring("menti survey", p).id, p.id

    _archive_patch(authed_client, pid)
    resp = authed_client.patch(f"/api/recurring/{rt_id}", json={
        "title": "menti survey (renamed)",
        "frequency": "daily",
        "type": "work",
        "project_id": str(pid),
        "goal_id": None,
        "url": None,
        "notes": None,
        "end_date": None,
        "day_of_week": None,
        "days_of_week": None,
        "day_of_month": None,
        "week_of_month": None,
    })
    assert resp.status_code == 200

    with app.app_context():
        assert _state(rt_id) == (False, True)
    _unarchive(authed_client, pid)
    with app.app_context():
        assert _state(rt_id) == (True, False)


# --- flag hygiene (spec §4.3, tests 10-13) ------------------------------------


def _archived_with_paused_template(client, app, name="CoP"):
    """A project archived through the real path, so its template is in
    the genuine paused-by-archive state rather than a hand-set one."""
    with app.app_context():
        p = _project(name)
        rt_id, pid = _recurring("routine", p).id, p.id
    _archive_patch(client, pid)
    with app.app_context():
        assert _state(rt_id) == (False, True)
    return pid, rt_id


def test_manual_resume_clears_flag_and_unarchive_leaves_it_alone(
    authed_client, app,
):
    pid, rt_id = _archived_with_paused_template(authed_client, app)

    authed_client.patch(f"/api/recurring/{rt_id}", json={"is_active": True})
    with app.app_context():
        assert _state(rt_id) == (True, False)
    # The user now pauses it themselves; unarchiving must respect that.
    authed_client.patch(f"/api/recurring/{rt_id}", json={"is_active": False})
    _unarchive(authed_client, pid)

    with app.app_context():
        assert _state(rt_id) == (False, False)


def test_moving_paused_template_clears_flag_and_it_stays_paused(
    authed_client, app,
):
    pid, rt_id = _archived_with_paused_template(authed_client, app)
    with app.app_context():
        new_home = _project("New home").id

    authed_client.patch(
        f"/api/recurring/{rt_id}", json={"project_id": str(new_home)},
    )
    with app.app_context():
        assert _state(rt_id) == (False, False)
    _unarchive(authed_client, pid)

    with app.app_context():
        assert _state(rt_id) == (False, False)


def test_deleting_paused_template_clears_flag_so_unarchive_cannot_resurrect_it(
    authed_client, app,
):
    # Delete writes the same is_active=False as Pause, so without this
    # the flag would survive and unarchive would bring the template back.
    pid, rt_id = _archived_with_paused_template(authed_client, app)

    assert authed_client.delete(f"/api/recurring/{rt_id}").status_code in (200, 204)
    with app.app_context():
        assert _state(rt_id) == (False, False)
    _unarchive(authed_client, pid)

    with app.app_context():
        assert _state(rt_id) == (False, False)


def test_resending_same_is_active_or_project_id_keeps_flag(authed_client, app):
    pid, rt_id = _archived_with_paused_template(authed_client, app)

    authed_client.patch(f"/api/recurring/{rt_id}", json={"is_active": False})
    authed_client.patch(f"/api/recurring/{rt_id}", json={"project_id": str(pid)})
    with app.app_context():
        assert _state(rt_id) == (False, True)
    _unarchive(authed_client, pid)

    with app.app_context():
        assert _state(rt_id) == (True, False)


def test_bulk_recurring_delete_clears_flag(authed_client, app):
    # The /recurring bulk Delete goes through delete_recurring per row.
    pid, rt_id = _archived_with_paused_template(authed_client, app)

    resp = authed_client.delete(
        "/api/recurring/bulk", json={"template_ids": [str(rt_id)]},
    )
    assert resp.status_code == 200
    _unarchive(authed_client, pid)

    with app.app_context():
        assert _state(rt_id) == (False, False)


def test_saving_a_spawned_task_keeps_its_link_to_an_archive_paused_template(
    authed_client, app,
):
    # Final-review finding. The detail panel shows Repeat "none" for a
    # task whose template is inactive (_serialize_repeat hides it), and
    # buildTaskDetailPayload always sends `repeat`. So an ordinary save of
    # a spawned task on an archived project sent repeat:null, and
    # _update_repeat cut the task loose from its template. After
    # unarchive the template resumed but the task had lost its link, and
    # setting Repeat again made a SECOND template. "none" was never a
    # choice the user made, so an inactive template's link is left alone.
    with app.app_context():
        p = _project("CoP")
        rt = _recurring("menti survey", p)
        t = Task(title="menti survey", type=TaskType.WORK, tier=Tier.TODAY,
                 project_id=p.id, recurring_task_id=rt.id)
        db.session.add(t)
        db.session.commit()
        pid, rt_id, tid = p.id, rt.id, t.id

    _archive_patch(authed_client, pid)
    resp = authed_client.patch(
        f"/api/tasks/{tid}", json={"notes": "edited", "repeat": None},
    )
    assert resp.status_code == 200

    with app.app_context():
        assert db.session.get(Task, tid).recurring_task_id == rt_id
        assert _state(rt_id) == (False, True)
    _unarchive(authed_client, pid)
    with app.app_context():
        assert _state(rt_id) == (True, False)
        assert db.session.get(Task, tid).recurring_task_id == rt_id


def test_undo_batch_does_not_pause_templates_356(app):
    # Pins CURRENT behavior: recycle_service writes is_active directly
    # and bypasses _set_project_active. Routing it through the cascade is
    # #356's job; this test makes that a deliberate change, not drift.
    import recycle_service

    with app.app_context():
        batch_id = uuid.uuid4()
        p = Project(name="Imported", batch_id=batch_id)
        db.session.add(p)
        db.session.add(ImportLog(source="t", task_count=1, batch_id=batch_id))
        db.session.commit()
        pid = p.id
        rt_id = _recurring("imported routine", p).id

        recycle_service.undo_batch(batch_id)

        assert db.session.get(Project, pid).is_active is False
        assert _state(rt_id) == (True, False)
