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
    Task,
    TaskStatus,
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


# --- #356: the recycle bin follows the archive rule --------------------------
#
# Spec: docs/design/356-recycle-paths-follow-archive-rule.md. Undo and
# restore treat an imported project exactly as Archive / Unarchive do
# (via _set_project_active), and purge leaves no template flagged for a
# project that no longer exists.


def _batch_with_project(name: str):
    """An import batch holding one project, in the live state."""
    batch_id = uuid.uuid4()
    p = Project(name=name, batch_id=batch_id)
    db.session.add(p)
    db.session.add(ImportLog(source="t", task_count=1, batch_id=batch_id))
    db.session.commit()
    return batch_id, p


def test_undo_batch_pauses_templates(app):
    # Was test_undo_batch_does_not_pause_templates_356, which pinned the
    # bypass so #356 would change it on purpose. This is that change.
    with app.app_context():
        bid, p = _batch_with_project("Imported")
        pid, rt_id = p.id, _recurring("imported routine", p).id

        recycle_service.undo_batch(bid)

        assert db.session.get(Project, pid).is_active is False
        assert _state(rt_id) == (False, True)


def test_undo_batch_keeps_task_project_links(app):
    # ADR-038 on the last path that still broke it. Includes a task the
    # user linked by hand OUTSIDE the batch, which undo used to detach.
    with app.app_context():
        bid, p = _batch_with_project("Imported")
        in_batch = Task(title="imported", type=TaskType.WORK, tier=Tier.INBOX,
                        project_id=p.id, batch_id=bid)
        by_hand = Task(title="mine", type=TaskType.WORK, tier=Tier.INBOX,
                       project_id=p.id)
        db.session.add_all([in_batch, by_hand])
        db.session.commit()
        pid, in_id, hand_id = p.id, in_batch.id, by_hand.id

        recycle_service.undo_batch(bid)

        assert db.session.get(Task, in_id).project_id == pid
        hand = db.session.get(Task, hand_id)
        assert hand.project_id == pid
        assert hand.status == TaskStatus.ACTIVE


def test_restore_batch_resumes_templates_undo_paused(app):
    with app.app_context():
        bid, p = _batch_with_project("Imported")
        t = Task(title="imported", type=TaskType.WORK, tier=Tier.INBOX,
                 project_id=p.id, batch_id=bid)
        db.session.add(t)
        db.session.commit()
        pid, tid = p.id, t.id
        rt_id = _recurring("imported routine", p).id

        recycle_service.undo_batch(bid)
        result = recycle_service.restore_batch(bid)

        assert result["projects_restored"] == 1
        assert db.session.get(Project, pid).is_active is True
        assert _state(rt_id) == (True, False)
        # The round trip no longer loses the link.
        assert db.session.get(Task, tid).project_id == pid


def test_restore_batch_leaves_a_projects_archive_alone_and_unarchive_resumes(
    authed_client, app,
):
    # #353's final-review stuck state, revisited by #367. Archived on
    # /projects first (template flagged), so undo changes nothing about
    # the project. Restore now leaves it as the user left it, archived
    # (#367: restore only reverses what the undo did). It is not stuck:
    # the template keeps its flag, so unarchiving the project brings it
    # back.
    with app.app_context():
        bid, p = _batch_with_project("Imported")
        pid, rt_id = p.id, _recurring("imported routine", p).id

    _archive_patch(authed_client, pid)

    with app.app_context():
        assert _state(rt_id) == (False, True)
        recycle_service.undo_batch(bid)
        recycle_service.restore_batch(bid)

        assert db.session.get(Project, pid).is_active is False
        assert _state(rt_id) == (False, True)

    _unarchive(authed_client, pid)
    with app.app_context():
        assert db.session.get(Project, pid).is_active is True
        assert _state(rt_id) == (True, False)


def test_restore_batch_leaves_user_paused_template_paused(app):
    with app.app_context():
        bid, p = _batch_with_project("Imported")
        rt_id = _recurring("paused by me", p, is_active=False).id

        recycle_service.undo_batch(bid)
        recycle_service.restore_batch(bid)

        assert _state(rt_id) == (False, False)


def test_undo_restore_leave_goal_links_alone(app):
    # Spec §1: goals already follow the keep-links rule. Pinned so a
    # future change to goals is deliberate (that's #368's job).
    with app.app_context():
        bid, p = _batch_with_project("Imported")
        batch_goal = Goal(title="Imported goal", category=GoalCategory.WORK,
                          priority=GoalPriority.SHOULD, batch_id=bid)
        outside = Goal(title="Mine", category=GoalCategory.WORK,
                       priority=GoalPriority.MUST)
        db.session.add_all([batch_goal, outside])
        db.session.commit()
        t_out = Task(title="a", type=TaskType.WORK, tier=Tier.INBOX,
                     project_id=p.id, goal_id=outside.id)
        t_batch = Task(title="b", type=TaskType.WORK, tier=Tier.INBOX,
                       goal_id=batch_goal.id)
        db.session.add_all([t_out, t_batch])
        db.session.commit()
        rt_id = _recurring("routine", p, goal_id=outside.id).id
        want = {t_out.id: outside.id, t_batch.id: batch_goal.id}

        for step in (recycle_service.undo_batch, recycle_service.restore_batch):
            step(bid)
            for tid, gid in want.items():
                assert db.session.get(Task, tid).goal_id == gid
            assert db.session.get(RecurringTask, rt_id).goal_id == outside.id


# Purge hard-deletes the project, and the DB's ON DELETE SET NULL nulls
# the template's project_id. SQLite only enforces that with the pragma
# on (the tests/test_recycle_bin.py:552 pattern); Postgres always does.


def _fk_on():
    db.session.execute(sa.text("PRAGMA foreign_keys=ON"))


def test_purge_batch_clears_flag_on_templates_of_purged_projects(app):
    # The flag promises "resumes when the project is unarchived". Once the
    # project is gone that can't happen, so the template becomes an
    # ordinary paused one. It is NOT resumed: a template whose project
    # the user permanently deleted shouldn't start firing into no project.
    with app.app_context():
        _fk_on()
        bid, p = _batch_with_project("Imported")
        rt_id = _recurring("imported routine", p).id
        recycle_service.undo_batch(bid)
        assert _state(rt_id) == (False, True)

        recycle_service.purge_batch(bid, "DELETE")

        rt = db.session.get(RecurringTask, rt_id)
        db.session.refresh(rt)
        assert rt.project_id is None
        assert (rt.is_active, rt.paused_by_project_archive) == (False, False)


def test_purge_leaves_a_user_resumed_template_running(authed_client, app):
    # Review Focus 2: resumed by hand while the project sat in the bin,
    # so the flag is already clear. Purge changes nothing about it except
    # the DB nulling its project link.
    with app.app_context():
        bid, p = _batch_with_project("Imported")
        rt_id = _recurring("keep running", p).id
        recycle_service.undo_batch(bid)

    authed_client.patch(f"/api/recurring/{rt_id}", json={"is_active": True})

    with app.app_context():
        _fk_on()
        recycle_service.purge_batch(bid, "DELETE")

        rt = db.session.get(RecurringTask, rt_id)
        db.session.refresh(rt)
        assert rt.project_id is None
        assert (rt.is_active, rt.paused_by_project_archive) == (True, False)


def test_purge_never_touches_goal_links(app):
    # Review Focus 4, purge half (final-review finding): only project_id
    # is DB-nulled. A template and a hand-made task on the purged project
    # keep a goal that lives OUTSIDE the batch.
    with app.app_context():
        _fk_on()
        bid, p = _batch_with_project("Imported")
        outside = Goal(title="Mine", category=GoalCategory.WORK,
                       priority=GoalPriority.MUST)
        db.session.add(outside)
        db.session.commit()
        t = Task(title="mine", type=TaskType.WORK, tier=Tier.INBOX,
                 project_id=p.id, goal_id=outside.id)
        db.session.add(t)
        db.session.commit()
        tid, gid = t.id, outside.id
        rt_id = _recurring("routine", p, goal_id=gid).id
        recycle_service.undo_batch(bid)

        recycle_service.purge_batch(bid, "DELETE")

        rt = db.session.get(RecurringTask, rt_id)
        db.session.refresh(rt)
        assert (rt.project_id, rt.goal_id) == (None, gid)
        task = db.session.get(Task, tid)
        db.session.refresh(task)
        assert (task.project_id, task.goal_id) == (None, gid)


def test_empty_bin_clears_flags_across_batches(app):
    # Review Focus 3: empty_bin loops purge_batch, so it inherits the
    # flag clearing for every batch in the bin.
    with app.app_context():
        _fk_on()
        rts = []
        for name in ("First import", "Second import"):
            bid, p = _batch_with_project(name)
            rts.append(_recurring(f"{name} routine", p).id)
            recycle_service.undo_batch(bid)

        result = recycle_service.empty_bin("DELETE")

        assert result["batches_purged"] == 2
        for rt_id in rts:
            assert _state(rt_id) == (False, False)
