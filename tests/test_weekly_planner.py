"""Integration tests for the weekly planner.

Service: ``weekly_planner_service.compute_weekly_plan(start_date)``
API:     ``POST /api/planner/weekly``
         ``POST /api/planner/ignore/<task_id>``

The Claude HTTP call is mocked via
``patch("weekly_planner_service._post_to_claude")``; we never hit the
real API. Tests focus on the validation pass that defends against:

  - Claude hallucinating task_ids / project_ids / goal_ids
  - Claude returning a due_date outside the target Mon–Sun window
    (clamped for every tier today — #510 decides the far-off ones)
  - Claude omitting tasks (backfilled with action="keep") or naming one twice
  - an unreadable / cut-off reply (502, not 500 — #509)
  - Stale freezer items leaking into the main plan
  - planner_ignore=True tasks being included anyway
  - update_task() failing to reset planner_ignore on field change
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest

from models import (
    Task,
    TaskStatus,
    TaskType,
    Tier,
    db,
)


def _claude_response(plan: dict) -> dict:
    """Wrap a plan dict in the Claude HTTP body shape."""
    return {"content": [{"type": "text", "text": json.dumps(plan)}]}


def _make_task(
    *, title: str, tier: Tier, days_old: int = 0,
    status: TaskStatus = TaskStatus.ACTIVE,
    task_type: TaskType = TaskType.WORK,
    parent_id=None, planner_ignore: bool = False,
) -> Task:
    when = datetime.now(UTC) - timedelta(days=days_old)
    t = Task(
        title=title, type=task_type, tier=tier, status=status,
        parent_id=parent_id, planner_ignore=planner_ignore,
    )
    db.session.add(t)
    db.session.flush()
    t.created_at = when
    t.updated_at = when
    db.session.commit()
    return t


# --- Service: empty + happy paths -------------------------------------------


class TestEmptyPath:
    def test_returns_empty_plan_when_no_active_tasks(self, app, monkeypatch):
        from weekly_planner_service import compute_weekly_plan

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            result = compute_weekly_plan()
        assert result["active_count"] == 0
        assert result["per_task_suggestions"] == []
        assert result["model"] is None  # no Claude call when nothing to plan

    def test_does_not_call_claude_when_inputs_empty(self, app, monkeypatch):
        from weekly_planner_service import compute_weekly_plan

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with (
            app.app_context(),
            patch("weekly_planner_service._post_to_claude") as mock_post,
        ):
            compute_weekly_plan()
        assert mock_post.call_count == 0


class TestHappyPath:
    def test_returns_one_suggestion_per_active_task(self, app, monkeypatch):
        from weekly_planner_service import compute_weekly_plan

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            t1 = _make_task(title="A", tier=Tier.INBOX)
            t2 = _make_task(title="B", tier=Tier.TODAY)
            t1_id, t2_id = str(t1.id), str(t2.id)
            start = date(2026, 5, 4)  # a Monday
            plan = {
                "per_task_suggestions": [
                    {"task_id": t1_id, "action": "move",
                     "suggested_tier": "this_week",
                     "suggested_due_date": "2026-05-06",
                     "suggested_project_id": None, "suggested_goal_id": None,
                     "reason": "x"},
                    {"task_id": t2_id, "action": "keep",
                     "suggested_tier": None, "suggested_due_date": None,
                     "suggested_project_id": None, "suggested_goal_id": None,
                     "reason": "well-categorized"},
                ],
                "day_by_day_plan": {"Wednesday": [t1_id]},
                "goal_hints": [],
                "velocity_warning": None,
                "stale_freezer_review": [],
            }
            with patch(
                "weekly_planner_service._post_to_claude",
                return_value=_claude_response(plan),
            ):
                result = compute_weekly_plan(start_date=start)

        assert result["active_count"] == 2
        ids = {s["task_id"] for s in result["per_task_suggestions"]}
        assert ids == {t1_id, t2_id}
        assert result["day_by_day_plan"]["Wednesday"] == [t1_id]

    def test_freezer_tasks_excluded_from_main_plan(self, app, monkeypatch):
        from weekly_planner_service import compute_weekly_plan

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            active = _make_task(title="Active", tier=Tier.INBOX)
            frozen_recent = _make_task(title="Frozen recent", tier=Tier.FREEZER, days_old=10)
            frozen_old = _make_task(title="Frozen old", tier=Tier.FREEZER, days_old=90)
            active_id = str(active.id)
            frozen_old_id = str(frozen_old.id)
            plan = {
                "per_task_suggestions": [{
                    "task_id": active_id, "action": "keep",
                    "suggested_tier": None, "suggested_due_date": None,
                    "suggested_project_id": None, "suggested_goal_id": None,
                    "reason": "x",
                }],
                "day_by_day_plan": {},
                "goal_hints": [],
                "velocity_warning": None,
                "stale_freezer_review": [{
                    "task_id": frozen_old_id,
                    "recommendation": "thaw_to_backlog",
                    "reason": "frozen 90 days, may still be relevant",
                }],
            }
            with patch(
                "weekly_planner_service._post_to_claude",
                return_value=_claude_response(plan),
            ):
                result = compute_weekly_plan()

        # Active included, recent freezer excluded entirely, stale freezer in its own section.
        active_ids = {s["task_id"] for s in result["per_task_suggestions"]}
        stale_ids = {s["task_id"] for s in result["stale_freezer_review"]}
        assert active_id in active_ids
        # Make sure no freezer item leaked into main plan
        assert all(s["task_id"] != frozen_old_id for s in result["per_task_suggestions"])
        assert frozen_old_id in stale_ids
        # Recent freezer (only 10 days frozen) shouldn't appear anywhere
        assert all(
            s["task_id"] != str(frozen_recent.id)
            for s in result["per_task_suggestions"] + result["stale_freezer_review"]
        )


# --- Validation defenses ----------------------------------------------------


class TestValidation:
    def test_invalid_task_id_dropped(self, app, monkeypatch):
        from weekly_planner_service import compute_weekly_plan

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            t = _make_task(title="real", tier=Tier.INBOX)
            t_id = str(t.id)
            ghost = "11111111-2222-3333-4444-555555555555"
            plan = {
                "per_task_suggestions": [
                    {"task_id": t_id, "action": "keep",
                     "suggested_tier": None, "suggested_due_date": None,
                     "suggested_project_id": None, "suggested_goal_id": None, "reason": "ok"},
                    {"task_id": ghost, "action": "delete",
                     "suggested_tier": None, "suggested_due_date": None,
                     "suggested_project_id": None, "suggested_goal_id": None, "reason": "ghost"},
                ],
                "day_by_day_plan": {},
                "goal_hints": [],
                "velocity_warning": None,
                "stale_freezer_review": [],
            }
            with patch(
                "weekly_planner_service._post_to_claude",
                return_value=_claude_response(plan),
            ):
                result = compute_weekly_plan()
        ids = {s["task_id"] for s in result["per_task_suggestions"]}
        assert t_id in ids
        assert ghost not in ids

    def test_due_date_outside_target_week_clamped(self, app, monkeypatch):
        from weekly_planner_service import compute_weekly_plan

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            t = _make_task(title="x", tier=Tier.INBOX)
            t_id = str(t.id)
            start = date(2026, 5, 4)  # Mon
            plan = {
                "per_task_suggestions": [{
                    "task_id": t_id, "action": "move",
                    "suggested_tier": "this_week",
                    "suggested_due_date": "2026-06-15",  # weeks past target
                    "suggested_project_id": None, "suggested_goal_id": None,
                    "reason": "x",
                }],
                "day_by_day_plan": {},
                "goal_hints": [], "velocity_warning": None,
                "stale_freezer_review": [],
            }
            with patch(
                "weekly_planner_service._post_to_claude",
                return_value=_claude_response(plan),
            ):
                result = compute_weekly_plan(start_date=start)
        # Clamped to target_end (Sunday 2026-05-10)
        assert result["per_task_suggestions"][0]["suggested_due_date"] == "2026-05-10"

    def test_invalid_action_falls_back_to_keep(self, app, monkeypatch):
        from weekly_planner_service import compute_weekly_plan

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            t = _make_task(title="x", tier=Tier.INBOX)
            plan = {
                "per_task_suggestions": [{
                    "task_id": str(t.id), "action": "yeet",  # invalid
                    "suggested_tier": None, "suggested_due_date": None,
                    "suggested_project_id": None, "suggested_goal_id": None,
                    "reason": "x",
                }],
                "day_by_day_plan": {}, "goal_hints": [],
                "velocity_warning": None, "stale_freezer_review": [],
            }
            with patch(
                "weekly_planner_service._post_to_claude",
                return_value=_claude_response(plan),
            ):
                result = compute_weekly_plan()
        assert result["per_task_suggestions"][0]["action"] == "keep"

    def test_omitted_task_backfilled_with_keep(self, app, monkeypatch):
        from weekly_planner_service import compute_weekly_plan

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            t1 = _make_task(title="present", tier=Tier.INBOX)
            t2 = _make_task(title="omitted by Claude", tier=Tier.INBOX)
            t1_id = str(t1.id)
            t2_id = str(t2.id)
            plan = {
                "per_task_suggestions": [{
                    "task_id": t1_id, "action": "keep",
                    "suggested_tier": None, "suggested_due_date": None,
                    "suggested_project_id": None, "suggested_goal_id": None, "reason": "x",
                }],
                "day_by_day_plan": {}, "goal_hints": [],
                "velocity_warning": None, "stale_freezer_review": [],
            }
            with patch(
                "weekly_planner_service._post_to_claude",
                return_value=_claude_response(plan),
            ):
                result = compute_weekly_plan()
        ids = {s["task_id"] for s in result["per_task_suggestions"]}
        assert {t1_id, t2_id} == ids
        omitted = next(s for s in result["per_task_suggestions"] if s["task_id"] == t2_id)
        assert omitted["action"] == "keep"
        assert "review manually" in omitted["reason"]


# --- planner_ignore flag ----------------------------------------------------


class TestPlannerIgnoreFlag:
    def test_ignored_tasks_excluded_from_plan(self, app, monkeypatch):
        from weekly_planner_service import compute_weekly_plan

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            visible = _make_task(title="visible", tier=Tier.INBOX)
            ignored = _make_task(title="ignored", tier=Tier.INBOX, planner_ignore=True)
            visible_id = str(visible.id)
            ignored_id = str(ignored.id)
            plan = {
                "per_task_suggestions": [{
                    "task_id": visible_id, "action": "keep",
                    "suggested_tier": None, "suggested_due_date": None,
                    "suggested_project_id": None, "suggested_goal_id": None,
                    "reason": "x",
                }],
                "day_by_day_plan": {}, "goal_hints": [],
                "velocity_warning": None, "stale_freezer_review": [],
            }
            with patch(
                "weekly_planner_service._post_to_claude",
                return_value=_claude_response(plan),
            ):
                result = compute_weekly_plan()
        ids = {s["task_id"] for s in result["per_task_suggestions"]}
        assert visible_id in ids
        assert ignored_id not in ids

    def test_update_task_resets_planner_ignore_on_meaningful_change(self, app):
        """The 'stop suggesting until I touch it' contract — any
        meaningful field change must clear the flag so the next planner
        run reconsiders the task."""
        import uuid as uuid_module

        from task_service import update_task

        with app.app_context():
            t = _make_task(title="x", tier=Tier.INBOX, planner_ignore=True)
            t_id = t.id
            db.session.commit()
            # Sanity: flag set
            assert db.session.get(Task, t_id).planner_ignore is True
            # Touch a meaningful field
            update_task(uuid_module.UUID(str(t_id)), {"tier": "today"})
            t2 = db.session.get(Task, t_id)
            assert t2.planner_ignore is False, (
                "tier change should reset planner_ignore"
            )

    def test_update_task_does_not_reset_for_no_op_payload(self, app):
        """An empty / no-meaningful-fields payload shouldn't reset the
        flag — the user hasn't actually engaged with the task."""
        import uuid as uuid_module

        from task_service import update_task

        with app.app_context():
            t = _make_task(title="x", tier=Tier.INBOX, planner_ignore=True)
            t_id = t.id
            db.session.commit()
            # Update with a non-meaningful key
            update_task(uuid_module.UUID(str(t_id)), {"sort_order": 5})
            t2 = db.session.get(Task, t_id)
            assert t2.planner_ignore is True


# --- next_monday_from helper ------------------------------------------------


class TestNextMondayHelper:
    def test_friday_returns_following_monday(self):
        from weekly_planner_service import next_monday_from
        assert next_monday_from(date(2026, 5, 1)) == date(2026, 5, 4)  # Fri → Mon

    def test_monday_returns_next_monday(self):
        """If today IS a Monday, plan for the following week."""
        from weekly_planner_service import next_monday_from
        assert next_monday_from(date(2026, 5, 4)) == date(2026, 5, 11)

    def test_sunday_returns_tomorrow(self):
        from weekly_planner_service import next_monday_from
        assert next_monday_from(date(2026, 5, 3)) == date(2026, 5, 4)


# --- API contract ----------------------------------------------------------


class TestPlannerWeeklyAPI:
    def test_endpoint_returns_structured_response(self, authed_client, app, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            t = _make_task(title="x", tier=Tier.INBOX)
            plan = {
                "per_task_suggestions": [{
                    "task_id": str(t.id), "action": "keep",
                    "suggested_tier": None, "suggested_due_date": None,
                    "suggested_project_id": None, "suggested_goal_id": None,
                    "reason": "x",
                }],
                "day_by_day_plan": {}, "goal_hints": [],
                "velocity_warning": None, "stale_freezer_review": [],
            }
            with patch(
                "weekly_planner_service._post_to_claude",
                return_value=_claude_response(plan),
            ):
                resp = authed_client.post(
                    "/api/planner/weekly",
                    json={"start_date": "2026-05-04"},
                )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "per_task_suggestions" in body
        assert "day_by_day_plan" in body
        assert "goal_hints" in body
        assert "stale_freezer_review" in body

    def test_rejects_non_monday_start_date(self, authed_client):
        # 2026-05-06 is a Wednesday — must be a Monday for plans
        resp = authed_client.post(
            "/api/planner/weekly",
            json={"start_date": "2026-05-06"},
        )
        assert resp.status_code == 422

    def test_rejects_malformed_date(self, authed_client):
        resp = authed_client.post(
            "/api/planner/weekly",
            json={"start_date": "not-a-date"},
        )
        assert resp.status_code == 422

    def test_endpoint_502_on_claude_error(self, authed_client, app, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            _make_task(title="x", tier=Tier.INBOX)
            with patch(
                "weekly_planner_service._post_to_claude",
                side_effect=RuntimeError("Claude unavailable"),
            ):
                resp = authed_client.post(
                    "/api/planner/weekly",
                    json={"start_date": "2026-05-04"},
                )
        assert resp.status_code == 502

    def test_endpoint_requires_auth(self, client):
        for path in ("/api/planner/weekly", f"/api/planner/ignore/{uuid.uuid4()}"):
            resp = client.post(path, json={"ignore": True})
            assert resp.status_code == 401, path


# --- Ignore endpoint -------------------------------------------------------


class TestPlannerIgnoreEndpoint:
    def test_sets_flag_to_true(self, authed_client, app):
        with app.app_context():
            t = _make_task(title="x", tier=Tier.INBOX)
            t_id = str(t.id)
        resp = authed_client.post(
            f"/api/planner/ignore/{t_id}",
            json={"ignore": True},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["planner_ignore"] is True
        with app.app_context():
            import uuid as _uuid
            refreshed = db.session.get(Task, _uuid.UUID(t_id))
            assert refreshed.planner_ignore is True

    def test_sets_flag_to_false(self, authed_client, app):
        with app.app_context():
            t = _make_task(title="x", tier=Tier.INBOX, planner_ignore=True)
            t_id = str(t.id)
        resp = authed_client.post(
            f"/api/planner/ignore/{t_id}",
            json={"ignore": False},
        )
        assert resp.status_code == 200
        with app.app_context():
            import uuid as _uuid
            refreshed = db.session.get(Task, _uuid.UUID(t_id))
            assert refreshed.planner_ignore is False

    def test_400_when_body_missing_ignore_field(self, authed_client, app):
        with app.app_context():
            t = _make_task(title="x", tier=Tier.INBOX)
            t_id = str(t.id)
        resp = authed_client.post(f"/api/planner/ignore/{t_id}", json={})
        assert resp.status_code == 400

    def test_404_for_nonexistent_task(self, authed_client):
        ghost = "11111111-2222-3333-4444-555555555555"
        resp = authed_client.post(
            f"/api/planner/ignore/{ghost}",
            json={"ignore": True},
        )
        assert resp.status_code == 404


# --- #509: what the 2026-10-19 refresh found untested --------------------------


START = date(2026, 5, 4)  # a Monday


def _keep(task_id: str, **over) -> dict:
    row = {
        "task_id": task_id, "action": "keep", "suggested_tier": None,
        "suggested_due_date": None, "suggested_project_id": None,
        "suggested_goal_id": None, "reason": "x",
    }
    row.update(over)
    return row


def _plan(rows=(), **extra) -> dict:
    plan = {
        "per_task_suggestions": list(rows), "goal_hints": [],
        "velocity_warning": None, "stale_freezer_review": [],
    }
    plan.update(extra)
    return plan


def _run(response: dict, start: date | None = START) -> dict:
    """compute_weekly_plan with Claude answering ``response`` (the raw
    HTTP body). Call inside an app context with the key set."""
    from weekly_planner_service import compute_weekly_plan

    with patch("weekly_planner_service._post_to_claude", return_value=response):
        return compute_weekly_plan(start_date=start)


class TestClaudeAnswersBadly:
    """A reply cut off at max_tokens (likely with 100 tasks) or not JSON
    at all must be a 502 the /plan page can show, never a 500."""

    @pytest.mark.parametrize("response", [
        {"content": [{"type": "text", "text": "oops, not json"}]},
        {"content": [{"type": "text", "text": '{"per_task_suggestions": [{"task'}]},
        {"content": []},
        {"content": None},
        {},
        {"content": ["not a dict"]},
    ])
    def test_unreadable_reply_is_a_502(self, authed_client, app, monkeypatch, response):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            _make_task(title="x", tier=Tier.INBOX)
            with patch("weekly_planner_service._post_to_claude", return_value=response):
                resp = authed_client.post(
                    "/api/planner/weekly", json={"start_date": "2026-05-04"})
        assert resp.status_code == 502
        assert "try again" in resp.get_json()["error"].lower()

    def test_no_api_key_is_a_502(self, authed_client, app, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with app.app_context():
            _make_task(title="x", tier=Tier.INBOX)
            resp = authed_client.post("/api/planner/weekly", json={})
        assert resp.status_code == 502
        assert "not configured" in resp.get_json()["error"]

    def test_json_inside_a_code_fence_is_read(self, app, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            t_id = str(_make_task(title="x", tier=Tier.INBOX).id)
            fenced = "Here you go:\n```json\n" + json.dumps(
                _plan([_keep(t_id, reason="fenced")])) + "\n```"
            result = _run({"content": [{"type": "text", "text": fenced}]})
        assert result["per_task_suggestions"][0]["reason"] == "fenced"

    def test_model_reported_is_the_one_called(self, app, monkeypatch):
        from claude_client import HAIKU

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            t_id = str(_make_task(title="x", tier=Tier.INBOX).id)
            result = _run(_claude_response(_plan([_keep(t_id)])))
        assert result["model"] == HAIKU


class TestRowValidation:

    def test_unknown_or_archived_project_and_unknown_goal_are_dropped(
            self, app, monkeypatch):
        from models import Project, ProjectType

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            t_id = str(_make_task(title="x", tier=Tier.INBOX).id)
            archived = Project(name="Old", type=ProjectType.WORK, is_active=False)
            db.session.add(archived)
            db.session.commit()
            rows = [_keep(t_id, suggested_project_id=str(archived.id),
                          suggested_goal_id="00000000-0000-0000-0000-000000000000")]
            result = _run(_claude_response(_plan(rows)))
        row = result["per_task_suggestions"][0]
        assert row["suggested_project_id"] is None
        assert row["suggested_goal_id"] is None

    def test_a_task_returned_twice_keeps_the_first_row(self, app, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            t_id = str(_make_task(title="x", tier=Tier.INBOX).id)
            rows = [_keep(t_id, action="move", suggested_tier="this_week"),
                    _keep(t_id, action="delete")]
            result = _run(_claude_response(_plan(rows)))
        assert [r["action"] for r in result["per_task_suggestions"]] == ["move"]

    @pytest.mark.parametrize("due,expected", [
        ("2026-02-30", None),          # not a real day
        ("5/6/2026", None),            # not ISO
        (123, None),                   # not a string
        ("2026-04-01", "2026-05-04"),  # before the week → its Monday
        ("2026-05-07", "2026-05-07"),  # inside the week → as given
    ])
    def test_due_date_shapes(self, app, monkeypatch, due, expected):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            t_id = str(_make_task(title="x", tier=Tier.INBOX).id)
            rows = [_keep(t_id, action="move", suggested_tier="this_week",
                          suggested_due_date=due)]
            result = _run(_claude_response(_plan(rows)))
        assert result["per_task_suggestions"][0]["suggested_due_date"] == expected

    def test_day_by_day_comes_from_move_dates_not_from_claude(self, app, monkeypatch):
        """Claude's own day_by_day_plan is ignored; the server rebuilds it
        from each move's date, and a keep row with a date isn't placed."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            mover = str(_make_task(title="m", tier=Tier.INBOX).id)
            keeper = str(_make_task(title="k", tier=Tier.INBOX).id)
            rows = [
                _keep(mover, action="move", suggested_tier="this_week",
                      suggested_due_date="2026-05-08"),
                _keep(keeper, suggested_due_date="2026-05-05"),
            ]
            result = _run(_claude_response(_plan(
                rows, day_by_day_plan={"Monday": [keeper, mover]})))
        plan = result["day_by_day_plan"]
        assert plan["Friday"] == [mover]
        assert all(keeper not in ids for ids in plan.values())
        assert plan["Monday"] == []

    def test_rows_carry_title_and_task_type(self, app, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            t_id = str(_make_task(title="Call the bank", tier=Tier.INBOX,
                                  task_type=TaskType.PERSONAL).id)
            result = _run(_claude_response(_plan([_keep(t_id)])))
        row = result["per_task_suggestions"][0]
        assert (row["title"], row["task_type"]) == ("Call the bank", "personal")


class TestWhatIsSentToClaude:

    def test_subtasks_are_not_planned_or_backfilled(self, app, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            parent = _make_task(title="parent", tier=Tier.INBOX)
            child = _make_task(title="child", tier=Tier.INBOX, parent_id=parent.id)
            with patch("weekly_planner_service._post_to_claude",
                       return_value=_claude_response(_plan())) as post:
                from weekly_planner_service import compute_weekly_plan
                result = compute_weekly_plan(start_date=START)
            prompt = post.call_args[0][1]
            parent_id, child_id = str(parent.id), str(child.id)
        assert child_id not in prompt
        assert {r["task_id"] for r in result["per_task_suggestions"]} == {parent_id}

    def test_only_the_oldest_hundred_are_sent(self, app, monkeypatch):
        import weekly_planner_service as wps

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        monkeypatch.setattr(wps, "MAX_TASKS_PER_CALL", 3)
        with app.app_context():
            ids = [str(_make_task(title=f"t{n}", tier=Tier.INBOX, days_old=10 - n).id)
                   for n in range(4)]
            result = _run(_claude_response(_plan()))
        assert result["active_count"] == 3
        sent = {r["task_id"] for r in result["per_task_suggestions"]}
        assert sent == set(ids[:3])  # the newest one waits for next time

    def test_a_freezer_only_week_still_asks_about_stale_items(self, app, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            frozen = _make_task(title="old idea", tier=Tier.FREEZER, days_old=90)
            _make_task(title="ignored idea", tier=Tier.FREEZER, days_old=90,
                       planner_ignore=True)
            review = [{"task_id": str(frozen.id), "recommendation": "delete",
                       "reason": "stale"}]
            with patch("weekly_planner_service._post_to_claude",
                       return_value=_claude_response(
                           _plan(stale_freezer_review=review))) as post:
                from weekly_planner_service import compute_weekly_plan
                result = compute_weekly_plan(start_date=START)
        assert post.call_count == 1
        assert result["stale_freezer_count"] == 1
        assert [r["title"] for r in result["stale_freezer_review"]] == ["old idea"]


class TestGoalHintsAndVelocity:

    def test_goal_hints_are_cleaned_and_filled_in(self, app, monkeypatch):
        from models import Goal, GoalCategory, GoalPriority

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            t_id = str(_make_task(title="x", tier=Tier.INBOX).id)
            hinted = Goal(title="Run 5k", category=GoalCategory.HEALTH,
                          priority=GoalPriority.MUST)
            skipped = Goal(title="Read more", category=GoalCategory.PERSONAL_GROWTH,
                           priority=GoalPriority.COULD)
            db.session.add_all([hinted, skipped])
            db.session.commit()
            hints = [
                {"goal_id": str(hinted.id), "status": "sideways", "recommendation": "go"},
                {"goal_id": "not-a-goal", "status": "on_track", "recommendation": "x"},
            ]
            result = _run(_claude_response(_plan([_keep(t_id)], goal_hints=hints)))
            hinted_id, skipped_id = str(hinted.id), str(skipped.id)
        by_id = {h["goal_id"]: h for h in result["goal_hints"]}
        assert set(by_id) == {hinted_id, skipped_id}
        assert by_id[hinted_id]["status"] == "no_progress"   # bad status
        assert by_id[hinted_id]["goal_title"] == "Run 5k"
        assert "no hint returned" in by_id[skipped_id]["recommendation"]

    @pytest.mark.parametrize("raw,expected", [
        ("   ", None), (5, None), (None, None),
        ("  Too much this week.  ", "Too much this week."),
        ("x" * 300, "x" * 240),
    ])
    def test_velocity_warning_is_trimmed(self, app, monkeypatch, raw, expected):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            t_id = str(_make_task(title="x", tier=Tier.INBOX).id)
            result = _run(_claude_response(
                _plan([_keep(t_id)], velocity_warning=raw)))
        assert result["velocity_warning"] == expected


class TestStartDate:

    @pytest.mark.parametrize("bad", [5, ["2026-05-04"], True])
    def test_non_string_start_date_is_422(self, authed_client, bad):
        resp = authed_client.post("/api/planner/weekly", json={"start_date": bad})
        assert resp.status_code == 422

    @pytest.mark.parametrize("empty", ["", None, 0])
    def test_empty_start_date_means_next_monday(self, authed_client, app, monkeypatch,
                                                empty):
        """Pinned: an empty value plans the coming week, as if it were
        left out (the /plan page always sends its picker's Monday)."""
        from utils import local_today_date
        from weekly_planner_service import next_monday_from

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        resp = authed_client.post("/api/planner/weekly", json={"start_date": empty})
        assert resp.status_code == 200
        assert resp.get_json()["start_date"] == next_monday_from(
            local_today_date()).isoformat()


class TestIgnoreResetCoversEveryField:

    @pytest.mark.parametrize("field,value", [
        ("title", "renamed"), ("type", "personal"), ("tier", "today"),
        ("status", "archived"), ("project_id", None), ("goal_id", None),
        ("due_date", None), ("url", None), ("notes", "n"), ("checklist", []),
        ("cancellation_reason", None), ("parent_id", None),
    ])
    def test_touching_any_meaningful_field_clears_ignore(self, app, field, value):
        from task_service import update_task

        with app.app_context():
            t = _make_task(title="x", tier=Tier.INBOX, planner_ignore=True)
            update_task(t.id, {field: value})
            db.session.expire_all()
            assert db.session.get(Task, t.id).planner_ignore is False
