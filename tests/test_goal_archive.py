"""#349: archive / unarchive a goal, and a hard delete that cannot orphan.

The bug this closes. `delete_goal` has always been a SOFT delete — it
sets `is_active=False` — but the button said **Delete**, `goalsRender`
hard-filtered to active goals with no filter control, and there was no
unarchive anywhere. So pressing it made a goal permanently invisible and
unrecoverable from the UI while the row lived on in the database. Worse,
`delete_goal` also clears `batch_id` on purpose, so even the recycle-bin
restore path would not bring it back.

A button labelled Delete that silently archives is the worst of both
readings at once: whoever wanted it gone believes it is gone, and
whoever wants it back has no route.

The hard delete is guarded rather than confirmed. FOUR models carry a
`goal_id` — Project, Task, RecurringTask and WeeklyFocus — and only
`Task.goal_id` lacks `ondelete="SET NULL"`, so a raw delete would
hard-fail on tasks and SILENTLY null the other three. Silently nulling
a project's goal because its goal was deleted is precisely the class of
invisible data change #350/#351 exist to stop, so the guard refuses the
delete and names what is in the way instead of letting the database
quietly decide.

Archive-before-delete is a deliberate second gate: it makes the
destructive path two deliberate steps, and it means any goal reaching
the hard delete has already had `batch_id` cleared by `delete_goal`, so
a hard delete can never strand a live import batch.
"""
from __future__ import annotations

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
    WeeklyFocus,
    db,
)


def _goal(title: str, *, active: bool = True) -> Goal:
    g = Goal(
        title=title,
        category=GoalCategory.WORK,
        priority=GoalPriority.MUST,
        is_active=active,
    )
    db.session.add(g)
    db.session.commit()
    return g


# --- archive / unarchive is just update_goal ---------------------------------


def test_archiving_a_goal_hides_it_from_the_default_list(authed_client, app):
    with app.app_context():
        gid = _goal("Archive me").id

    assert authed_client.patch(
        f"/api/goals/{gid}", json={"is_active": False}
    ).status_code == 200

    titles = [x["title"] for x in authed_client.get("/api/goals").get_json()]
    assert "Archive me" not in titles


def test_an_archived_goal_is_still_reachable_with_is_active_all(authed_client, app):
    # This is the whole point of archiving rather than deleting: the row
    # has to be findable again, or Unarchive has nothing to act on.
    with app.app_context():
        gid = _goal("Archive me", active=False).id

    rows = authed_client.get("/api/goals?is_active=all").get_json()
    assert str(gid) in [x["id"] for x in rows]


def test_unarchiving_brings_it_back(authed_client, app):
    with app.app_context():
        gid = _goal("Back from the dead", active=False).id

    assert authed_client.patch(
        f"/api/goals/{gid}", json={"is_active": True}
    ).status_code == 200

    titles = [x["title"] for x in authed_client.get("/api/goals").get_json()]
    assert "Back from the dead" in titles


def test_delete_still_archives_rather_than_removing(authed_client, app):
    # DELETE /api/goals/<id> is unchanged — it is the Archive action.
    # Only the label changes, so an in-flight client cannot be surprised.
    with app.app_context():
        gid = _goal("Soft").id

    assert authed_client.delete(f"/api/goals/{gid}").status_code == 204

    with app.app_context():
        row = db.session.get(Goal, gid)
        assert row is not None
        assert row.is_active is False


# --- the hard delete, and everything that blocks it --------------------------


def test_hard_delete_removes_an_archived_unreferenced_goal(authed_client, app):
    with app.app_context():
        gid = _goal("Nothing points here", active=False).id

    resp = authed_client.delete(f"/api/goals/{gid}/permanent")
    assert resp.status_code == 204

    with app.app_context():
        assert db.session.get(Goal, gid) is None


def test_hard_delete_refuses_an_ACTIVE_goal(authed_client, app):
    # Archive-before-delete: two deliberate steps, not one click.
    with app.app_context():
        gid = _goal("Still live").id

    resp = authed_client.delete(f"/api/goals/{gid}/permanent")
    assert resp.status_code == 409
    assert "archive" in resp.get_json()["error"].lower()

    with app.app_context():
        assert db.session.get(Goal, gid) is not None


def test_hard_delete_refuses_when_a_TASK_points_at_it(authed_client, app):
    with app.app_context():
        g = _goal("Has a task", active=False)
        db.session.add(Task(
            title="Clinger", type=TaskType.WORK, tier=Tier.INBOX, goal_id=g.id,
        ))
        db.session.commit()
        gid = g.id

    resp = authed_client.delete(f"/api/goals/{gid}/permanent")
    assert resp.status_code == 409
    assert resp.get_json()["references"]["tasks"] == 1

    with app.app_context():
        assert db.session.get(Goal, gid) is not None


def test_a_COMPLETED_task_still_blocks_the_delete(authed_client, app):
    # The reference count must not filter by status. An archived task
    # holds the same foreign key as an active one, and Task.goal_id has
    # no ondelete clause, so the DB would raise rather than tidy up.
    with app.app_context():
        g = _goal("Has history", active=False)
        db.session.add(Task(
            title="Done long ago", type=TaskType.WORK, tier=Tier.INBOX,
            goal_id=g.id, status=TaskStatus.ARCHIVED,
        ))
        db.session.commit()
        gid = g.id

    resp = authed_client.delete(f"/api/goals/{gid}/permanent")
    assert resp.status_code == 409
    assert resp.get_json()["references"]["tasks"] == 1


def test_hard_delete_refuses_when_a_PROJECT_points_at_it(authed_client, app):
    with app.app_context():
        g = _goal("Has a project", active=False)
        db.session.add(Project(name="Clinger", goal_id=g.id))
        db.session.commit()
        gid = g.id

    resp = authed_client.delete(f"/api/goals/{gid}/permanent")
    assert resp.status_code == 409
    assert resp.get_json()["references"]["projects"] == 1


def test_hard_delete_refuses_when_a_TEMPLATE_points_at_it(authed_client, app):
    with app.app_context():
        g = _goal("Has a template", active=False)
        db.session.add(RecurringTask(
            title="Clinger", frequency=RecurringFrequency.DAILY,
            type=TaskType.WORK, goal_id=g.id,
        ))
        db.session.commit()
        gid = g.id

    resp = authed_client.delete(f"/api/goals/{gid}/permanent")
    assert resp.status_code == 409
    assert resp.get_json()["references"]["recurring"] == 1


def test_hard_delete_refuses_when_a_WEEKLY_FOCUS_points_at_it(authed_client, app):
    # The reference I nearly missed. WeeklyFocus.goal_id is the fourth
    # goal foreign key and the least visible of them; its ondelete is
    # SET NULL, so leaving it out of the guard would have silently
    # emptied a past week's focus with nothing shown to the user.
    from datetime import date

    with app.app_context():
        g = _goal("Was a focus", active=False)
        db.session.add(WeeklyFocus(
            goal_id=g.id, week_start_date=date(2026, 9, 28), slot_order=0,
            text="Ship the thing",
        ))
        db.session.commit()
        gid = g.id

    resp = authed_client.delete(f"/api/goals/{gid}/permanent")
    assert resp.status_code == 409
    assert resp.get_json()["references"]["weekly_focus"] == 1

    with app.app_context():
        assert db.session.get(Goal, gid) is not None


def test_the_refusal_reports_every_blocker_at_once(authed_client, app):
    # One round trip tells you everything to clear, rather than making
    # you discover the blockers one delete at a time.
    with app.app_context():
        g = _goal("Popular", active=False)
        db.session.add(Task(
            title="t", type=TaskType.WORK, tier=Tier.INBOX, goal_id=g.id))
        db.session.add(Project(name="p", goal_id=g.id))
        db.session.add(RecurringTask(
            title="r", frequency=RecurringFrequency.DAILY,
            type=TaskType.WORK, goal_id=g.id))
        db.session.commit()
        gid = g.id

    refs = authed_client.delete(
        f"/api/goals/{gid}/permanent").get_json()["references"]
    assert refs["tasks"] == 1
    assert refs["projects"] == 1
    assert refs["recurring"] == 1
    assert refs["weekly_focus"] == 0


def test_hard_delete_404s_on_an_unknown_goal(authed_client):
    resp = authed_client.delete(
        "/api/goals/0f0f0f0f-0f0f-4f0f-8f0f-0f0f0f0f0f0f/permanent")
    assert resp.status_code == 404


def test_hard_delete_is_not_reachable_by_GET(authed_client, app):
    # #190: a state-mutating GET is a CSRF surface — SameSite=Lax does
    # not block a top-level cross-origin GET, so an <img src> would fire
    # it. This route must reject GET outright.
    with app.app_context():
        gid = _goal("Guarded", active=False).id

    assert authed_client.get(f"/api/goals/{gid}/permanent").status_code == 405

    with app.app_context():
        assert db.session.get(Goal, gid) is not None


def test_archiving_then_hard_deleting_cannot_strand_an_import_batch(
    authed_client, app
):
    # delete_goal clears batch_id on purpose, and archive-before-delete
    # means every hard delete goes through it. So a hard-deleted goal is
    # never still claimed by a restorable batch.
    import uuid as _uuid

    with app.app_context():
        g = _goal("Imported")
        g.batch_id = _uuid.uuid4()
        db.session.commit()
        gid = g.id

    assert authed_client.delete(f"/api/goals/{gid}").status_code == 204
    with app.app_context():
        assert db.session.get(Goal, gid).batch_id is None

    assert authed_client.delete(f"/api/goals/{gid}/permanent").status_code == 204
    with app.app_context():
        assert db.session.get(Goal, gid) is None


# --- archiving has to mean hidden, including in the digest -------------------


def test_the_digest_leaves_out_an_archived_goal(app):
    # Found while building this. digest_service grouped goals by
    # `status != DONE` and never looked at is_active, so an archived
    # goal still turned up in the daily email. An archive that does not
    # hide is the same false promise as a Delete that does not delete.
    #
    # The precedent was already sitting next to the bug: PR62 audit fix
    # #14 added exactly this guard for inactive PROJECTS, in both the
    # grouped section and the per-task label. Goals only ever got the
    # `status != DONE` half.
    from datetime import date

    from digest_service import _build_digest_data

    with app.app_context():
        live = _goal("Live goal")
        dead = _goal("Archived goal", active=False)
        for goal, title in ((live, "live task"), (dead, "dead task")):
            db.session.add(Task(
                title=title, type=TaskType.WORK, tier=Tier.TODAY,
                goal_id=goal.id, due_date=date.today(),
            ))
        db.session.commit()

        data = _build_digest_data()

        # the grouped "goals you moved today" section
        titles = [row["title"] for row in data["goals_today"]]
        assert "Live goal" in titles
        assert "Archived goal" not in titles

        # ...and the per-task goal label, which is a separate code path
        labels = {v["title"]: v["goal"] for v in data["today"]}
        assert labels["live task"] == "Live goal"
        assert labels["dead task"] is None
