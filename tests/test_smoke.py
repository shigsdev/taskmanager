"""Smoke tests: app boots, blueprints register, healthz responds.

The ``requires_postgres`` marker skips tests that need a real PostgreSQL
connection unless DATABASE_URL points to one. These will be exercised
post-deploy or in CI with a real DB.

Run the postgres-only tests locally with:
    DATABASE_URL=postgresql+psycopg://... pytest -m requires_postgres
"""
from __future__ import annotations

import os
import uuid

import pytest

from app import create_app
from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    Task,
    TaskType,
    db,
)

requires_postgres = pytest.mark.skipif(
    not (os.environ.get("DATABASE_URL") or "").startswith("postgresql"),
    reason="requires a real PostgreSQL DATABASE_URL",
)


# --- App boot (always runs) -------------------------------------------------


def test_app_boots(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test")
    monkeypatch.setenv("FLASK_ENV", "development")
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "smoke",
            "AUTHORIZED_EMAIL": "smoke@example.com",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        }
    )
    assert app is not None


def test_healthz_no_auth(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_all_blueprints_registered(app):
    names = set(app.blueprints.keys())
    assert "google" in names
    assert "tasks_api" in names
    assert "goals_api" in names


def test_expected_routes_exist(app):
    rules = [r.rule for r in app.url_map.iter_rules()]
    assert "/api/tasks" in rules
    assert "/api/goals" in rules
    assert "/healthz" in rules
    assert "/login" in rules
    assert "/logout" in rules


# --- PostgreSQL-specific (skipped unless DATABASE_URL is a real PG) ----------


@requires_postgres
class TestPostgresSpecific:
    """Tests that exercise PostgreSQL-only behavior: JSONB, native UUID,
    native enums.  Skipped in local dev if DATABASE_URL is SQLite."""

    @pytest.fixture(autouse=True)
    def _pg_app(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "test")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test")
        monkeypatch.setenv("FLASK_ENV", "development")
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "pg-smoke",
                "AUTHORIZED_EMAIL": "smoke@example.com",
                "SQLALCHEMY_DATABASE_URI": os.environ["DATABASE_URL"],
            }
        )
        with self.app.app_context():
            db.create_all()
            yield
            db.session.remove()
            db.drop_all()

    def test_uuid_primary_key_round_trips(self):
        with self.app.app_context():
            task = Task(title="PG UUID test", type=TaskType.WORK)
            db.session.add(task)
            db.session.commit()
            fetched = db.session.get(Task, task.id)
            assert isinstance(fetched.id, uuid.UUID)

    def test_jsonb_checklist_round_trips(self):
        with self.app.app_context():
            checklist = [
                {"id": "1", "text": "step one", "checked": False},
                {"id": "2", "text": "step two", "checked": True},
            ]
            task = Task(title="JSONB test", type=TaskType.WORK, checklist=checklist)
            db.session.add(task)
            db.session.commit()
            fetched = db.session.get(Task, task.id)
            assert fetched.checklist == checklist
            assert fetched.checklist[1]["checked"] is True

    def test_enum_values_stored_correctly(self):
        with self.app.app_context():
            goal = Goal(
                title="PG enum test",
                category=GoalCategory.HEALTH,
                priority=GoalPriority.MUST,
            )
            db.session.add(goal)
            db.session.commit()
            fetched = db.session.get(Goal, goal.id)
            assert fetched.category is GoalCategory.HEALTH
            assert fetched.priority is GoalPriority.MUST
