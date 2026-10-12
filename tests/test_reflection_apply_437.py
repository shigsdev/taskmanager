"""#437 — Reflection: the user's "today", a retryable Apply, readable errors.

1. The ISO week and the "today" Claude is told come from DIGEST_TZ, not
   UTC (a Sunday 23:30 ET reflection is Monday in UTC).
2. A partly failed Apply leaves ``applied_at`` unset and reports which
   actions failed; a retry applies only what hadn't landed, and an action
   that already landed is never applied twice.
3. A database error's raw text never reaches the response.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest

import auth
from models import Reflection, ReflectionInputMode, Task, db

# Sunday 2026-10-11 23:30 in New York == Monday 03:30 UTC.
_INSTANT = datetime(2026, 10, 12, 3, 30, tzinfo=UTC)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return _INSTANT.astimezone(tz) if tz else _INSTANT.replace(tzinfo=None)


@pytest.fixture
def sunday_night_et(monkeypatch):
    import utils
    monkeypatch.setenv("DIGEST_TZ", "America/New_York")
    monkeypatch.setattr(utils, "datetime", _FrozenDatetime)


def _bypass_auth(monkeypatch):
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")


def _reflection():
    from reflection_service import save_reflection
    return save_reflection(
        transcript="x",
        input_mode=ReflectionInputMode.TYPED,
        proposed={"explicit": [], "suggested": []},
    )


def _create_task(title):
    return {"op": "create", "entity": "task", "target": title,
            "fields": {"title": title, "type": "work", "tier": "inbox"}}


def _create_goal(title):
    return {"op": "create", "entity": "goal", "target": title,
            "fields": {"title": title, "category": "work", "priority": "should"}}


def _titles(prefix):
    return sorted(t.title for t in Task.query.all() if t.title.startswith(prefix))


class TestUsersToday:

    def test_iso_week_is_the_users_week(self, app, sunday_night_et):
        from reflection_service import current_iso_week
        iso = date(2026, 10, 11).isocalendar()
        assert current_iso_week() == f"{iso.year}-W{iso.week:02d}"

    def test_claude_is_told_the_users_date(self, app, sunday_night_et, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        fake = {"content": [{"type": "text",
                             "text": json.dumps({"explicit": [], "suggested": []})}],
                "usage": {"input_tokens": 1, "output_tokens": 1}}
        with app.app_context(), patch(
            "reflection_service._call_claude", return_value=fake,
        ) as call:
            from reflection_service import analyze_reflection
            analyze_reflection("Plan the week.")
        prompt = call.call_args.args[1]
        assert "2026-10-11" in prompt
        assert "2026-10-12" not in prompt


class TestRetryablePartialApply:

    def test_failed_step_leaves_it_unapplied_and_retry_finishes(self, app):
        from reflection_service import apply_selected_actions
        with app.app_context():
            r = _reflection()
            actions = [_create_goal("437 goal"), _create_task("437 task A")]
            with patch("scan_service.create_tasks_from_candidates",
                       side_effect=RuntimeError("boom")):
                first = apply_selected_actions(r, actions)
            assert first["created"]["goal"] == 1
            assert first["failed"] == [1]
            assert r.applied_at is None
            assert _titles("437 task") == []

            # The retry resends BOTH: the goal is skipped, the task lands.
            second = apply_selected_actions(r, actions)
            assert second["already_applied"] == 1
            assert second["created"] == {"task": 1, "goal": 0, "project": 0}
            assert second["failed"] == []
            assert r.applied_at is not None
            assert _titles("437 task") == ["437 task A"]
            from models import Goal
            assert Goal.query.filter_by(title="437 goal").count() == 1
            assert len(r.applied_actions["actions"]) == 2

    def test_reapply_after_success_creates_nothing_twice(self, app):
        from reflection_service import apply_selected_actions
        with app.app_context():
            r = _reflection()
            actions = [_create_task("437 once")]
            apply_selected_actions(r, actions)
            r.applied_at = None  # as if reopened before the 409 guard
            again = apply_selected_actions(r, actions)
            assert again["already_applied"] == 1
            assert _titles("437 once") == ["437 once"]

    def test_update_of_a_missing_task_names_it(self, app):
        from reflection_service import apply_selected_actions
        with app.app_context():
            r = _reflection()
            summary = apply_selected_actions(r, [{
                "op": "update", "entity": "task", "target": "Book dentist",
                "id": "00000000-0000-0000-0000-000000000001",
                "fields": {"tier": "today"},
            }])
        assert summary["failed"] == [0]
        assert summary["errors"] == [
            'Couldn\'t update task "Book dentist" — it no longer exists.'
        ]

    def test_database_error_text_is_not_shown(self, app):
        from sqlalchemy.exc import IntegrityError

        from reflection_service import apply_selected_actions
        raw = 'duplicate key value violates unique constraint "tasks_pkey"'
        with app.app_context():
            r = _reflection()
            with patch("scan_service.create_tasks_from_candidates",
                       side_effect=IntegrityError("INSERT ...", {}, Exception(raw))):
                summary = apply_selected_actions(r, [_create_task("437 db")])
        joined = " ".join(summary["errors"])
        assert "tasks_pkey" not in joined
        assert "IntegrityError" not in joined
        assert summary["errors"] == ["Couldn't create 1 task — nothing was saved for it."]


class TestConfirmRoute:

    def test_207_then_retry_then_409(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        with app.app_context():
            rid = str(_reflection().id)
        actions = [_create_goal("437 route goal"), _create_task("437 route task")]
        url = f"/api/reflection/{rid}/confirm"
        with patch("scan_service.create_tasks_from_candidates",
                   side_effect=RuntimeError("boom")):
            first = client.post(url, json={"actions": actions})
        assert first.status_code == 207
        assert first.get_json()["applied_at"] is None
        assert first.get_json()["summary"]["failed"] == [1]

        second = client.post(url, json={"actions": [actions[1]]})
        assert second.status_code == 200
        assert second.get_json()["applied_at"] is not None

        third = client.post(url, json={"actions": actions})
        assert third.status_code == 409
        with app.app_context():
            assert _titles("437 route task") == ["437 route task"]
            assert db.session.get(Reflection, __import__("uuid").UUID(rid)).applied_at
