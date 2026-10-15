"""#475 — a project or goal link on a write is checked.

A NEW link to a project or goal that doesn't exist, is archived, or (for a
project) is of the other type is refused with a plain 422. A link that is
re-sent unchanged, or inherited (a subtask's from its parent, a task's goal
from its project), is not new and still saves. Changing a task's or a
template's type takes it off a project of the other type, as picking
"(no project)" would (#427).
"""
from __future__ import annotations

import uuid

from models import Project, RecurringTask, Task, db

MISSING_PROJECT = "That project no longer exists — pick another."
MISSING_GOAL = "That goal no longer exists — pick another."


def _archived_project_msg(name):
    return f'The project "{name}" is archived — unarchive it first.'


def _archived_goal_msg(title):
    return f'The goal "{title}" is archived — unarchive it first.'


def _type_msg(name, project_type, item_type, noun="task"):
    return (
        f'"{name}" is a {project_type} project and this is a {item_type} {noun}'
        f" — pick a {item_type} project or none."
    )


def _project(c, name, type_="work", goal_id=None):
    body = {"name": name, "type": type_}
    if goal_id:
        body["goal_id"] = goal_id
    r = c.post("/api/projects", json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id"]


def _goal(c, title):
    r = c.post("/api/goals", json={"title": title, "category": "work", "priority": "must"})
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id"]


def _archive(c, kind, id_):
    r = c.patch(f"/api/{kind}/{id_}", json={"is_active": False})
    assert r.status_code == 200, r.get_json()


def _task(c, **body):
    body.setdefault("title", "T")
    body.setdefault("type", "work")
    r = c.post("/api/tasks", json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id"]


def _template(c, **body):
    body.setdefault("title", "R")
    body.setdefault("type", "work")
    body.setdefault("frequency", "daily")
    r = c.post("/api/recurring", json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id"]


def _row(app, model, id_):
    with app.app_context():
        row = db.session.get(model, uuid.UUID(id_))
        return {
            "project_id": str(row.project_id) if getattr(row, "project_id", None) else None,
            "goal_id": str(row.goal_id) if row.goal_id else None,
            "type": getattr(row, "type", None),
        }


def _refused(r, msg, field):
    assert r.status_code == 422, r.get_json()
    assert r.get_json() == {"error": msg, "field": field}


GHOST = str(uuid.uuid4())


class TestTaskCreate:
    def test_missing_project_and_goal_refused(self, authed_client):
        c = authed_client
        _refused(c.post("/api/tasks", json={"title": "x", "type": "work", "project_id": GHOST}),
                 MISSING_PROJECT, "project_id")
        _refused(c.post("/api/tasks", json={"title": "x", "type": "work", "goal_id": GHOST}),
                 MISSING_GOAL, "goal_id")
        with c.application.app_context():
            assert Task.query.filter_by(title="x").count() == 0

    def test_archived_project_and_goal_refused(self, authed_client):
        c = authed_client
        pid = _project(c, "Old project")
        gid = _goal(c, "Old goal")
        _archive(c, "projects", pid)
        _archive(c, "goals", gid)
        _refused(c.post("/api/tasks", json={"title": "x", "type": "work", "project_id": pid}),
                 _archived_project_msg("Old project"), "project_id")
        _refused(c.post("/api/tasks", json={"title": "x", "type": "work", "goal_id": gid}),
                 _archived_goal_msg("Old goal"), "goal_id")

    def test_other_type_project_refused(self, authed_client):
        c = authed_client
        pid = _project(c, "Home", "personal")
        _refused(c.post("/api/tasks", json={"title": "x", "type": "work", "project_id": pid}),
                 _type_msg("Home", "personal", "work"), "project_id")

    def test_live_same_type_links_save(self, authed_client, app):
        c = authed_client
        gid = _goal(c, "G")
        pid = _project(c, "Home", "personal")
        tid = _task(c, type="personal", project_id=pid, goal_id=gid)
        assert _row(app, Task, tid)["project_id"] == pid
        assert _row(app, Task, tid)["goal_id"] == gid

    def test_subtask_inherits_archived_parent_links(self, authed_client, app):
        c = authed_client
        gid = _goal(c, "G")
        pid = _project(c, "P", goal_id=gid)
        parent = _task(c, project_id=pid)
        _archive(c, "projects", pid)
        _archive(c, "goals", gid)
        # The client sends the parent's links explicitly; the server also
        # inherits them. Neither is a NEW link.
        sid = _task(c, title="child", parent_id=parent, project_id=pid, goal_id=gid)
        assert _row(app, Task, sid)["project_id"] == pid
        assert _row(app, Task, sid)["goal_id"] == gid
        sid2 = _task(c, title="child2", parent_id=parent)
        assert _row(app, Task, sid2)["project_id"] == pid

    def test_archived_goal_cascades_from_its_project(self, authed_client, app):
        c = authed_client
        gid = _goal(c, "G")
        pid = _project(c, "P", goal_id=gid)
        _archive(c, "goals", gid)
        # Both the cascade (no goal_id) and a client that sends the
        # project's own goal along with it.
        t1 = _task(c, project_id=pid)
        t2 = _task(c, project_id=pid, goal_id=gid)
        assert _row(app, Task, t1)["goal_id"] == gid
        assert _row(app, Task, t2)["goal_id"] == gid


class TestTaskUpdate:
    def test_new_bad_links_refused_and_nothing_changes(self, authed_client, app):
        c = authed_client
        live = _project(c, "Live")
        tid = _task(c, project_id=live)
        old = _project(c, "Old")
        _archive(c, "projects", old)
        home = _project(c, "Home", "personal")
        g_old = _goal(c, "Old goal")
        _archive(c, "goals", g_old)
        cases = [
            ({"project_id": GHOST}, MISSING_PROJECT, "project_id"),
            ({"project_id": old}, _archived_project_msg("Old"), "project_id"),
            ({"project_id": home}, _type_msg("Home", "personal", "work"), "project_id"),
            ({"goal_id": GHOST}, MISSING_GOAL, "goal_id"),
            ({"goal_id": g_old}, _archived_goal_msg("Old goal"), "goal_id"),
        ]
        for body, msg, field in cases:
            _refused(c.patch(f"/api/tasks/{tid}", json={"title": "renamed", **body}), msg, field)
        with app.app_context():
            t = db.session.get(Task, uuid.UUID(tid))
            assert t.title == "T"
            assert str(t.project_id) == live

    def test_resent_archived_links_still_save(self, authed_client, app):
        c = authed_client
        gid = _goal(c, "G")
        pid = _project(c, "P", goal_id=gid)
        tid = _task(c, project_id=pid)
        _archive(c, "projects", pid)
        _archive(c, "goals", gid)
        r = c.patch(f"/api/tasks/{tid}",
                    json={"title": "edited", "project_id": pid, "goal_id": gid})
        assert r.status_code == 200, r.get_json()
        assert _row(app, Task, tid)["project_id"] == pid
        assert _row(app, Task, tid)["goal_id"] == gid

    def test_resent_mismatch_still_saves(self, authed_client, app):
        """A task already on a project of the other type (old data) keeps
        saving while neither its type nor its project changes."""
        c = authed_client
        home = _project(c, "Home", "personal")
        tid = _task(c)
        with app.app_context():
            db.session.get(Task, uuid.UUID(tid)).project_id = uuid.UUID(home)
            db.session.commit()
        r = c.patch(f"/api/tasks/{tid}",
                    json={"title": "edited", "type": "work", "project_id": home})
        assert r.status_code == 200, r.get_json()
        assert _row(app, Task, tid)["project_id"] == home

    def test_type_change_unlinks_other_type_project_and_its_goal(self, authed_client, app):
        c = authed_client
        gid = _goal(c, "G")
        pid = _project(c, "Work P", goal_id=gid)
        tid = _task(c, project_id=pid)
        # A client that re-sends the stored links with the new type.
        r = c.patch(f"/api/tasks/{tid}",
                    json={"type": "personal", "project_id": pid, "goal_id": gid})
        assert r.status_code == 200, r.get_json()
        assert _row(app, Task, tid)["project_id"] is None
        assert _row(app, Task, tid)["goal_id"] is None

    def test_type_change_keeps_a_hand_set_goal(self, authed_client, app):
        c = authed_client
        g_proj = _goal(c, "Project goal")
        g_mine = _goal(c, "My goal")
        pid = _project(c, "Work P", goal_id=g_proj)
        tid = _task(c, project_id=pid, goal_id=g_mine)
        r = c.patch(f"/api/tasks/{tid}", json={"type": "personal"})
        assert r.status_code == 200, r.get_json()
        assert _row(app, Task, tid)["project_id"] is None
        assert _row(app, Task, tid)["goal_id"] == g_mine

    def test_type_change_with_a_new_matching_project(self, authed_client, app):
        c = authed_client
        work = _project(c, "Work P")
        home = _project(c, "Home", "personal")
        tid = _task(c, project_id=work)
        r = c.patch(f"/api/tasks/{tid}", json={"type": "personal", "project_id": home})
        assert r.status_code == 200, r.get_json()
        assert _row(app, Task, tid)["project_id"] == home
        # ... and the old project for the NEW type is refused.
        _refused(c.patch(f"/api/tasks/{tid}", json={"project_id": work}),
                 _type_msg("Work P", "work", "personal"), "project_id")

    def test_bulk_type_change_unlinks(self, authed_client, app):
        c = authed_client
        pid = _project(c, "Work P")
        t1 = _task(c, project_id=pid)
        t2 = _task(c)
        r = c.patch("/api/tasks/bulk", json={"task_ids": [t1, t2], "updates": {"type": "personal"}})
        assert r.get_json()["updated"] == 2
        assert _row(app, Task, t1)["project_id"] is None

    def test_bulk_reports_a_refused_row(self, authed_client, app):
        c = authed_client
        home = _project(c, "Home", "personal")
        work_task = _task(c)
        home_task = _task(c, type="personal")
        r = c.patch("/api/tasks/bulk", json={
            "task_ids": [work_task, home_task], "updates": {"project_id": home},
        })
        body = r.get_json()
        assert body["updated"] == 1
        assert body["errors"] == [{
            "id": work_task, "field": "project_id",
            "message": _type_msg("Home", "personal", "work"),
        }]
        assert _row(app, Task, work_task)["project_id"] is None
        assert _row(app, Task, home_task)["project_id"] == home

    def test_repeat_on_a_task_in_an_archived_project_refused(self, authed_client, app):
        c = authed_client
        pid = _project(c, "P")
        tid = _task(c, project_id=pid)
        _archive(c, "projects", pid)
        _refused(c.patch(f"/api/tasks/{tid}", json={"repeat": {"frequency": "daily"}}),
                 _archived_project_msg("P"), "project_id")
        with app.app_context():
            assert RecurringTask.query.count() == 0


class TestCaptureHint:
    def test_hint_prefers_own_type(self, authed_client, app):
        c = authed_client
        _project(c, "Garden work", "work")
        home = _project(c, "Garden home", "personal")
        r = c.post("/api/tasks", json={"title": "x", "type": "personal", "project_hint": "garden"})
        assert r.status_code == 201
        assert r.get_json()["project_id"] == home
        assert "warning" not in r.get_json()

    def test_other_type_only_match_warns(self, authed_client):
        c = authed_client
        _project(c, "Roadmaps", "work")
        r = c.post("/api/tasks", json={"title": "x", "type": "personal", "project_hint": "road"})
        assert r.status_code == 201
        body = r.get_json()
        assert body["project_id"] is None
        assert body["warning"] == (
            '"@road" matches Roadmaps, a work project — task created without a project.'
        )


class TestRecurring:
    def test_create_refusals(self, authed_client):
        c = authed_client
        old = _project(c, "Old")
        _archive(c, "projects", old)
        home = _project(c, "Home", "personal")
        g_old = _goal(c, "Old goal")
        _archive(c, "goals", g_old)
        base = {"title": "R", "type": "work", "frequency": "daily"}
        for body, msg, field in [
            ({"project_id": GHOST}, MISSING_PROJECT, "project_id"),
            ({"project_id": old}, _archived_project_msg("Old"), "project_id"),
            ({"project_id": home}, _type_msg("Home", "personal", "work", "template"), "project_id"),
            ({"goal_id": GHOST}, MISSING_GOAL, "goal_id"),
            ({"goal_id": g_old}, _archived_goal_msg("Old goal"), "goal_id"),
        ]:
            _refused(c.post("/api/recurring", json={**base, **body}), msg, field)
        with c.application.app_context():
            assert RecurringTask.query.count() == 0

    def test_update_refused_resent_saves(self, authed_client, app):
        c = authed_client
        gid = _goal(c, "G")
        pid = _project(c, "P", goal_id=gid)
        rid = _template(c, project_id=pid, goal_id=gid)
        _archive(c, "projects", pid)
        home = _project(c, "Home", "personal")
        # Re-sent (the /recurring editor sends both on every Save).
        r = c.patch(f"/api/recurring/{rid}",
                    json={"title": "R2", "project_id": pid, "goal_id": gid})
        assert r.status_code == 200, r.get_json()
        _refused(c.patch(f"/api/recurring/{rid}", json={"project_id": home}),
                 _type_msg("Home", "personal", "work", "template"), "project_id")
        _refused(c.patch(f"/api/recurring/{rid}", json={"goal_id": GHOST}), MISSING_GOAL, "goal_id")
        assert _row(app, RecurringTask, rid)["project_id"] == pid

    def test_type_change_unlinks(self, authed_client, app):
        c = authed_client
        gid = _goal(c, "G")
        pid = _project(c, "Work P", goal_id=gid)
        rid = _template(c, project_id=pid, goal_id=gid)
        r = c.patch(f"/api/recurring/{rid}",
                    json={"type": "personal", "project_id": pid, "goal_id": gid})
        assert r.status_code == 200, r.get_json()
        assert _row(app, RecurringTask, rid)["project_id"] is None
        assert _row(app, RecurringTask, rid)["goal_id"] is None

    def test_bulk_reports_a_refused_row(self, authed_client):
        c = authed_client
        home = _project(c, "Home", "personal")
        work_rt = _template(c)
        home_rt = _template(c, type="personal")
        r = c.patch("/api/recurring/bulk", json={
            "template_ids": [work_rt, home_rt], "updates": {"project_id": home},
        })
        body = r.get_json()
        assert body["updated"] == 1
        assert body["errors"] == [{
            "id": work_rt, "field": "project_id",
            "error": _type_msg("Home", "personal", "work", "template"),
        }]


class TestProjectGoal:
    def test_create_refusals(self, authed_client):
        c = authed_client
        g_old = _goal(c, "Old goal")
        _archive(c, "goals", g_old)
        _refused(c.post("/api/projects", json={"name": "P", "goal_id": GHOST}),
                 MISSING_GOAL, "goal_id")
        _refused(c.post("/api/projects", json={"name": "P", "goal_id": g_old}),
                 _archived_goal_msg("Old goal"), "goal_id")
        with c.application.app_context():
            assert Project.query.filter_by(name="P").count() == 0

    def test_update_refused_resent_saves(self, authed_client, app):
        c = authed_client
        gid = _goal(c, "G")
        pid = _project(c, "P", goal_id=gid)
        tid = _task(c, project_id=pid)
        _archive(c, "goals", gid)
        # The /projects panel sends goal_id on every save.
        r = c.patch(f"/api/projects/{pid}", json={"name": "P2", "goal_id": gid})
        assert r.status_code == 200, r.get_json()
        g_old = _goal(c, "Old goal")
        _archive(c, "goals", g_old)
        _refused(c.patch(f"/api/projects/{pid}", json={"goal_id": g_old}),
                 _archived_goal_msg("Old goal"), "goal_id")
        _refused(c.patch(f"/api/projects/{pid}", json={"goal_id": GHOST}), MISSING_GOAL, "goal_id")
        # The refused goal didn't cascade onto the project's tasks.
        assert _row(app, Task, tid)["goal_id"] == gid
        with app.app_context():
            assert str(db.session.get(Project, uuid.UUID(pid)).goal_id) == gid

    def test_clearing_the_goal_still_works(self, authed_client, app):
        c = authed_client
        gid = _goal(c, "G")
        pid = _project(c, "P", goal_id=gid)
        r = c.patch(f"/api/projects/{pid}", json={"goal_id": None})
        assert r.status_code == 200
        with app.app_context():
            assert db.session.get(Project, uuid.UUID(pid)).goal_id is None
