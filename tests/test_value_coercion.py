"""#476 — values of the wrong kind on a write.

A yes/no that isn't true/false, a body that isn't an object, a number where
text belongs, a "whole number" that is Infinity / true / 2.5 / too big for
the column: each is refused with a plain 422 (400 for a body), before
anything changes — instead of being bent into the wrong value or crashing
with a 500.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import DataError

from models import Project, RecurringTask, Task, TaskStatus, TaskType, db

INF = float("inf")


def _err(r, status, msg, field=None):
    assert r.status_code == status, (r.status_code, r.get_json())
    body = r.get_json()
    assert body["error"] == msg, body
    if field is not None:
        assert body.get("field") == field, body


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


def _project(c, **body):
    body.setdefault("name", "P")
    r = c.post("/api/projects", json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id"]


def _goal(c, **body):
    body.setdefault("title", "G")
    body.setdefault("category", "work")
    body.setdefault("priority", "must")
    r = c.post("/api/goals", json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id"]


def _get(app, model, id_):
    with app.app_context():
        return db.session.get(model, uuid.UUID(id_))


class TestYesNo:
    def test_recurring_is_active_string_refused(self, authed_client, app):
        c = authed_client
        rid = _template(c)
        assert c.patch(f"/api/recurring/{rid}", json={"is_active": False}).status_code == 200
        _err(c.patch(f"/api/recurring/{rid}", json={"is_active": "false"}),
             422, "is_active must be true or false", "is_active")
        assert _get(app, RecurringTask, rid).is_active is False
        r = c.patch("/api/recurring/bulk",
                    json={"template_ids": [rid], "updates": {"is_active": "true"}})
        assert r.get_json()["errors"] == [
            {"id": rid, "error": "is_active must be true or false", "field": "is_active"},
        ]
        assert _get(app, RecurringTask, rid).is_active is False
        # The quiet case: a real boolean still resumes.
        assert c.patch(f"/api/recurring/{rid}", json={"is_active": True}).status_code == 200
        assert _get(app, RecurringTask, rid).is_active is True

    @pytest.mark.parametrize("action,flag", [("complete", "complete_subtasks"),
                                             ("cancel", "cancel_subtasks")])
    def test_subtask_flag_string_refused(self, authed_client, app, action, flag):
        c = authed_client
        parent = _task(c)
        child = _task(c, title="child", parent_id=parent)
        _err(c.post(f"/api/tasks/{parent}/{action}", json={flag: "false"}),
             422, f"{flag} must be true or false", flag)
        assert _get(app, Task, child).status == TaskStatus.ACTIVE
        assert _get(app, Task, parent).status == TaskStatus.ACTIVE
        # The quiet case: true closes both.
        assert c.post(f"/api/tasks/{parent}/{action}", json={flag: True}).status_code == 200
        assert _get(app, Task, child).status != TaskStatus.ACTIVE

    def test_planner_ignore_string_refused(self, authed_client, app):
        c = authed_client
        tid = _task(c)
        _err(c.post(f"/api/planner/ignore/{tid}", json={"ignore": "false"}),
             422, "ignore must be true or false", "ignore")
        assert _get(app, Task, tid).planner_ignore is False
        assert c.post(f"/api/planner/ignore/{tid}", json={"ignore": True}).status_code == 200
        assert _get(app, Task, tid).planner_ignore is True


class TestNullEnumKeepsCurrent:
    def test_project_null_type_and_status_keep_current(self, authed_client, app):
        c = authed_client
        pid = _project(c, type="personal", status="in_progress")
        r = c.patch(f"/api/projects/{pid}", json={"type": None, "status": None, "name": "P2"})
        assert r.status_code == 200, r.get_json()
        p = _get(app, Project, pid)
        assert (p.name, p.type.value, p.status.value) == ("P2", "personal", "in_progress")
        r = c.patch("/api/projects/bulk", json={"project_ids": [pid], "updates": {"type": None}})
        assert r.get_json()["updated"] == 1
        assert _get(app, Project, pid).type.value == "personal"


class TestBodyMustBeAnObject:
    def test_optional_body_routes_refuse_a_list(self, authed_client):
        c = authed_client
        tid = _task(c)
        routes = [
            ("post", f"/api/tasks/{tid}/complete"),
            ("post", f"/api/tasks/{tid}/cancel"),
            ("post", "/api/planner/weekly"),
            ("post", f"/api/planner/ignore/{tid}"),
            ("post", "/api/strength-forge/sessions"),
            ("patch", "/api/strength-forge/flare"),
            ("patch", "/api/weekly-focus/1"),
            ("patch", "/api/weekly-focus/settings/slot-count"),
            ("post", f"/api/voice-review/{tid}/move"),
        ]
        for method, url in routes:
            for body in ([1], "x", 5):
                r = getattr(c, method)(url, json=body)
                _err(r, 400, "JSON body must be an object")
        assert _get(c.application, Task, tid).status == TaskStatus.ACTIVE

    def test_no_body_still_means_no_options(self, authed_client, app):
        c = authed_client
        tid = _task(c)
        assert c.post(f"/api/tasks/{tid}/complete").status_code == 200
        assert _get(app, Task, tid).status == TaskStatus.ARCHIVED


class TestIdLists:
    def test_number_ids_refused(self, authed_client):
        c = authed_client
        r = c.post("/api/projects/reorder", json={"ordered_ids": [5]})
        assert r.status_code == 422, r.get_json()
        r = c.patch("/api/recurring/bulk", json={"template_ids": [5], "updates": {"type": "work"}})
        _err(r, 422, "every entry in template_ids must be a UUID")
        r = c.delete("/api/recurring/bulk", json={"template_ids": [5]})
        _err(r, 422, "every entry in template_ids must be a UUID")


class TestText:
    def test_task_text_fields(self, authed_client, app):
        c = authed_client
        _err(c.post("/api/tasks", json={"title": 5, "type": "work"}),
             422, "title must be text", "title")
        _err(c.post("/api/tasks", json={"title": "x", "type": "work", "project_hint": 5}),
             422, "project_hint must be text", "project_hint")
        tid = _task(c)
        for field in ("title", "notes"):
            for bad in (5, [1], {"a": 1}):
                _err(c.patch(f"/api/tasks/{tid}", json={field: bad}), 422,
                     f"{field} must be text", field)
        _err(c.post(f"/api/tasks/{tid}/cancel", json={"cancellation_reason": 5}),
             422, "cancellation_reason must be text", "cancellation_reason")
        t = _get(app, Task, tid)
        assert (t.title, t.notes, t.status) == ("T", None, TaskStatus.ACTIVE)
        # The quiet cases.
        assert c.patch(f"/api/tasks/{tid}", json={"notes": ""}).status_code == 200
        assert c.patch(f"/api/tasks/{tid}", json={"notes": None}).status_code == 200

    def test_project_goal_recurring_text_fields(self, authed_client, app):
        c = authed_client
        _err(c.post("/api/projects", json={"name": 5}), 422, "name must be text", "name")
        pid = _project(c)
        for field in ("name", "target_quarter", "actions", "notes"):
            _err(c.patch(f"/api/projects/{pid}", json={field: 5}),
                 422, f"{field} must be text", field)
        _err(c.post("/api/goals", json={"title": 5, "category": "work", "priority": "must"}),
             422, "title must be text", "title")
        gid = _goal(c)
        for field in ("title", "target_quarter", "actions", "notes"):
            _err(c.patch(f"/api/goals/{gid}", json={field: [1]}),
                 422, f"{field} must be text", field)
        _err(c.post("/api/recurring", json={"title": 5, "type": "work", "frequency": "daily"}),
             422, "title must be text", "title")
        rid = _template(c)
        for field in ("title", "url", "notes"):
            _err(c.patch(f"/api/recurring/{rid}", json={field: 5}),
                 422, f"{field} must be text", field)
        assert _get(app, Project, pid).name == "P"
        assert _get(app, RecurringTask, rid).title == "R"

    def test_reflection_milestone_strength_text(self, authed_client):
        c = authed_client
        _err(c.post("/api/reflection", json={"text": 5}), 422, "text must be text")
        _err(c.put("/api/reflection/milestone", json={"label": 5}), 422, "label must be text")
        _err(c.put("/api/reflection/milestone", json={"goal_id": 5}), 422, "goal_id must be a UUID")
        _err(c.post("/api/strength-forge/sessions", json={"plan_type": 5}),
             422, "plan_type must be text")
        _err(c.patch("/api/strength-forge/flare", json={"phase": 5}), 422, "phase must be text")

    def test_url_preview_number_is_an_invalid_url(self, authed_client):
        _err(authed_client.post("/api/tasks/url-preview", json={"url": 5}), 400, "invalid url")


class TestWholeNumbers:
    @pytest.mark.parametrize("bad", [INF, True, 2.5, float("nan")])
    def test_sort_order_refused(self, authed_client, bad):
        c = authed_client
        tid = _task(c)
        _err(c.patch(f"/api/tasks/{tid}", json={"sort_order": bad}), 422,
             "invalid sort_order: must be an integer", "sort_order")

    def test_too_large_refused(self, authed_client):
        c = authed_client
        tid = _task(c)
        _err(c.patch(f"/api/tasks/{tid}", json={"sort_order": 10**30}), 422,
             "sort_order is too large", "sort_order")
        _err(c.patch(f"/api/tasks/{tid}", json={"sort_order": 2**31}), 422,
             "sort_order is too large", "sort_order")
        gid = _goal(c)
        _err(c.patch(f"/api/goals/{gid}", json={"priority_rank": INF}), 422,
             "invalid priority_rank: must be an integer", "priority_rank")

    def test_whole_float_and_numeric_string_accepted(self, authed_client, app):
        c = authed_client
        tid = _task(c)
        assert c.patch(f"/api/tasks/{tid}", json={"sort_order": 3.0}).status_code == 200
        assert _get(app, Task, tid).sort_order == 3
        assert c.patch(f"/api/tasks/{tid}", json={"sort_order": "4"}).status_code == 200
        assert _get(app, Task, tid).sort_order == 4
        assert c.patch(f"/api/tasks/{tid}", json={"sort_order": -(2**31) + 1}).status_code == 200

    def test_project_priority_order(self, authed_client):
        c = authed_client
        pid = _project(c)
        for bad in (INF, True, 10**30):
            _err(c.patch(f"/api/projects/{pid}", json={"priority_order": bad}), 422,
                 "priority_order must be integer", "priority_order")

    def test_recurring_day_fields(self, authed_client):
        c = authed_client
        base = {"title": "R", "type": "work"}
        _err(c.post("/api/recurring",
                    json={**base, "frequency": "monthly_date", "day_of_month": INF}),
             422, "day_of_month must be integer 1-31", "day_of_month")
        _err(c.post("/api/recurring", json={**base, "frequency": "weekly", "day_of_week": True}),
             422, "day_of_week must be integer 0-6", "day_of_week")
        _err(c.post("/api/recurring", json={**base, "frequency": "multi_day_of_week",
                                            "days_of_week": [True]}),
             422, "days_of_week entries must be integers 0-6", "days_of_week")

    def test_weekly_focus_slot_count(self, authed_client):
        _err(authed_client.patch("/api/weekly-focus/settings/slot-count", json={"slot_count": INF}),
             422, "slot_count must be an integer")

    def test_strength_rows_stay_forgiving(self, authed_client, app):
        from models import WorkoutSet
        c = authed_client
        r = c.post("/api/strength-forge/sessions", json={"plan_type": "split-1", "sets": [
            {"exercise_id": "a", "name": "A", "set_number": INF, "reps": INF, "resistance": 25},
            {"exercise_id": 5, "name": ["x"], "set_number": 2, "reps": 8},
        ]})
        assert r.status_code == 201, r.get_json()
        with app.app_context():
            rows = sorted(db.session.query(WorkoutSet).all(), key=lambda s: s.set_number)
            got = [(s.set_number, s.reps, s.resistance) for s in rows]
            assert got == [(1, None, "25"), (2, 8, None)]
            assert (rows[1].exercise_id, rows[1].exercise_name) == ("5", "5")


class TestShapes:
    def test_repeat_must_be_an_object(self, authed_client):
        c = authed_client
        tid = _task(c)
        for bad in ("daily", ["daily"], 5):
            _err(c.patch(f"/api/tasks/{tid}", json={"repeat": bad}), 422,
                 "repeat must be an object or null", "repeat")

    def test_checklist_items_must_be_objects(self, authed_client):
        c = authed_client
        tid = _task(c)
        _err(c.patch(f"/api/tasks/{tid}", json={"checklist": ["a", 5]}), 422,
             "checklist items must be objects", "checklist")
        ok = [{"text": "a", "done": False}]
        assert c.patch(f"/api/tasks/{tid}", json={"checklist": ok}).status_code == 200

    def test_reflection_segment_non_finite_numbers_dropped(self, app):
        from reflection_service import _normalise_raw_segments
        with app.app_context():
            out = _normalise_raw_segments(
                [{"text": "hi", "duration_seconds": INF, "cost_usd": float("nan")}],
            )
        assert out[0]["duration_seconds"] is None
        assert out[0]["cost_usd"] is None

    def test_scan_kind_not_text_means_tasks(self):
        from scan_api import _normalize_kind
        assert _normalize_kind(5) == "tasks"
        assert _normalize_kind(["goals"]) == "tasks"
        assert _normalize_kind("goals") == "goals"


class TestFlushGuardIntegerRange:
    def test_out_of_range_integer_raises_like_postgres(self, app):
        with app.app_context():
            t = Task(title="x", type=TaskType.WORK, sort_order=2**31)
            db.session.add(t)
            with pytest.raises(DataError):
                db.session.flush()
            db.session.rollback()
