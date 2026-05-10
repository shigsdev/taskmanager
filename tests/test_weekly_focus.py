"""Tests for the Weekly Focus panel (Feature 1).

Covers:
  - service: read/upsert/clear semantics including carry-forward
  - service: slot-count validation + clamp
  - API: GET / PATCH / DELETE / settings round-trip
  - API: auth required (no session = 401)
  - service: AI plan_for_focus validation (mocked Claude — drop bad
    rows, accept good ones, never invent IDs)
"""
from __future__ import annotations

import json
import uuid
from datetime import date

import pytest

import auth
import weekly_focus_service
from models import Goal, GoalCategory, GoalPriority, Task, TaskStatus, TaskType, Tier, db
from weekly_focus_service import (
    DEFAULT_SLOT_COUNT,
    MAX_SLOT_COUNT,
    MIN_SLOT_COUNT,
    clear_slot,
    get_displayed_focus,
    get_slot_count,
    monday_of,
    plan_for_focus,
    set_slot_count,
    upsert_slot,
)

# --- Pure helper -------------------------------------------------------------


class TestMondayOf:
    def test_monday_returns_self(self):
        d = date(2026, 5, 11)  # Monday
        assert monday_of(d) == d

    def test_wednesday_returns_monday(self):
        d = date(2026, 5, 13)  # Wednesday
        assert monday_of(d) == date(2026, 5, 11)

    def test_sunday_returns_previous_monday(self):
        d = date(2026, 5, 17)  # Sunday
        assert monday_of(d) == date(2026, 5, 11)


# --- Slot count --------------------------------------------------------------


class TestSlotCount:
    def test_default_when_unset(self, app):
        with app.app_context():
            assert get_slot_count() == DEFAULT_SLOT_COUNT

    def test_set_and_read(self, app):
        with app.app_context():
            set_slot_count(5)
            assert get_slot_count() == 5

    def test_clamps_too_low(self, app):
        with app.app_context():
            assert set_slot_count(0) == MIN_SLOT_COUNT
            assert get_slot_count() == MIN_SLOT_COUNT

    def test_clamps_too_high(self, app):
        with app.app_context():
            assert set_slot_count(99) == MAX_SLOT_COUNT
            assert get_slot_count() == MAX_SLOT_COUNT

    def test_invalid_value_falls_back_to_default(self, app):
        # Simulate a corrupted value in the table.
        from models import AppSetting
        with app.app_context():
            db.session.add(
                AppSetting(key="weekly_focus_slot_count", value="not-a-number")
            )
            db.session.commit()
            assert get_slot_count() == DEFAULT_SLOT_COUNT


# --- Read/upsert/clear -------------------------------------------------------


class TestUpsertAndDisplay:
    def test_first_save_creates_row(self, app):
        today = date(2026, 5, 13)  # Wednesday
        with app.app_context():
            row = upsert_slot(slot_order=1, text="Ship the auth refresh", today=today)
            assert row.text == "Ship the auth refresh"
            assert row.week_start_date == date(2026, 5, 11)  # Monday
            assert row.is_active is True

    def test_second_save_updates_same_row(self, app):
        today = date(2026, 5, 13)
        with app.app_context():
            r1 = upsert_slot(slot_order=1, text="First", today=today)
            r2 = upsert_slot(slot_order=1, text="Second", today=today)
            assert r1.id == r2.id  # same row, updated
            assert r2.text == "Second"

    def test_displayed_returns_current_week_when_present(self, app):
        today = date(2026, 5, 13)
        with app.app_context():
            upsert_slot(slot_order=1, text="Focus A", today=today)
            d = get_displayed_focus(today=today)
            assert d["week_start_date"] == "2026-05-11"
            assert d["fallback_from"] is None
            assert len(d["slots"]) == 1
            assert d["slots"][0]["text"] == "Focus A"

    def test_carry_forward_when_current_week_empty(self, app):
        # User set slot last week, never touched it this week → display
        # should show last week's text with fallback_from set.
        last_week = date(2026, 5, 6)  # Wednesday of previous ISO week
        this_week_day = date(2026, 5, 13)
        with app.app_context():
            upsert_slot(slot_order=1, text="Last week's focus", today=last_week)
            d = get_displayed_focus(today=this_week_day)
            assert d["week_start_date"] == "2026-05-11"  # current week
            assert d["fallback_from"] == "2026-05-04"  # last week's Monday
            assert len(d["slots"]) == 1
            assert d["slots"][0]["text"] == "Last week's focus"

    def test_clear_soft_deletes_only_current_week(self, app):
        last_week = date(2026, 5, 6)
        this_week_day = date(2026, 5, 13)
        with app.app_context():
            upsert_slot(slot_order=1, text="Old", today=last_week)
            upsert_slot(slot_order=1, text="New", today=this_week_day)
            assert clear_slot(1, today=this_week_day) is True
            d = get_displayed_focus(today=this_week_day)
            # Cleared current week → falls back to last week (preserved).
            assert d["fallback_from"] == "2026-05-04"
            assert d["slots"][0]["text"] == "Old"

    def test_clear_returns_false_when_nothing_to_clear(self, app):
        today = date(2026, 5, 13)
        with app.app_context():
            assert clear_slot(2, today=today) is False

    def test_goal_link_validates_existence(self, app):
        today = date(2026, 5, 13)
        with app.app_context():
            ghost = uuid.uuid4()
            with pytest.raises(ValueError, match="not found"):
                upsert_slot(
                    slot_order=1, text="x", goal_id=ghost, today=today,
                )

    def test_goal_link_persists_when_valid(self, app):
        today = date(2026, 5, 13)
        with app.app_context():
            g = Goal(
                title="Q2 OKRs", category=GoalCategory.WORK,
                priority=GoalPriority.MUST,
            )
            db.session.add(g)
            db.session.commit()
            row = upsert_slot(
                slot_order=1, text="Ship Q2 OKR feature",
                goal_id=g.id, today=today,
            )
            assert row.goal_id == g.id
            d = get_displayed_focus(today=today)
            assert d["slots"][0]["goal_id"] == str(g.id)
            assert d["slots"][0]["goal_title"] == "Q2 OKRs"


class TestUpsertValidation:
    def test_slot_order_below_range(self, app):
        with app.app_context(), pytest.raises(ValueError, match="slot_order"):
            upsert_slot(slot_order=0, text="x")

    def test_slot_order_above_count(self, app):
        with app.app_context():
            set_slot_count(3)
            with pytest.raises(ValueError, match="slot_order"):
                upsert_slot(slot_order=4, text="x")

    def test_empty_text_rejected(self, app):
        with app.app_context(), pytest.raises(ValueError, match="text required"):
            upsert_slot(slot_order=1, text="")

    def test_whitespace_text_rejected(self, app):
        with app.app_context(), pytest.raises(ValueError, match="text required"):
            upsert_slot(slot_order=1, text="   ")

    def test_text_truncated_at_500(self, app):
        today = date(2026, 5, 13)
        with app.app_context():
            row = upsert_slot(slot_order=1, text="x" * 600, today=today)
            assert len(row.text) == 500


# --- API ---------------------------------------------------------------------


class TestWeeklyFocusAPI:
    def test_get_empty_returns_default_slot_count(self, authed_client):
        resp = authed_client.get("/api/weekly-focus")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["slot_count"] == DEFAULT_SLOT_COUNT
        assert body["slots"] == []

    def test_patch_creates_slot(self, authed_client):
        resp = authed_client.patch(
            "/api/weekly-focus/1",
            json={"text": "Ship the auth refresh"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["slots"][0]["text"] == "Ship the auth refresh"

    def test_patch_with_invalid_goal_id(self, authed_client):
        resp = authed_client.patch(
            "/api/weekly-focus/1",
            json={"text": "x", "goal_id": "not-a-uuid"},
        )
        assert resp.status_code == 422

    def test_delete_clears_slot(self, authed_client):
        authed_client.patch("/api/weekly-focus/1", json={"text": "x"})
        resp = authed_client.delete("/api/weekly-focus/1")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["cleared"] is True

    def test_settings_round_trip(self, authed_client):
        resp = authed_client.patch(
            "/api/weekly-focus/settings/slot-count",
            json={"slot_count": 5},
        )
        assert resp.status_code == 200
        assert resp.get_json()["slot_count"] == 5
        assert authed_client.get("/api/weekly-focus").get_json()["slot_count"] == 5

    def test_settings_clamps(self, authed_client):
        resp = authed_client.patch(
            "/api/weekly-focus/settings/slot-count",
            json={"slot_count": 99},
        )
        assert resp.get_json()["slot_count"] == MAX_SLOT_COUNT

    def test_settings_rejects_non_int(self, authed_client):
        resp = authed_client.patch(
            "/api/weekly-focus/settings/slot-count",
            json={"slot_count": "five"},
        )
        assert resp.status_code == 422

    def test_unauthenticated_get_returns_401(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/api/weekly-focus")
        assert resp.status_code == 401


# --- AI plan_for_focus -------------------------------------------------------


class TestPlanForFocus:
    def test_no_slot_raises(self, app):
        with app.app_context(), pytest.raises(ValueError, match="no active focus slot"):
            plan_for_focus(slot_order=1)

    def test_no_api_key_raises(self, app, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with app.app_context():
            upsert_slot(slot_order=1, text="Ship auth")
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                plan_for_focus(slot_order=1)

    def test_drops_invalid_task_ids(self, app, monkeypatch):
        # Mock Claude to return one valid + one ghost task_id.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        with app.app_context():
            t = Task(
                title="Real task", type=TaskType.WORK,
                tier=Tier.THIS_WEEK, status=TaskStatus.ACTIVE,
            )
            db.session.add(t)
            db.session.commit()
            real_id = str(t.id)
            ghost_id = str(uuid.uuid4())
            upsert_slot(slot_order=1, text="Ship auth refresh")

            def fake_post(api_key, prompt, max_tokens):
                return {
                    "content": [{"text": json.dumps({
                        "changes": [
                            {"action": "promote_today",
                             "task_id": real_id,
                             "reason": "directly aligned"},
                            {"action": "promote_today",
                             "task_id": ghost_id,
                             "reason": "phantom"},
                        ]
                    })}]
                }
            monkeypatch.setattr(
                weekly_focus_service, "_post_to_claude", fake_post
            )
            result = plan_for_focus(slot_order=1)
            assert len(result["changes"]) == 1
            assert result["changes"][0]["task_id"] == real_id

    def test_create_new_task_validated_and_normalized(self, app, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        with app.app_context():
            upsert_slot(slot_order=1, text="Ship auth refresh")

            def fake_post(api_key, prompt, max_tokens):
                return {"content": [{"text": json.dumps({
                    "changes": [
                        {"action": "create_new",
                         "title": "Rotate prod SAML cert",
                         "suggested_tier": "today",
                         "type": "work",
                         "due_date": "2026-05-12",
                         "reason": "blocks ship"},
                        # Bad shape — bogus tier becomes this_week default
                        {"action": "create_new",
                         "title": "Verify OIDC clients",
                         "suggested_tier": "INVALID",
                         "type": "lol",
                         "due_date": "garbage",
                         "reason": "smoke"},
                    ]
                })}]}
            monkeypatch.setattr(
                weekly_focus_service, "_post_to_claude", fake_post
            )
            result = plan_for_focus(slot_order=1)
            assert len(result["changes"]) == 2
            ok = result["changes"][0]
            assert ok["action"] == "create_new"
            assert ok["suggested_tier"] == "today"
            assert ok["due_date"] == "2026-05-12"
            normalized = result["changes"][1]
            assert normalized["suggested_tier"] == "this_week"
            assert normalized["type"] == "work"
            assert normalized["due_date"] is None


# --- #157 next-week tab toggle -----------------------------------------------


class TestWeekOffsetNextWeek:
    """Locks #157: ?week_offset=1 reads/writes/plans the next ISO
    week's slots without disturbing the current week's data."""

    def test_get_next_week_returns_empty_when_no_rows(self, app):
        from datetime import date

        from weekly_focus_service import get_displayed_focus
        today = date(2026, 5, 13)  # Wednesday this week
        with app.app_context():
            d = get_displayed_focus(today=today, week_offset=1)
            assert d["week_start_date"] == "2026-05-18"  # next Monday
            assert d["week_offset"] == 1
            assert d["fallback_from"] is None  # no carry-forward into future
            assert d["slots"] == []

    def test_upsert_next_week_does_not_touch_this_week(self, app):
        from datetime import date

        from weekly_focus_service import get_displayed_focus, upsert_slot
        today = date(2026, 5, 13)
        with app.app_context():
            upsert_slot(slot_order=1, text="this", today=today, week_offset=0)
            upsert_slot(
                slot_order=1, text="planning ahead", today=today, week_offset=1,
            )
            this_week = get_displayed_focus(today=today, week_offset=0)
            next_week = get_displayed_focus(today=today, week_offset=1)
            assert this_week["slots"][0]["text"] == "this"
            assert next_week["slots"][0]["text"] == "planning ahead"
            assert this_week["week_start_date"] != next_week["week_start_date"]

    def test_upsert_invalid_week_offset_rejected(self, app):
        from weekly_focus_service import upsert_slot
        with app.app_context():
            with pytest.raises(ValueError, match="week_offset"):
                upsert_slot(slot_order=1, text="x", week_offset=2)
            with pytest.raises(ValueError, match="week_offset"):
                upsert_slot(slot_order=1, text="x", week_offset=-1)

    def test_clear_next_week_does_not_touch_this_week(self, app):
        from datetime import date

        from weekly_focus_service import clear_slot, get_displayed_focus, upsert_slot
        today = date(2026, 5, 13)
        with app.app_context():
            upsert_slot(slot_order=1, text="this", today=today, week_offset=0)
            upsert_slot(slot_order=1, text="next", today=today, week_offset=1)
            cleared = clear_slot(1, today=today, week_offset=1)
            assert cleared is True
            assert get_displayed_focus(today=today, week_offset=0)["slots"][0]["text"] == "this"
            assert get_displayed_focus(today=today, week_offset=1)["slots"] == []

    def test_no_carry_forward_for_next_week(self, app):
        # Even if last week had rows, a fresh next-week query returns
        # blank — the user shouldn't be tricked into thinking they
        # already planned ahead by silently seeded text.
        from datetime import date

        from weekly_focus_service import get_displayed_focus, upsert_slot
        last = date(2026, 5, 6)
        today = date(2026, 5, 13)
        with app.app_context():
            upsert_slot(slot_order=1, text="last", today=last, week_offset=0)
            d = get_displayed_focus(today=today, week_offset=1)
            assert d["slots"] == []
            assert d["fallback_from"] is None

    def test_api_get_with_week_offset_query_param(self, authed_client):
        # The endpoint reads ?week_offset=1 and forwards to the service.
        resp = authed_client.get("/api/weekly-focus?week_offset=1")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["week_offset"] == 1

    def test_api_invalid_week_offset_defaults_to_0(self, authed_client):
        # Malformed param falls back to 0 silently — the panel must
        # always render.
        resp = authed_client.get("/api/weekly-focus?week_offset=abc")
        assert resp.status_code == 200
        assert resp.get_json()["week_offset"] == 0

    def test_api_upsert_with_week_offset(self, authed_client):
        resp = authed_client.patch(
            "/api/weekly-focus/1?week_offset=1",
            json={"text": "planning ahead"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["week_offset"] == 1
        assert body["slots"][0]["text"] == "planning ahead"
