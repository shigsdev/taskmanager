"""Integration tests for the weekly planner.

Service: ``weekly_planner_service.compute_weekly_plan(start_date)``
API:     ``POST /api/planner/weekly``
         ``POST /api/planner/ignore/<task_id>``

The Claude HTTP call is mocked via
``patch("weekly_planner_service._post_to_claude")``; we never hit the
real API. Tests focus on the validation pass that defends against:

  - Claude hallucinating task_ids / project_ids / goal_ids
  - Claude returning a due_date outside the target Mon–Sun window
  - Claude omitting tasks (backfilled with action="keep")
  - Stale freezer items leaking into the main plan
  - planner_ignore=True tasks being included anyway
  - update_task() failing to reset planner_ignore on field change
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

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
        resp = client.post("/api/planner/weekly", json={})
        assert resp.status_code != 200


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
