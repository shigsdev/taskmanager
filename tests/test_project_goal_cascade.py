"""#350: moving a project to another goal re-points its tasks' goals.

Why this exists at all. #77 settled the rule with an explicit user
scoping decision, recorded verbatim in the header of
`scripts/backfill_task_goal_from_project.py`:

    "always overwrite + go back and update any missing. After this
     script runs, all task<-project<-goal links are consistent."

`update_task` has honoured that since #77 — assigning a project copies
the project's goal onto the task. `update_project` never did. So the
invariant held when you edited the TASK and silently broke when you
edited the PROJECT, and the repo shipped two tools to repair the drift
afterwards (that backfill script and
`/api/debug/backfill-task-goal-from-project`). A repair tool for a
drift is the drift being a bug.

#343 made it easy to cause: changing a project's goal used to mean
opening the detail panel, and is now a drag.

The null case is deliberate and is NOT the PR24 "silent data loss"
case. PR24 was about assigning a task to a project that happens to
have no goal — the goal is incidental there, so overwriting it with
None destroys an unrelated choice. Dragging a project OUT of a goal is
the opposite: the goal is precisely what the user is changing, so
cascading it honours the intent. The backfill script already takes the
same line (`new_goal_id = proj.goal_id  # may be None`).
"""
from __future__ import annotations

from datetime import date

from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    Project,
    RecurringFrequency,
    RecurringTask,
    Task,
    TaskStatus,
    TaskType,
    Tier,
    db,
)
from recurring_service import spawn_today_tasks


def _goal(title: str) -> Goal:
    g = Goal(title=title, category=GoalCategory.WORK, priority=GoalPriority.MUST)
    db.session.add(g)
    db.session.commit()
    return g


def _project(name: str, goal: Goal | None = None) -> Project:
    p = Project(name=name, goal_id=goal.id if goal else None)
    db.session.add(p)
    db.session.commit()
    return p


def _task(title: str, project: Project | None, goal: Goal | None, **kw) -> Task:
    t = Task(
        title=title,
        type=kw.pop("type", TaskType.WORK),
        tier=kw.pop("tier", Tier.INBOX),
        project_id=project.id if project else None,
        goal_id=goal.id if goal else None,
        **kw,
    )
    db.session.add(t)
    db.session.commit()
    return t


# --- the move realigns -------------------------------------------------------


def test_moving_a_project_repoints_its_tasks(authed_client, app):
    with app.app_context():
        old, new = _goal("Old"), _goal("New")
        proj = _project("Mover", old)
        a = _task("A", proj, old)
        b = _task("B", proj, old)
        ids, new_id = (a.id, b.id), new.id
        proj_id = proj.id

    resp = authed_client.patch(
        f"/api/projects/{proj_id}", json={"goal_id": str(new_id)}
    )
    assert resp.status_code == 200

    with app.app_context():
        for tid in ids:
            assert db.session.get(Task, tid).goal_id == new_id


def test_tasks_with_no_goal_gain_the_projects_goal(authed_client, app):
    with app.app_context():
        g = _goal("Target")
        proj = _project("Mover", None)
        t = _task("Loose", proj, None)
        tid, gid, pid = t.id, g.id, proj.id

    authed_client.patch(f"/api/projects/{pid}", json={"goal_id": str(gid)})

    with app.app_context():
        assert db.session.get(Task, tid).goal_id == gid


def test_a_task_pointed_elsewhere_is_overwritten(authed_client, app):
    # "Always overwrite" is the recorded decision, not an accident: a
    # task's goal is not allowed to drift from its project's.
    with app.app_context():
        home, stray, dest = _goal("Home"), _goal("Stray"), _goal("Dest")
        proj = _project("Mover", home)
        t = _task("Deliberately elsewhere", proj, stray)
        tid, pid, dest_id = t.id, proj.id, dest.id

    authed_client.patch(f"/api/projects/{pid}", json={"goal_id": str(dest_id)})

    with app.app_context():
        assert db.session.get(Task, tid).goal_id == dest_id


# --- the destructive direction ----------------------------------------------


def test_unassigning_a_project_clears_its_tasks_goals(authed_client, app):
    # The user's call, against the recommendation, and the better
    # argument: dragging a project out of a goal is an explicit statement
    # about that goal, so the cascade honours intent rather than
    # destroying it. Matches the backfill script.
    with app.app_context():
        g = _goal("Leaving")
        proj = _project("Mover", g)
        t = _task("A", proj, g)
        tid, pid = t.id, proj.id

    resp = authed_client.patch(f"/api/projects/{pid}", json={"goal_id": None})
    assert resp.status_code == 200

    with app.app_context():
        assert db.session.get(Task, tid).goal_id is None


# --- blast radius: what it must NOT touch ------------------------------------


def test_cascade_does_not_touch_other_projects_tasks(authed_client, app):
    with app.app_context():
        old, new, other = _goal("Old"), _goal("New"), _goal("Other")
        mover = _project("Mover", old)
        bystander = _project("Bystander", other)
        moved = _task("Moved", mover, old)
        untouched = _task("Untouched", bystander, other)
        loose = _task("Loose", None, other)
        moved_id, untouched_id, loose_id = moved.id, untouched.id, loose.id
        pid, new_id, other_id = mover.id, new.id, other.id

    authed_client.patch(f"/api/projects/{pid}", json={"goal_id": str(new_id)})

    with app.app_context():
        assert db.session.get(Task, moved_id).goal_id == new_id
        assert db.session.get(Task, untouched_id).goal_id == other_id
        assert db.session.get(Task, loose_id).goal_id == other_id


def test_no_cascade_when_goal_id_is_absent_from_the_payload(authed_client, app):
    # Renaming a project must not rewrite task rows. update_project only
    # acts on keys it is given, and the cascade lives inside that branch.
    with app.app_context():
        g, stray = _goal("Home"), _goal("Stray")
        proj = _project("Mover", g)
        t = _task("Elsewhere", proj, stray)
        tid, pid, stray_id = t.id, proj.id, stray.id

    resp = authed_client.patch(f"/api/projects/{pid}", json={"name": "Renamed"})
    assert resp.status_code == 200

    with app.app_context():
        assert db.session.get(Task, tid).goal_id == stray_id


def test_no_cascade_when_the_goal_did_not_actually_change(authed_client, app):
    # The /projects detail panel sends goal_id on every save, so a
    # no-op save must stay a no-op — otherwise editing a project's
    # colour silently realigns its tasks. A deliberate re-sync is what
    # the backfill endpoint is for.
    with app.app_context():
        g, stray = _goal("Home"), _goal("Stray")
        proj = _project("Mover", g)
        t = _task("Elsewhere", proj, stray)
        tid, pid, gid, stray_id = t.id, proj.id, g.id, stray.id

    resp = authed_client.patch(
        f"/api/projects/{pid}", json={"name": "Recoloured", "goal_id": str(gid)}
    )
    assert resp.status_code == 200

    with app.app_context():
        assert db.session.get(Task, tid).goal_id == stray_id


def test_cascade_reaches_every_status_like_the_backfill_does(authed_client, app):
    # The backfill selects on project_id alone with no status filter, and
    # the invariant it defines is the one being maintained here. A
    # completed task that stayed behind would make the goal's own
    # completed-count wrong.
    with app.app_context():
        old, new = _goal("Old"), _goal("New")
        proj = _project("Mover", old)
        done = _task("Done", proj, old, status=TaskStatus.ARCHIVED)
        cancelled = _task("Cancelled", proj, old, status=TaskStatus.CANCELLED)
        done_id, cancelled_id, pid, new_id = done.id, cancelled.id, proj.id, new.id

    authed_client.patch(f"/api/projects/{pid}", json={"goal_id": str(new_id)})

    with app.app_context():
        assert db.session.get(Task, done_id).goal_id == new_id
        assert db.session.get(Task, cancelled_id).goal_id == new_id


# --- the other doors onto the same field -------------------------------------


def test_bulk_project_update_cascades_too(authed_client, app):
    # bulk_update_projects reuses update_project per row precisely so
    # cascade rules cannot diverge. Pinned so that stays true.
    with app.app_context():
        old, new = _goal("Old"), _goal("New")
        p1, p2 = _project("One", old), _project("Two", old)
        t1, t2 = _task("T1", p1, old), _task("T2", p2, old)
        ids = (t1.id, t2.id)
        pids = [str(p1.id), str(p2.id)]
        new_id = new.id

    resp = authed_client.patch(
        "/api/projects/bulk",
        json={"project_ids": pids, "updates": {"goal_id": str(new_id)}},
    )
    assert resp.status_code == 200

    with app.app_context():
        for tid in ids:
            assert db.session.get(Task, tid).goal_id == new_id


def test_deleting_a_project_preserves_task_project_and_goal(authed_client, app):
    # The one case that genuinely IS "independent intent", and the
    # distinction this whole change turns on. Archiving a project must
    # not drag its tasks off their goal — the project went away, the
    # user did not say anything about the goal. Unchanged by #350.
    # #353 / ADR-038: it no longer detaches them from the project either
    # (reversing PR63 #129), so Delete matches the Archive button.
    with app.app_context():
        g = _goal("Survives")
        proj = _project("Doomed", g)
        t = _task("Orphan", proj, g)
        tid, pid, gid = t.id, proj.id, g.id

    resp = authed_client.delete(f"/api/projects/{pid}")
    assert resp.status_code == 204

    with app.app_context():
        task = db.session.get(Task, tid)
        assert task.project_id == pid
        assert task.goal_id == gid


# --- #352: the cascade has to reach recurring templates ----------------------
#
# `RecurringTask` carries its OWN `goal_id`, and `spawn_today_tasks`
# copies it onto every task it creates (`recurring_service.py:676`). So
# a template left behind by the #350 cascade does not just hold a stale
# value — it re-stamps the OLD goal onto a brand-new task every time it
# fires. #350's invariant would hold the moment you dragged the project
# and then decay on a timer, which is strictly worse than the drift it
# was written to fix, because it is self-renewing.
#
# Found on the live data: a 394-task "BAU" project whose "Evening prep"
# template sat on the WORK goal while every other personal routine on
# the same project sat on no goal. One mis-set template field had
# stamped 122 task rows.


def _recurring(title: str, project: Project | None, goal: Goal | None, **kw):
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


def test_moving_a_project_repoints_its_recurring_templates(authed_client, app):
    with app.app_context():
        old, new = _goal("Old"), _goal("New")
        proj = _project("Mover", old)
        rt = _recurring("Evening prep", proj, old)
        rt_id, new_id, proj_id = rt.id, new.id, proj.id

    resp = authed_client.patch(
        f"/api/projects/{proj_id}", json={"goal_id": str(new_id)}
    )
    assert resp.status_code == 200

    with app.app_context():
        assert db.session.get(RecurringTask, rt_id).goal_id == new_id


def test_future_spawns_land_on_the_new_goal(authed_client, app):
    # The one that actually matters. Re-pointing the template row is
    # only the mechanism; this asserts the user-visible consequence,
    # which is that tomorrow's task arrives on the right goal.
    with app.app_context():
        old, new = _goal("Old"), _goal("New")
        proj = _project("Routines", old)
        _recurring("Morning Prep", proj, old)
        new_id, proj_id = new.id, proj.id

    assert authed_client.patch(
        f"/api/projects/{proj_id}", json={"goal_id": str(new_id)}
    ).status_code == 200

    with app.app_context():
        spawned = spawn_today_tasks(target_date=date(2026, 10, 2))
        assert len(spawned) == 1
        assert spawned[0].goal_id == new_id


def test_a_template_whose_goal_was_wrong_is_corrected_by_the_move(
    authed_client, app
):
    # The live shape: the project has NO goal, one template sits on a
    # goal nothing else on the project uses. Filing the project under
    # its real goal has to fix the template too, or the next spawn
    # re-opens the hole the move just closed.
    with app.app_context():
        work_bau, personal_bau = _goal("Work BAU"), _goal("Personal BAU")
        proj = _project("BAU", None)
        evening = _recurring("Evening prep", proj, work_bau)
        morning = _recurring("Morning Prep", proj, None)
        ids = (evening.id, morning.id)
        dest, proj_id = personal_bau.id, proj.id

    assert authed_client.patch(
        f"/api/projects/{proj_id}", json={"goal_id": str(dest)}
    ).status_code == 200

    with app.app_context():
        for rt_id in ids:
            assert db.session.get(RecurringTask, rt_id).goal_id == dest


def test_unassigning_a_project_clears_its_templates_goals(authed_client, app):
    # Same rule as tasks, by the user's #350 decision: clearing a
    # project's goal is a direct statement about that goal.
    with app.app_context():
        g = _goal("Dropped")
        proj = _project("Loose", g)
        rt = _recurring("Laundry", proj, g)
        rt_id, proj_id = rt.id, proj.id

    resp = authed_client.patch(f"/api/projects/{proj_id}", json={"goal_id": None})
    assert resp.status_code == 200

    with app.app_context():
        assert db.session.get(RecurringTask, rt_id).goal_id is None


def test_no_template_cascade_when_the_goal_did_not_change(authed_client, app):
    # The /projects detail panel sends goal_id on EVERY save, so a
    # rename or a recolour must not quietly rewrite template rows. Same
    # change-only guard the task cascade uses.
    with app.app_context():
        g, other = _goal("Kept"), _goal("Unrelated")
        proj = _project("Stable", g)
        # Deliberately NOT the project's goal: a hand-set template goal
        # that a recolour has no business overwriting.
        rt = _recurring("Hand-set", proj, other)
        rt_id, proj_id, other_id, same_goal = rt.id, proj.id, other.id, g.id

    resp = authed_client.patch(
        f"/api/projects/{proj_id}",
        json={"goal_id": str(same_goal), "color": "#ff0000"},
    )
    assert resp.status_code == 200

    with app.app_context():
        assert db.session.get(RecurringTask, rt_id).goal_id == other_id


def test_templates_on_another_project_are_untouched(authed_client, app):
    with app.app_context():
        a, b = _goal("A"), _goal("B")
        mine, theirs = _project("Mine", a), _project("Theirs", a)
        kept = _recurring("Not mine", theirs, a)
        kept_id, b_id, mine_id, a_id = kept.id, b.id, mine.id, a.id

    assert authed_client.patch(
        f"/api/projects/{mine_id}", json={"goal_id": str(b_id)}
    ).status_code == 200

    with app.app_context():
        assert db.session.get(RecurringTask, kept_id).goal_id == a_id


def test_a_template_with_no_project_is_never_touched(authed_client, app):
    # Project-less templates exist on the live data ("Meds", "Weekly
    # Reflection", "Clean out CPAP"). A project move must not sweep
    # them up — nothing links them to it.
    with app.app_context():
        a, b = _goal("A"), _goal("B")
        proj = _project("Mover", a)
        loose = _recurring("Weekly Reflection", None, a)
        loose_id, b_id, proj_id, a_id = loose.id, b.id, proj.id, a.id

    assert authed_client.patch(
        f"/api/projects/{proj_id}", json={"goal_id": str(b_id)}
    ).status_code == 200

    with app.app_context():
        assert db.session.get(RecurringTask, loose_id).goal_id == a_id


def test_bulk_project_update_cascades_to_templates_too(authed_client, app):
    # bulk_update_projects reuses update_project per row, so this is
    # inherited rather than reimplemented — pinned so a future refactor
    # that inlines the logic cannot drop it.
    with app.app_context():
        old, new = _goal("Old"), _goal("New")
        p1, p2 = _project("One", old), _project("Two", old)
        r1, r2 = _recurring("R1", p1, old), _recurring("R2", p2, old)
        ids = (r1.id, r2.id)
        payload = {
            "project_ids": [str(p1.id), str(p2.id)],
            "updates": {"goal_id": str(new.id)},
        }
        new_id = new.id

    resp = authed_client.patch("/api/projects/bulk", json=payload)
    assert resp.status_code == 200

    with app.app_context():
        for rt_id in ids:
            assert db.session.get(RecurringTask, rt_id).goal_id == new_id


def test_archiving_a_project_leaves_template_goals_alone(authed_client, app):
    # Mirrors test_deleting_a_project_still_leaves_task_goals_alone:
    # the project went away, the user said nothing about the goal.
    with app.app_context():
        g = _goal("Survives")
        proj = _project("Doomed", g)
        rt = _recurring("Still mine", proj, g)
        rt_id, pid, gid = rt.id, proj.id, g.id

    assert authed_client.delete(f"/api/projects/{pid}").status_code == 204

    with app.app_context():
        assert db.session.get(RecurringTask, rt_id).goal_id == gid
