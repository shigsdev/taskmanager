"""#325: the reflection milestone — runway + continuity.

Before this, every reflection was analysed COLD: Claude had no idea a
deadline existed and no memory of what the user committed to last week,
so a multi-week plan never compounded. These tests pin the two halves:

  * the milestone resolves correctly (including when a LINKED goal is
    renamed, completed, or deleted — degrading loudly, never silently);
  * the runway and the previous reflections actually reach the prompt.

The prompt assertions go through ``_call_claude`` and inspect what was
really sent, rather than string-matching source (anti-pattern #3).
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from unittest.mock import patch

import pytest

import auth
from models import (
    AppSetting,
    Goal,
    GoalCategory,
    GoalPriority,
    GoalStatus,
    ReflectionInputMode,
    db,
)


def _bypass_auth(monkeypatch):
    monkeypatch.setattr(
        auth, "get_current_user_email", lambda: "me@example.com"
    )


def _make_goal(app, title="Start the new role prepared", status=None):
    with app.app_context():
        g = Goal(
            title=title,
            category=GoalCategory.WORK,
            priority=GoalPriority.MUST,
            status=status or GoalStatus.IN_PROGRESS,
        )
        db.session.add(g)
        db.session.commit()
        return str(g.id)


# --- pure countdown math -----------------------------------------------------


class TestCountdown:
    def test_none_target_is_all_none(self, app):
        from milestone_service import countdown
        assert countdown(None) == {
            "days_left": None, "weeks_left": None, "passed": False,
        }

    def test_the_target_day_itself_is_zero_days_left(self, app):
        from milestone_service import countdown
        out = countdown(date(2026, 11, 2), date(2026, 11, 2))
        assert out["days_left"] == 0
        assert out["passed"] is False

    def test_future_target(self, app):
        from milestone_service import countdown
        out = countdown(date(2026, 11, 2), date(2026, 9, 22))
        assert out["days_left"] == 41
        # 41 days rounds UP to 6 weeks — "5 weeks" would undersell the runway.
        assert out["weeks_left"] == 6
        assert out["passed"] is False

    def test_weeks_round_up_not_down(self, app):
        from milestone_service import countdown
        assert countdown(date(2026, 1, 7), date(2026, 1, 1))["weeks_left"] == 1
        assert countdown(date(2026, 1, 8), date(2026, 1, 1))["weeks_left"] == 1
        assert countdown(date(2026, 1, 9), date(2026, 1, 1))["weeks_left"] == 2

    def test_past_target_reports_negative_not_clamped(self, app):
        """A milestone that has gone by must SAY so, not read '0 days
        left' forever."""
        from milestone_service import countdown
        out = countdown(date(2026, 9, 1), date(2026, 9, 22))
        assert out["days_left"] == -21
        assert out["passed"] is True


# --- resolution --------------------------------------------------------------


class TestMilestoneResolution:
    def test_unconfigured(self, app):
        from milestone_service import get_milestone
        with app.app_context():
            m = get_milestone()
        assert m["configured"] is False
        assert m["source"] is None
        assert m["date"] is None

    def test_custom_label_and_date(self, app):
        from milestone_service import get_milestone, set_milestone
        with app.app_context():
            set_milestone(label="New role", target_date="2026-11-02")
            m = get_milestone(today=date(2026, 9, 22))
        assert m["configured"] is True
        assert m["source"] == "custom"
        assert m["label"] == "New role"
        assert m["date"] == "2026-11-02"
        assert m["days_left"] == 41

    def test_linked_goal_supplies_the_label(self, app):
        from milestone_service import get_milestone, set_milestone
        gid = _make_goal(app)
        with app.app_context():
            set_milestone(goal_id=gid, target_date="2026-11-02")
            m = get_milestone(today=date(2026, 9, 22))
        assert m["source"] == "goal"
        assert m["label"] == "Start the new role prepared"
        assert m["goal_id"] == gid
        assert m["warning"] is None

    def test_label_FOLLOWS_a_renamed_goal(self, app):
        """The point of linking: rename the goal, the header follows."""
        from milestone_service import get_milestone, set_milestone
        gid = _make_goal(app)
        with app.app_context():
            set_milestone(goal_id=gid, target_date="2026-11-02")
            goal = db.session.get(Goal, uuid.UUID(gid))
            goal.title = "Land well in the new job"
            db.session.commit()
            m = get_milestone()
        assert m["label"] == "Land well in the new job"

    def test_deleted_goal_warns_and_falls_back(self, app):
        """Degrade LOUDLY. A countdown that quietly stops tracking is
        worse than no countdown."""
        from milestone_service import get_milestone, set_milestone
        gid = _make_goal(app)
        with app.app_context():
            set_milestone(goal_id=gid, target_date="2026-11-02")
            goal = db.session.get(Goal, uuid.UUID(gid))
            goal.is_active = False
            db.session.commit()
            m = get_milestone()
        assert m["warning"] is not None
        assert "deleted" in m["warning"]
        # The saved title is still shown rather than a blank header.
        assert m["label"] == "Start the new role prepared"
        assert m["date"] == "2026-11-02"

    def test_completed_goal_warns_but_keeps_tracking(self, app):
        from milestone_service import get_milestone, set_milestone
        gid = _make_goal(app)
        with app.app_context():
            set_milestone(goal_id=gid, target_date="2026-11-02")
            goal = db.session.get(Goal, uuid.UUID(gid))
            goal.status = GoalStatus.DONE
            db.session.commit()
            m = get_milestone()
        assert m["source"] == "goal"
        assert "done" in m["warning"]

    def test_vanished_goal_row_warns(self, app):
        from milestone_service import GOAL_ID_KEY, get_milestone
        with app.app_context():
            db.session.add(
                AppSetting(key=GOAL_ID_KEY, value=str(uuid.uuid4()))
            )
            db.session.commit()
            m = get_milestone()
        assert m["warning"] is not None
        assert "no longer exists" in m["warning"]

    def test_setting_a_label_unlinks_the_goal(self, app):
        from milestone_service import get_milestone, set_milestone
        gid = _make_goal(app)
        with app.app_context():
            set_milestone(goal_id=gid, target_date="2026-11-02")
            set_milestone(label="Something else", target_date="2026-12-01")
            m = get_milestone()
        assert m["source"] == "custom"
        assert m["goal_id"] is None
        assert m["label"] == "Something else"

    def test_clear_removes_everything(self, app):
        from milestone_service import clear_milestone, get_milestone, set_milestone
        with app.app_context():
            set_milestone(label="New role", target_date="2026-11-02")
            clear_milestone()
            m = get_milestone()
        assert m["configured"] is False
        assert m["label"] is None

    def test_bad_date_and_bad_goal_raise(self, app):
        from milestone_service import set_milestone
        with app.app_context():
            with pytest.raises(ValueError, match="YYYY-MM-DD"):
                set_milestone(label="x", target_date="Nov 2nd")
            with pytest.raises(ValueError, match="goal"):
                set_milestone(goal_id=str(uuid.uuid4()))


# --- what actually reaches Claude --------------------------------------------


def _capture_prompt(app, transcript="This week I did some prep."):
    """Run analyze_reflection with a stubbed Claude and return the
    prompt string that was really sent."""
    seen = {}

    def fake_call(api_key, prompt, *a, **kw):
        seen["prompt"] = prompt
        return {
            "content": [{"text": json.dumps({"explicit": [], "suggested": []})}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    with patch("reflection_service._call_claude", side_effect=fake_call):
        from reflection_service import analyze_reflection
        analyze_reflection(transcript)
    return seen.get("prompt", "")


class TestRunwayReachesThePrompt:
    def test_milestone_appears_in_the_prompt(self, app, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        from milestone_service import set_milestone
        with app.app_context():
            set_milestone(label="New role", target_date="2099-01-01")
            prompt = _capture_prompt(app)
        assert "New role" in prompt
        assert "2099-01-01" in prompt
        assert "Sequence and time-box" in prompt

    def test_no_milestone_means_no_runway_text(self, app, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with app.app_context():
            prompt = _capture_prompt(app)
        assert "Sequence and time-box" not in prompt
        # The prompt must still be well-formed without it.
        assert "PROJECTS" in prompt and "ACTIVE TASKS" in prompt

    def test_linked_goal_id_is_offered_for_attachment(self, app, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        gid = _make_goal(app)
        from milestone_service import set_milestone
        with app.app_context():
            set_milestone(goal_id=gid, target_date="2099-01-01")
            prompt = _capture_prompt(app)
        assert gid in prompt
        assert "attach related" in prompt


class TestContinuityReachesThePrompt:
    def _save(self, app, text):
        with app.app_context():
            from reflection_service import save_reflection
            r = save_reflection(
                transcript=text,
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            return r.id

    def test_previous_reflections_are_included(self, app, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        self._save(app, "Week one: I set up the reading list.")
        with app.app_context():
            prompt = _capture_prompt(app, "Week two: I got through two books.")
        assert "Week one: I set up the reading list." in prompt
        assert "PREVIOUS reflections" in prompt

    def test_no_history_means_no_continuity_block(self, app, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with app.app_context():
            prompt = _capture_prompt(app)
        assert "PREVIOUS reflections" not in prompt

    def test_only_the_most_recent_three_are_included(self, app, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        for i in range(5):
            self._save(app, f"Reflection number {i}.")
        with app.app_context():
            prompt = _capture_prompt(app)
        included = [i for i in range(5) if f"Reflection number {i}." in prompt]
        assert len(included) == 3, f"expected 3 prior reflections, got {included}"

    def test_a_reflection_is_excluded_from_its_own_context(self, app, monkeypatch):
        """The API saves the transcript BEFORE analysing, so without the
        exclusion Claude would receive this week's words twice — once as
        'the reflection' and once as 'what you said previously'."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        rid = self._save(app, "UNIQUE-MARKER this very reflection.")
        seen = {}

        def fake_call(api_key, prompt, *a, **kw):
            seen["prompt"] = prompt
            return {
                "content": [{"text": json.dumps({"explicit": [], "suggested": []})}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }

        with app.app_context(), patch(
            "reflection_service._call_claude", side_effect=fake_call
        ):
            from reflection_service import analyze_reflection
            analyze_reflection("UNIQUE-MARKER this very reflection.", exclude_id=rid)

        prompt = seen["prompt"]
        # Present once (as the reflection under analysis), never as history.
        assert "PREVIOUS reflections" not in prompt

    def test_drafts_never_leak_into_continuity(self, app, monkeypatch):
        """An unsubmitted draft is not something the user 'said before'."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with app.app_context():
            from reflection_service import save_draft
            save_draft(transcript="DRAFT-ONLY half a thought")
            prompt = _capture_prompt(app)
        assert "DRAFT-ONLY" not in prompt

    def test_long_transcripts_are_truncated(self, app, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        self._save(app, "x" * 5000)
        with app.app_context():
            prompt = _capture_prompt(app)
        assert "x" * 5000 not in prompt
        assert "…" in prompt


# --- API ---------------------------------------------------------------------


class TestMilestoneApi:
    def test_get_put_delete_round_trip(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        assert client.get("/api/reflection/milestone").get_json()[
            "configured"
        ] is False

        resp = client.put(
            "/api/reflection/milestone",
            json={"label": "New role", "target_date": "2026-11-02"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["label"] == "New role"
        assert body["date"] == "2026-11-02"

        assert client.delete("/api/reflection/milestone").status_code == 204
        assert client.get("/api/reflection/milestone").get_json()[
            "configured"
        ] is False

    def test_link_a_goal_via_api(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        gid = _make_goal(app)
        resp = client.put(
            "/api/reflection/milestone",
            json={"goal_id": gid, "target_date": "2026-11-02"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["source"] == "goal"
        assert body["goal_id"] == gid

    def test_bad_input_is_422_not_500(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        assert client.put(
            "/api/reflection/milestone", json={"target_date": "tomorrow"},
        ).status_code == 422
        assert client.put(
            "/api/reflection/milestone", json={"goal_id": "not-a-uuid"},
        ).status_code == 422

    def test_milestone_endpoints_require_auth(self, app, client):
        for call in (
            lambda: client.get("/api/reflection/milestone"),
            lambda: client.put("/api/reflection/milestone", json={"label": "x"}),
            lambda: client.delete("/api/reflection/milestone"),
        ):
            assert call().status_code in (302, 401, 403)
