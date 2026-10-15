"""#447 — text longer than its column.

Prod is Postgres: a value longer than its ``String(n)`` column fails the
write (and, in a batch, every row with it) with an opaque "Database error".
User decision 2026-10-14: what you type is REFUSED with a clear message;
what arrives in a batch is CUT to fit (ending in "…") so the rest saves.

``conftest._check_string_widths`` makes SQLite refuse over-long values the
way Postgres does, so these tests (and every other test) see prod's failure.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import DataError

from models import Goal, ImportLog, Project, RecurringTask, Task, TaskType, db

LONG_TITLE = "x" * 501
LONG_NAME = "n" * 201
LONG_QUARTER = "Q" * 21


def _task(**kw) -> Task:
    t = Task(title=kw.pop("title", "short"), type=TaskType.WORK, **kw)
    db.session.add(t)
    db.session.commit()
    return t


class TestFlushGuard:
    """The test-only width check itself — without it nothing below means much."""

    def test_over_long_value_fails_like_postgres(self, app):
        with app.app_context():
            db.session.add(Task(title=LONG_TITLE, type=TaskType.WORK))
            with pytest.raises(DataError):
                db.session.flush()
            db.session.rollback()

    def test_value_at_the_limit_is_fine(self, app):
        with app.app_context():
            t = _task(title="x" * 500)
            assert len(t.title) == 500


class TestHelpers:
    def test_check_length_names_field_and_limit(self):
        from utils import ValidationError, check_length

        assert check_length("ok", 5, "title", "Title") == "ok"
        assert check_length(None, 5, "title", "Title") is None
        with pytest.raises(ValidationError) as e:
            check_length("toolong", 5, "title", "Title")
        assert str(e.value) == "Title is too long: 7 characters, the limit is 5."
        assert e.value.field == "title"

    def test_fit_length_cuts_with_an_ellipsis(self):
        from utils import fit_length

        assert fit_length("short", 10) == "short"
        assert fit_length(None, 10) is None
        cut = fit_length("abcdefghijkl", 10)
        assert cut == "abcdefghi…"
        assert len(cut) == 10
        # Never ends "word …" with a dangling space before the ellipsis.
        assert fit_length("abcd efghijkl", 6) == "abcd…"


class TestTypedEditsAreRefused:
    """Your own edits: 422 with the message, nothing saved, no Database error."""

    def _says(self, resp, label, n, limit):
        assert resp.status_code == 422
        assert resp.get_json()["error"] == (
            f"{label} is too long: {n} characters, the limit is {limit}."
        )

    def test_task_create_and_update(self, authed_client, app):
        r = authed_client.post("/api/tasks", json={"title": LONG_TITLE, "type": "work"})
        self._says(r, "Title", 501, 500)
        r = authed_client.post("/api/tasks", json={"title": "ok", "type": "work"})
        tid = r.get_json()["id"]
        r = authed_client.patch(f"/api/tasks/{tid}", json={"title": LONG_TITLE})
        self._says(r, "Title", 501, 500)
        r = authed_client.patch(f"/api/tasks/{tid}", json={"cancellation_reason": "r" * 501})
        self._says(r, "Cancellation reason", 501, 500)
        with app.app_context():
            assert db.session.get(Task, __import__("uuid").UUID(tid)).title == "ok"

    def test_task_cancel_reason(self, authed_client):
        tid = authed_client.post("/api/tasks", json={"title": "c", "type": "work"}).get_json()["id"]
        r = authed_client.post(f"/api/tasks/{tid}/cancel", json={"cancellation_reason": "r" * 501})
        self._says(r, "Cancellation reason", 501, 500)

    def test_task_bulk_reports_the_row(self, authed_client):
        tid = authed_client.post("/api/tasks", json={"title": "b", "type": "work"}).get_json()["id"]
        r = authed_client.patch("/api/tasks/bulk", json={
            "task_ids": [tid], "updates": {"cancellation_reason": "r" * 501},
        })
        assert r.status_code == 200
        body = r.get_json()
        assert body["updated"] == 0
        assert body["errors"][0]["message"].startswith("Cancellation reason is too long")

    def test_goal_create_and_update(self, authed_client):
        base = {"category": "work", "priority": "should"}
        self._says(authed_client.post("/api/goals", json={**base, "title": LONG_TITLE}),
                   "Title", 501, 500)
        self._says(authed_client.post("/api/goals", json={**base, "title": "g",
                                                           "target_quarter": LONG_QUARTER}),
                   "Target quarter", 21, 20)
        gid = authed_client.post("/api/goals", json={**base, "title": "g"}).get_json()["id"]
        self._says(authed_client.patch(f"/api/goals/{gid}", json={"title": LONG_TITLE}),
                   "Title", 501, 500)
        self._says(authed_client.patch(f"/api/goals/{gid}", json={"target_quarter": LONG_QUARTER}),
                   "Target quarter", 21, 20)

    def test_project_create_update_and_bulk(self, authed_client):
        self._says(authed_client.post("/api/projects", json={"name": LONG_NAME}),
                   "Name", 201, 200)
        self._says(authed_client.post("/api/projects", json={"name": "p",
                                                              "target_quarter": LONG_QUARTER}),
                   "Target quarter", 21, 20)
        pid = authed_client.post("/api/projects", json={"name": "p"}).get_json()["id"]
        self._says(authed_client.patch(f"/api/projects/{pid}", json={"name": LONG_NAME}),
                   "Name", 201, 200)
        r = authed_client.patch("/api/projects/bulk", json={
            "project_ids": [pid], "updates": {"target_quarter": LONG_QUARTER},
        })
        assert r.get_json()["updated"] == 0

    def test_project_colour_eight_digits_refused(self, authed_client):
        r = authed_client.post("/api/projects", json={"name": "c", "color": "#2563ebff"})
        assert r.status_code == 422
        r = authed_client.post("/api/projects", json={"name": "c", "color": "#2563eb"})
        assert r.status_code == 201
        assert r.get_json()["color"] == "#2563eb"

    def test_recurring_create_and_update(self, authed_client):
        base = {"type": "work", "frequency": "daily"}
        self._says(authed_client.post("/api/recurring", json={**base, "title": LONG_TITLE}),
                   "Title", 501, 500)
        self._says(authed_client.post("/api/recurring", json={**base, "title": "r",
                                                               "url": "https://e.x/" + "u" * 2000}),
                   "URL", 2012, 2000)
        rid = authed_client.post("/api/recurring", json={**base, "title": "r"}).get_json()["id"]
        self._says(authed_client.patch(f"/api/recurring/{rid}", json={"title": LONG_TITLE}),
                   "Title", 501, 500)


class TestBatchesFitAndSave:
    """A batch cuts the one long value to fit; the other rows still save."""

    def test_import_tasks(self, app):
        from import_service import create_tasks_from_import

        with app.app_context():
            tasks = create_tasks_from_import([
                {"title": LONG_TITLE, "included": True, "url": "https://e.x/" + "u" * 2000},
                {"title": "Short one", "included": True},
            ], source="s" * 150)
            assert len(tasks) == 2
            assert len(tasks[0].title) == 500 and tasks[0].title.endswith("…")
            assert tasks[0].url is None          # a cut URL wouldn't work
            assert tasks[1].title == "Short one"
            log = db.session.query(ImportLog).one()
            assert len(log.source) == 100

    def test_import_goals_and_projects(self, app):
        from import_service import create_goals_from_import, create_projects_from_import

        with app.app_context():
            goals = create_goals_from_import([
                {"title": LONG_TITLE, "target_quarter": LONG_QUARTER, "included": True},
                {"title": "Other goal", "included": True},
            ], source="g")
            assert len(goals) == 2
            assert len(goals[0].title) == 500
            assert len(goals[0].target_quarter) == 20
            projects = create_projects_from_import([
                {"name": LONG_NAME, "target_quarter": LONG_QUARTER, "included": True},
                {"name": "Other project", "included": True},
            ], source="p")
            assert len(projects) == 2
            assert len(projects[0].name) == 200 and projects[0].name.endswith("…")
            assert db.session.query(Goal).count() == 2
            assert db.session.query(Project).count() == 2

    def test_scan_voice_reflection_tasks(self, app):
        from scan_service import create_tasks_from_candidates

        with app.app_context():
            tasks = create_tasks_from_candidates([
                {"title": LONG_TITLE, "type": "work", "tier": "inbox", "included": True},
                {"title": "Fine", "type": "work", "tier": "inbox", "included": True},
            ], source_prefix="voice")
            assert len(tasks) == 2
            assert len(tasks[0].title) == 500

    def test_voice_recurring_template(self, app):
        from recurring_service import create_recurring_template_from_voice_candidate

        with app.app_context():
            rt = create_recurring_template_from_voice_candidate({
                "title": LONG_TITLE, "type": "work",
                "repeat": {"frequency": "daily"},
            })
            assert rt is not None
            assert len(rt.title) == 500

    def test_recurring_subtask_copies(self, app, authed_client):
        r = authed_client.post("/api/recurring", json={
            "title": "Weekly prep", "type": "work", "frequency": "daily",
            "subtasks_snapshot": [{"title": LONG_TITLE}, {"title": "second"}],
        })
        assert r.status_code == 201
        from recurring_service import spawn_today_tasks

        with app.app_context():
            spawn_today_tasks(target_date=date.today())
            subs = db.session.query(Task).filter(Task.parent_id.isnot(None)).all()
            assert len(subs) == 2
            assert sorted(len(s.title) for s in subs) == [6, 500]


class TestLogFieldsFit:
    """app_logs.request_id is String(36), app_logs.route String(200)."""

    def test_long_request_id_gets_a_fresh_uuid(self, app):
        from flask import g

        from logging_service import _before_request

        with app.test_request_context("/", headers={"X-Request-ID": "a" * 37}):
            _before_request()
            assert g.request_id != "a" * 37
            assert len(g.request_id) == 36
        with app.test_request_context("/", headers={"X-Request-ID": "b" * 36}):
            _before_request()
            assert g.request_id == "b" * 36

    def test_long_route_is_cut(self, app):
        from flask import g

        from logging_service import _before_request

        with app.test_request_context("/" + "z" * 300):
            _before_request()
            assert len(g.route) == 200


def test_recurring_template_model_is_checked_too(app):
    """RecurringTask rows go through the same flush guard."""
    with app.app_context():
        db.session.add(RecurringTask(title=LONG_TITLE, type=TaskType.WORK, frequency="daily"))
        with pytest.raises(DataError):
            db.session.flush()
        db.session.rollback()


def test_url_preview_title_is_cut_to_fit(authed_client, monkeypatch):
    """A pasted link's page title becomes the task title — a huge one must not
    get the capture refused for text the user never typed."""
    import urllib.request

    class _FakeResp:
        def read(self, n):  # noqa: ARG002
            return b"<html><head><title>" + b"T" * 900 + b"</title></head></html>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        urllib.request.OpenerDirector, "open",
        lambda self, req, timeout=None: _FakeResp(),  # noqa: ARG005
    )
    resp = authed_client.post("/api/tasks/url-preview", json={"url": "https://example.com/a"})
    assert resp.status_code == 200
    title = resp.get_json()["title"]
    assert len(title) == 500 and title.endswith("…")
    created = authed_client.post("/api/tasks", json={"title": title, "type": "work"})
    assert created.status_code == 201


def test_reflection_reason_has_one_full_stop():
    """/reflection's apply shows a refused update's message — once punctuated."""
    from reflection_service import _reason
    from utils import ValidationError

    msg = _reason(ValidationError("Title is too long: 501 characters, the limit is 500.", "title"))
    assert msg == " — Title is too long: 501 characters, the limit is 500."
    assert _reason(ValidationError("task no longer exists")) == " — task no longer exists."
