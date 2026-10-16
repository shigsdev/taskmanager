"""#470: voice memo Add All is all-or-nothing.

Spec: docs/design/470-voice-add-all-one-transaction.md. ``voice_api.confirm``
used to create tasks, recurring templates, goals and projects in separate
commits, so a failure part-way returned an error after some of the batch
was saved, and the #442 retry re-created what had landed. It now writes
the whole batch in one transaction: any failure saves nothing. One bad
recurring item is still skipped on its own (a savepoint), as before.
"""
from __future__ import annotations

from sqlalchemy import text

from models import Goal, ImportLog, Project, RecurringTask, Task, db

TAG = "E2E470"


def _batch():
    return {"candidates": [
        {"title": f"{TAG} task", "type": "work", "route": "task", "included": True},
        {"title": f"{TAG} routine", "type": "personal", "route": "task", "included": True,
         "repeat": {"frequency": "daily"}},
        {"title": f"{TAG} goal", "route": "goal", "category": "health", "included": True},
        {"title": f"{TAG} project", "route": "project", "type": "work", "included": True},
    ]}


def _counts(app):
    with app.app_context():
        like = f"{TAG}%"
        return {
            "tasks": db.session.query(Task).filter(Task.title.like(like)).count(),
            "recurring": db.session.query(RecurringTask)
            .filter(RecurringTask.title.like(like)).count(),
            "goals": db.session.query(Goal).filter(Goal.title.like(like)).count(),
            "projects": db.session.query(Project).filter(Project.name.like(like)).count(),
            "logs": db.session.query(ImportLog).filter(ImportLog.source.like("voice%")).count(),
        }


def test_the_whole_batch_lands(app, authed_client):
    """The quiet case: one of each, as before."""
    r = authed_client.post("/api/voice-memo/confirm", json=_batch())
    assert r.status_code == 201
    body = r.get_json()
    assert body["created"] == 4
    assert _counts(app) == {"tasks": 1, "recurring": 1, "goals": 1, "projects": 1, "logs": 3}


def test_a_failed_step_saves_nothing_and_a_retry_adds_each_once(app, authed_client, monkeypatch):
    import import_service

    real = import_service.create_goals_from_import

    def boom(*args, **kwargs):
        real(*args, **kwargs)          # the goal is written...
        raise RuntimeError("goal insert failed")  # ...then the step fails

    monkeypatch.setattr(import_service, "create_goals_from_import", boom)
    r = authed_client.post("/api/voice-memo/confirm", json=_batch())
    assert r.status_code == 500
    body = r.get_json()
    assert body["saved"] is False
    assert body["error"] == "something went wrong on the server"
    assert _counts(app) == {"tasks": 0, "recurring": 0, "goals": 0, "projects": 0, "logs": 0}

    monkeypatch.setattr(import_service, "create_goals_from_import", real)
    r = authed_client.post("/api/voice-memo/confirm", json=_batch())
    assert r.status_code == 201
    assert _counts(app) == {"tasks": 1, "recurring": 1, "goals": 1, "projects": 1, "logs": 3}


def test_a_failed_project_step_also_saves_nothing(app, authed_client, monkeypatch):
    import import_service

    def boom(*args, **kwargs):
        raise RuntimeError("project insert failed")

    monkeypatch.setattr(import_service, "create_projects_from_import", boom)
    r = authed_client.post("/api/voice-memo/confirm", json=_batch())
    assert r.status_code == 500
    assert _counts(app)["tasks"] == 0
    assert _counts(app)["goals"] == 0


def test_a_database_error_in_one_recurring_item_skips_only_that_item(
    app, authed_client, monkeypatch,
):
    """The recurring step used to catch the error without a rollback, which
    on Postgres leaves the session failed for the goal / project steps. Now
    the item's savepoint is rolled back and the batch goes on."""
    import recurring_service

    def broken(data, **kwargs):
        db.session.execute(text("SELECT * FROM no_such_table_470"))

    monkeypatch.setattr(recurring_service, "create_recurring", broken)
    r = authed_client.post("/api/voice-memo/confirm", json=_batch())
    assert r.status_code == 201
    body = r.get_json()
    assert "1 recurring item(s) couldn't be created" in body["warning"]
    assert _counts(app) == {"tasks": 1, "recurring": 0, "goals": 1, "projects": 1, "logs": 3}


def test_a_malformed_recurring_item_is_still_skipped_quietly(app, authed_client):
    batch = _batch()
    batch["candidates"][1]["repeat"] = {"frequency": "weekly"}   # no day: refused
    r = authed_client.post("/api/voice-memo/confirm", json=batch)
    assert r.status_code == 201
    assert "1 recurring item(s) couldn't be created" in r.get_json()["warning"]
    assert _counts(app)["recurring"] == 0
    assert _counts(app)["tasks"] == 1
