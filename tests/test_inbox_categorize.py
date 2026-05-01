"""Integration tests for the auto-categorize-inbox flow.

Service: ``inbox_categorize_service.categorize_inbox()``
Endpoint: ``POST /api/inbox/categorize``

The Claude HTTP call is mocked via ``patch("inbox_categorize_service._post_to_claude")``;
we never hit the real API. Tests focus on the trustworthiness of the
ID-validation pass after Claude responds — this is the load-bearing
defense against Claude hallucinating project/goal IDs that don't
exist.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from models import (
    Goal,
    GoalCategory,
    GoalStatus,
    Project,
    ProjectType,
    Task,
    TaskType,
    Tier,
    db,
)


def _claude_response(rows: list[dict]) -> dict:
    """Wrap a list of suggestion dicts in the shape the real Claude
    HTTP body uses."""
    import json
    return {"content": [{"type": "text", "text": json.dumps(rows)}]}


def _make_inbox_task(title: str = "T", task_type: TaskType = TaskType.WORK) -> Task:
    t = Task(title=title, type=task_type, tier=Tier.INBOX)
    db.session.add(t)
    db.session.commit()
    return t


def _make_project(name: str = "P", goal_id=None) -> Project:
    p = Project(name=name, type=ProjectType.WORK, goal_id=goal_id)
    db.session.add(p)
    db.session.commit()
    return p


def _make_goal(title: str = "G") -> Goal:
    g = Goal(title=title, category=GoalCategory.WORK, status=GoalStatus.IN_PROGRESS)
    db.session.add(g)
    db.session.commit()
    return g


# --- Empty cases ------------------------------------------------------------


class TestEmptyInbox:
    def test_returns_empty_list_when_no_inbox_tasks(self, app, monkeypatch):
        from inbox_categorize_service import categorize_inbox

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with app.app_context():
            result = categorize_inbox()
        assert result == {"count": 0, "suggestions": [], "capped": False}

    def test_does_not_call_claude_when_inbox_empty(self, app, monkeypatch):
        from inbox_categorize_service import categorize_inbox

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with (
            app.app_context(),
            patch(
                "inbox_categorize_service._post_to_claude",
            ) as mock_post,
        ):
            categorize_inbox()
        assert mock_post.call_count == 0


class TestApiKeyHandling:
    def test_raises_without_api_key(self, app, monkeypatch):
        from inbox_categorize_service import categorize_inbox

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with app.app_context():
            _make_inbox_task("Need to categorize")
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                categorize_inbox()


# --- Happy path -------------------------------------------------------------


class TestHappyPath:
    def test_returns_suggestion_per_task(self, app, monkeypatch):
        from inbox_categorize_service import categorize_inbox

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with app.app_context():
            t1 = _make_inbox_task("Pay water bill")
            t2 = _make_inbox_task("Email dentist")
            claude_rows = [
                {
                    "task_id": str(t1.id),
                    "suggested_tier": "this_week",
                    "suggested_project_id": None,
                    "suggested_goal_id": None,
                    "suggested_due_date": None,
                    "suggested_type": "personal",
                    "reason": "monthly bill",
                },
                {
                    "task_id": str(t2.id),
                    "suggested_tier": "today",
                    "suggested_project_id": None,
                    "suggested_goal_id": None,
                    "suggested_due_date": None,
                    "suggested_type": "personal",
                    "reason": "quick action",
                },
            ]
            with patch(
                "inbox_categorize_service._post_to_claude",
                return_value=_claude_response(claude_rows),
            ):
                result = categorize_inbox()

        assert result["count"] == 2
        assert result["capped"] is False
        ids = {s["task_id"] for s in result["suggestions"]}
        assert ids == {str(t1.id), str(t2.id)}
        for s in result["suggestions"]:
            assert s["suggested_tier"] in {"today", "tomorrow", "this_week",
                                           "next_week", "backlog", "freezer"}
            assert s["suggested_type"] in {"work", "personal"}


# --- ID validation (defense against Claude hallucination) -------------------


class TestIdValidation:
    def test_invalid_project_id_is_dropped_to_null(self, app, monkeypatch):
        """Claude returns a project_id that doesn't exist → set to null
        rather than letting the client try to PATCH with a fake FK."""
        from inbox_categorize_service import categorize_inbox

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with app.app_context():
            t = _make_inbox_task("Some task")
            row = {
                "task_id": str(t.id),
                "suggested_tier": "today",
                "suggested_project_id": "00000000-0000-0000-0000-000000000000",
                "suggested_goal_id": None,
                "suggested_due_date": None,
                "suggested_type": "work",
                "reason": "x",
            }
            with patch(
                "inbox_categorize_service._post_to_claude",
                return_value=_claude_response([row]),
            ):
                result = categorize_inbox()
        assert result["suggestions"][0]["suggested_project_id"] is None

    def test_valid_project_id_passes_through(self, app, monkeypatch):
        from inbox_categorize_service import categorize_inbox

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with app.app_context():
            t = _make_inbox_task("X")
            p = _make_project(name="Real project")
            row = {
                "task_id": str(t.id),
                "suggested_tier": "today",
                "suggested_project_id": str(p.id),
                "suggested_goal_id": None,
                "suggested_due_date": None,
                "suggested_type": "work",
                "reason": "x",
            }
            with patch(
                "inbox_categorize_service._post_to_claude",
                return_value=_claude_response([row]),
            ):
                result = categorize_inbox()
        assert result["suggestions"][0]["suggested_project_id"] == str(p.id)

    def test_invalid_tier_falls_back_to_backlog(self, app, monkeypatch):
        from inbox_categorize_service import categorize_inbox

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with app.app_context():
            t = _make_inbox_task("X")
            row = {
                "task_id": str(t.id),
                "suggested_tier": "lunchtime",  # invalid
                "suggested_project_id": None,
                "suggested_goal_id": None,
                "suggested_due_date": None,
                "suggested_type": "work",
                "reason": "x",
            }
            with patch(
                "inbox_categorize_service._post_to_claude",
                return_value=_claude_response([row]),
            ):
                result = categorize_inbox()
        assert result["suggestions"][0]["suggested_tier"] == "backlog"

    def test_invalid_due_date_dropped_to_null(self, app, monkeypatch):
        from inbox_categorize_service import categorize_inbox

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with app.app_context():
            t = _make_inbox_task("X")
            row = {
                "task_id": str(t.id),
                "suggested_tier": "today",
                "suggested_project_id": None,
                "suggested_goal_id": None,
                "suggested_due_date": "next-friday",  # not ISO
                "suggested_type": "work",
                "reason": "x",
            }
            with patch(
                "inbox_categorize_service._post_to_claude",
                return_value=_claude_response([row]),
            ):
                result = categorize_inbox()
        assert result["suggestions"][0]["suggested_due_date"] is None

    def test_unknown_task_id_silently_dropped(self, app, monkeypatch):
        """Claude hallucinates a task_id we didn't send → drop the row,
        don't propagate to the client."""
        from inbox_categorize_service import categorize_inbox

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with app.app_context():
            t = _make_inbox_task("Real task")
            ghost_id = "11111111-2222-3333-4444-555555555555"
            rows = [
                {
                    "task_id": str(t.id),
                    "suggested_tier": "today",
                    "suggested_project_id": None,
                    "suggested_goal_id": None,
                    "suggested_due_date": None,
                    "suggested_type": "work",
                    "reason": "real",
                },
                {
                    "task_id": ghost_id,
                    "suggested_tier": "today",
                    "suggested_project_id": None,
                    "suggested_goal_id": None,
                    "suggested_due_date": None,
                    "suggested_type": "work",
                    "reason": "ghost",
                },
            ]
            with patch(
                "inbox_categorize_service._post_to_claude",
                return_value=_claude_response(rows),
            ):
                result = categorize_inbox()
        ids = {s["task_id"] for s in result["suggestions"]}
        assert str(t.id) in ids
        assert ghost_id not in ids


# --- Backfill ---------------------------------------------------------------


class TestOmittedTaskBackfill:
    def test_task_omitted_by_claude_gets_default_suggestion(self, app, monkeypatch):
        """If Claude returns a partial response missing one of the inbox
        tasks, the service synthesizes a Backlog default so the UI can
        still show every inbox row."""
        from inbox_categorize_service import categorize_inbox

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with app.app_context():
            t1 = _make_inbox_task("Categorized")
            t2 = _make_inbox_task("Forgotten by Claude")
            rows = [{
                "task_id": str(t1.id),
                "suggested_tier": "today",
                "suggested_project_id": None,
                "suggested_goal_id": None,
                "suggested_due_date": None,
                "suggested_type": "work",
                "reason": "x",
            }]
            with patch(
                "inbox_categorize_service._post_to_claude",
                return_value=_claude_response(rows),
            ):
                result = categorize_inbox()
        ids = {s["task_id"] for s in result["suggestions"]}
        assert {str(t1.id), str(t2.id)} == ids
        # The omitted one should have the synthesized default.
        omitted = next(s for s in result["suggestions"] if s["task_id"] == str(t2.id))
        assert omitted["suggested_tier"] == "backlog"
        assert "review manually" in omitted["reason"]


# --- Subtask exclusion ------------------------------------------------------


class TestExclusions:
    def test_subtasks_not_included_in_call(self, app, monkeypatch):
        """Subtasks ride along with their parent — they shouldn't be sent
        to Claude or surface in suggestions."""
        from inbox_categorize_service import categorize_inbox

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with app.app_context():
            parent = _make_inbox_task("Parent")
            parent_id = str(parent.id)
            sub = Task(title="Sub", type=TaskType.WORK, tier=Tier.INBOX, parent_id=parent.id)
            db.session.add(sub)
            db.session.commit()
            sub_id = str(sub.id)
            row = {
                "task_id": parent_id,
                "suggested_tier": "today",
                "suggested_project_id": None,
                "suggested_goal_id": None,
                "suggested_due_date": None,
                "suggested_type": "work",
                "reason": "x",
            }
            with patch(
                "inbox_categorize_service._post_to_claude",
                return_value=_claude_response([row]),
            ):
                result = categorize_inbox()
        ids = {s["task_id"] for s in result["suggestions"]}
        assert parent_id in ids
        assert sub_id not in ids


# --- API contract -----------------------------------------------------------


class TestApiContract:
    def test_endpoint_returns_structured_response(self, authed_client, app, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with app.app_context():
            t = _make_inbox_task("Categorize me")
            row = {
                "task_id": str(t.id),
                "suggested_tier": "this_week",
                "suggested_project_id": None,
                "suggested_goal_id": None,
                "suggested_due_date": None,
                "suggested_type": "personal",
                "reason": "x",
            }
            with patch(
                "inbox_categorize_service._post_to_claude",
                return_value=_claude_response([row]),
            ):
                resp = authed_client.post("/api/inbox/categorize")
        assert resp.status_code == 200
        body = resp.get_json()
        assert set(body.keys()) == {"count", "suggestions", "capped"}
        assert body["count"] == 1
        sugg = body["suggestions"][0]
        assert set(sugg.keys()) == {
            "task_id", "title", "suggested_tier", "suggested_project_id",
            "suggested_goal_id", "suggested_due_date", "suggested_type", "reason",
        }

    def test_endpoint_502_on_claude_error(self, authed_client, app, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with app.app_context():
            _make_inbox_task("Categorize")
            with patch(
                "inbox_categorize_service._post_to_claude",
                side_effect=RuntimeError("Claude refused — vendor=Claude"),
            ):
                resp = authed_client.post("/api/inbox/categorize")
        assert resp.status_code == 502
        body = resp.get_json()
        assert "Claude" in body["error"]

    def test_endpoint_requires_auth(self, client):
        resp = client.post("/api/inbox/categorize")
        assert resp.status_code != 200
