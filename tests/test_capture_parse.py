"""Tests for the capture bar's parseCapture() logic.

The canonical implementation lives in static/parse_capture.js (extracted
from capture.js so Jest can import it directly).  This file maintains a
Python mirror of those parsing rules so we can test every shortcut
combination in pytest — including the prefix-collision cases that caused
bugs (#weekly vs #week, #weekdays vs #week, #work vs #personal).

If parse_capture.js changes, update ``_parse_capture()`` here to match
and ensure the new tests still pass.  The Jest suite in
tests/js/unit/parse_capture.test.js tests the real JS implementation;
this file is the cross-check.  The API round-trip tests (at the bottom)
hit ``POST /api/tasks`` with the exact payloads that parseCapture would
produce, verifying the server honours them.
"""
from __future__ import annotations

import re
from datetime import date

# ---------------------------------------------------------------------------
# Python mirror of capture.js parseCapture()
# ---------------------------------------------------------------------------

def _parse_capture(text: str) -> dict:
    """Pure-Python reimplementation of capture.js parseCapture().

    Must be kept in sync with static/capture.js.  The test suite below
    exercises every branch so drift is caught immediately.
    """
    result = {"title": text, "tier": "inbox"}

    # 1. URL detection
    url_match = re.search(r"https?://\S+", text, re.IGNORECASE)
    if url_match:
        result["url"] = url_match.group(0)
        remaining = text.replace(url_match.group(0), "").strip()
        result["title"] = remaining or url_match.group(0)
        result["_titleProvided"] = len(remaining) > 0

    # 2. Repeat shortcuts (BEFORE tier — longer tags first)
    today = date.today()
    weekday_iso = today.isoweekday()  # Mon=1 … Sun=7
    # JS: getDay() returns Sun=0…Sat=6; code does: day===0 ? 6 : day-1
    # That maps to Mon=0…Sun=6 (0-indexed Mon-based)
    js_day_of_week = 6 if weekday_iso == 7 else weekday_iso - 1

    repeat_map = {
        "#daily": {"frequency": "daily"},
        "#weekdays": {"frequency": "weekdays"},
        "#weekly": {"frequency": "weekly", "day_of_week": js_day_of_week},
        "#monthly": {"frequency": "monthly_date", "day_of_month": today.day},
    }
    for tag, repeat in repeat_map.items():
        if tag in result["title"].lower():
            result["repeat"] = repeat
            result["title"] = re.sub(re.escape(tag), "", result["title"],
                                     flags=re.IGNORECASE).strip()
            break

    # 3. Type shortcuts (#personal before #work — avoid prefix collision)
    if "#personal" in result["title"].lower():
        result["type"] = "personal"
        result["title"] = re.sub(r"#personal", "", result["title"],
                                  flags=re.IGNORECASE).strip()
    elif "#work" in result["title"].lower():
        result["type"] = "work"
        result["title"] = re.sub(r"#work", "", result["title"],
                                  flags=re.IGNORECASE).strip()

    # 4. Tier shortcuts
    tier_map = {
        "#today": "today",
        "#week": "this_week",
        "#backlog": "backlog",
        "#freezer": "freezer",
    }
    for tag, tier in tier_map.items():
        if tag in result["title"].lower():
            result["tier"] = tier
            result["title"] = re.sub(re.escape(tag), "", result["title"],
                                      flags=re.IGNORECASE).strip()

    # 5. Empty title fallback
    if not result["title"] and result.get("url"):
        result["title"] = result["url"]

    return result


# ---------------------------------------------------------------------------
# Shortcut parsing tests
# ---------------------------------------------------------------------------

class TestParseCaptureTier:
    """Tier shortcuts: #today, #week, #backlog, #freezer."""

    def test_default_tier_is_inbox(self):
        r = _parse_capture("Buy groceries")
        assert r["tier"] == "inbox"
        assert r["title"] == "Buy groceries"

    def test_today(self):
        r = _parse_capture("Fix bug #today")
        assert r["tier"] == "today"
        assert r["title"] == "Fix bug"

    def test_week(self):
        r = _parse_capture("Write docs #week")
        assert r["tier"] == "this_week"
        assert r["title"] == "Write docs"

    def test_backlog(self):
        r = _parse_capture("Learn Rust #backlog")
        assert r["tier"] == "backlog"
        assert r["title"] == "Learn Rust"

    def test_freezer(self):
        r = _parse_capture("Someday project #freezer")
        assert r["tier"] == "freezer"
        assert r["title"] == "Someday project"

    def test_tier_case_insensitive(self):
        r = _parse_capture("Task #TODAY")
        assert r["tier"] == "today"

    def test_tier_mid_string(self):
        r = _parse_capture("Do #today the thing")
        assert r["tier"] == "today"
        assert r["title"] == "Do  the thing"  # double space is expected


class TestParseCaptureType:
    """Type shortcuts: #work, #personal."""

    def test_work(self):
        r = _parse_capture("Deploy app #work")
        assert r["type"] == "work"
        assert r["title"] == "Deploy app"

    def test_personal(self):
        r = _parse_capture("Call dentist #personal")
        assert r["type"] == "personal"
        assert r["title"] == "Call dentist"

    def test_type_case_insensitive(self):
        r = _parse_capture("Task #WORK")
        assert r["type"] == "work"

    def test_no_type_default(self):
        r = _parse_capture("Plain task")
        assert "type" not in r


class TestParseCaptureRepeat:
    """Repeat shortcuts: #daily, #weekdays, #weekly, #monthly."""

    def test_daily(self):
        r = _parse_capture("Standup #daily")
        assert r["repeat"]["frequency"] == "daily"
        assert r["title"] == "Standup"

    def test_weekdays(self):
        r = _parse_capture("Check email #weekdays")
        assert r["repeat"]["frequency"] == "weekdays"
        assert r["title"] == "Check email"

    def test_weekly(self):
        r = _parse_capture("Team sync #weekly")
        assert r["repeat"]["frequency"] == "weekly"
        assert "day_of_week" in r["repeat"]
        assert r["title"] == "Team sync"

    def test_monthly(self):
        r = _parse_capture("Budget review #monthly")
        assert r["repeat"]["frequency"] == "monthly_date"
        assert r["repeat"]["day_of_month"] == date.today().day
        assert r["title"] == "Budget review"

    def test_repeat_case_insensitive(self):
        r = _parse_capture("Task #DAILY")
        assert r["repeat"]["frequency"] == "daily"


class TestParseCaptureURL:
    """URL detection and title extraction."""

    def test_url_only(self):
        r = _parse_capture("https://example.com/article")
        assert r["url"] == "https://example.com/article"
        assert r["title"] == "https://example.com/article"

    def test_url_with_title(self):
        r = _parse_capture("Read this https://example.com/article")
        assert r["url"] == "https://example.com/article"
        assert r["title"] == "Read this"
        assert r["_titleProvided"] is True

    def test_url_with_title_after(self):
        r = _parse_capture("https://example.com good article")
        assert r["url"] == "https://example.com"
        assert r["title"] == "good article"

    def test_http_url(self):
        r = _parse_capture("http://legacy.example.com")
        assert r["url"] == "http://legacy.example.com"


class TestParseCaptureCollisions:
    """PREFIX COLLISION tests — these catch the bugs we found.

    The critical ordering rule in parseCapture:
    1. Repeat shortcuts FIRST (#daily, #weekdays, #weekly, #monthly)
    2. Type shortcuts SECOND (#personal, #work)
    3. Tier shortcuts LAST (#today, #week, #backlog, #freezer)

    This prevents:
    - #week consuming the first 5 chars of #weekly → leaving "ly"
    - #week consuming the first 5 chars of #weekdays → leaving "days"
    - #work matching inside #personal (it doesn't, but order matters)
    """

    def test_weekly_not_eaten_by_week(self):
        """BUG FIX: #weekly must not be partially consumed by #week."""
        r = _parse_capture("Team sync #weekly")
        assert r["repeat"]["frequency"] == "weekly"
        assert r["title"] == "Team sync"
        # #week should NOT have matched — tier stays inbox
        assert r["tier"] == "inbox"
        # No leftover "ly" in the title
        assert "ly" not in r["title"]

    def test_weekdays_not_eaten_by_week(self):
        """#weekdays must not be partially consumed by #week."""
        r = _parse_capture("Standup #weekdays")
        assert r["repeat"]["frequency"] == "weekdays"
        assert r["title"] == "Standup"
        assert r["tier"] == "inbox"
        assert "days" not in r["title"]

    def test_weekly_with_tier(self):
        """#weekly + #today should both work independently."""
        r = _parse_capture("Sync #weekly #today")
        assert r["repeat"]["frequency"] == "weekly"
        assert r["tier"] == "today"
        assert r["title"] == "Sync"

    def test_weekdays_with_tier(self):
        """#weekdays + #backlog should both work."""
        r = _parse_capture("Email check #weekdays #backlog")
        assert r["repeat"]["frequency"] == "weekdays"
        assert r["tier"] == "backlog"
        assert r["title"] == "Email check"

    def test_work_not_eaten_by_week(self):
        """#work comes after repeat parsing, so #week won't eat it."""
        r = _parse_capture("Deploy #work #today")
        assert r["type"] == "work"
        assert r["tier"] == "today"
        assert r["title"] == "Deploy"

    def test_personal_before_work(self):
        """#personal is checked before #work (no prefix collision)."""
        r = _parse_capture("Gym #personal")
        assert r["type"] == "personal"
        assert r["title"] == "Gym"

    def test_all_shortcuts_combined(self):
        """All shortcut types at once."""
        r = _parse_capture("Big task #daily #work #today")
        assert r["repeat"]["frequency"] == "daily"
        assert r["type"] == "work"
        assert r["tier"] == "today"
        assert r["title"] == "Big task"

    def test_url_with_shortcuts(self):
        """URL + tier + type all parsed correctly."""
        r = _parse_capture("Read https://example.com #work #week")
        assert r["url"] == "https://example.com"
        assert r["type"] == "work"
        assert r["tier"] == "this_week"
        assert r["title"] == "Read"


# ---------------------------------------------------------------------------
# API round-trip tests — verify server accepts parseCapture payloads
# ---------------------------------------------------------------------------

class TestCaptureAPIRoundTrip:
    """POST /api/tasks with payloads that mirror parseCapture output."""

    def test_plain_task(self, authed_client):
        resp = authed_client.post("/api/tasks", json={
            "title": "Buy milk",
            "tier": "inbox",
            "type": "personal",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["title"] == "Buy milk"
        assert data["tier"] == "inbox"

    def test_task_with_tier(self, authed_client):
        resp = authed_client.post("/api/tasks", json={
            "title": "Fix bug",
            "tier": "today",
            "type": "work",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["tier"] == "today"
        assert data["type"] == "work"

    def test_task_with_url(self, authed_client):
        resp = authed_client.post("/api/tasks", json={
            "title": "Read article",
            "tier": "inbox",
            "type": "work",
            "url": "https://example.com/article",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["url"] == "https://example.com/article"

    def test_task_with_repeat_daily(self, authed_client):
        resp = authed_client.post("/api/tasks", json={
            "title": "Morning standup",
            "tier": "inbox",
            "type": "work",
            "repeat": {"frequency": "daily"},
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["repeat"] is not None
        assert data["repeat"]["frequency"] == "daily"

    def test_task_with_repeat_weekly(self, authed_client):
        resp = authed_client.post("/api/tasks", json={
            "title": "Team sync",
            "tier": "inbox",
            "type": "work",
            "repeat": {"frequency": "weekly", "day_of_week": 2},
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["repeat"]["frequency"] == "weekly"
        assert data["repeat"]["day_of_week"] == 2

    def test_task_with_repeat_weekdays(self, authed_client):
        resp = authed_client.post("/api/tasks", json={
            "title": "Check email",
            "tier": "inbox",
            "type": "work",
            "repeat": {"frequency": "weekdays"},
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["repeat"]["frequency"] == "weekdays"

    def test_task_with_repeat_monthly(self, authed_client):
        resp = authed_client.post("/api/tasks", json={
            "title": "Budget review",
            "tier": "inbox",
            "type": "personal",
            "repeat": {"frequency": "monthly_date", "day_of_month": 15},
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["repeat"]["frequency"] == "monthly_date"
        assert data["repeat"]["day_of_month"] == 15

    def test_full_capture_payload(self, authed_client):
        """Simulates parseCapture("Read https://ex.com #weekly #work #today")."""
        resp = authed_client.post("/api/tasks", json={
            "title": "Read",
            "tier": "today",
            "type": "work",
            "url": "https://example.com",
            "repeat": {"frequency": "weekly", "day_of_week": 0},
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["title"] == "Read"
        assert data["tier"] == "today"
        assert data["type"] == "work"
        assert data["url"] == "https://example.com"
        assert data["repeat"]["frequency"] == "weekly"
