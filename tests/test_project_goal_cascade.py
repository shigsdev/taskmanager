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

from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    Project,
    Task,
    TaskStatus,
    TaskType,
    Tier,
    db,
)


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


def test_deleting_a_project_still_leaves_task_goals_alone(authed_client, app):
    # The one case that genuinely IS "independent intent", and the
    # distinction this whole change turns on. Archiving a project
    # detaches its tasks (PR63 #129) but must not drag them off their
    # goal — the project went away, the user did not say anything about
    # the goal. Unchanged by #350.
    with app.app_context():
        g = _goal("Survives")
        proj = _project("Doomed", g)
        t = _task("Orphan", proj, g)
        tid, pid, gid = t.id, proj.id, g.id

    resp = authed_client.delete(f"/api/projects/{pid}")
    assert resp.status_code == 204

    with app.app_context():
        task = db.session.get(Task, tid)
        assert task.project_id is None
        assert task.goal_id == gid
