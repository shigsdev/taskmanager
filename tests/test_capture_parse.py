"""The capture bar's payloads, round-tripped through ``POST /api/tasks``.

#506 (refreshed 2026-10-18 after the tech-debt audit flagged this file
stale): it used to hold a hand-written Python copy of ``parseCapture`` and
28 tests of that copy. The copy had drifted — it still defaulted to Inbox
(gone since #443) and had no #tomorrow / #next_week / longest-first rule /
@project hint — so those tests checked behaviour the app no longer has.
The parsing rules are tested on the real code in
``tests/js/unit/parse_capture.test.js``.

What stays here is the server half: each test posts exactly what
``static/capture.js`` ``submitCapture`` sends — ``parseCapture``'s result
as-is, so no ``tier`` key unless a hashtag or the section page set one,
plus ``_titleProvided`` / ``project_hint`` when present — and checks the
server files it as the capture bar intends. ``FULL_CAPTURE`` is pinned on
the Jest side too ("the payload pytest round-trips"), so if parseCapture's
output changes shape, one side fails.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from models import Project, ProjectType, db
from utils import local_today_date

# parseCapture("Read https://example.com #weekly #work #today @Audit"),
# with the weekday fixed (the real one uses today's).
FULL_CAPTURE = {
    "title": "Read",
    "url": "https://example.com",
    "_titleProvided": True,
    "project_hint": "Audit",
    "repeat": {"frequency": "weekly", "day_of_week": 2},
    "type": "work",
    "tier": "today",
}


def _post(client, payload):
    resp = client.post("/api/tasks", json=payload)
    return resp.status_code, resp.get_json()


class TestCaptureRoundTrip:
    def test_plain_capture_lands_in_inbox(self, authed_client):
        # No hashtag: parseCapture sets no tier (#443) and capture.js adds
        # the type from its Work / Personal select.
        status, data = _post(authed_client, {"title": "Buy milk", "type": "personal"})
        assert status == 201
        assert (data["title"], data["tier"], data["type"]) == ("Buy milk", "inbox", "personal")

    def test_section_hashtag_sets_the_section(self, authed_client):
        status, data = _post(authed_client, {"title": "Fix bug", "type": "work",
                                             "tier": "this_week"})
        assert status == 201
        assert data["tier"] == "this_week"

    def test_section_page_default_files_there(self, authed_client):
        # #443: on /tier/tomorrow capture.js fills tier from the bar's
        # data-default-tier; Tomorrow then gets tomorrow's date (#28).
        status, data = _post(authed_client, {"title": "Call Sam", "type": "work",
                                             "tier": "tomorrow"})
        assert status == 201
        assert data["tier"] == "tomorrow"
        assert data["due_date"] == (local_today_date() + timedelta(days=1)).isoformat()

    def test_url_with_title_keeps_both(self, authed_client):
        # _titleProvided rides along in the payload; the server ignores it.
        status, data = _post(authed_client, {
            "title": "Read this", "type": "work",
            "url": "https://example.com/article", "_titleProvided": True,
        })
        assert status == 201
        assert (data["title"], data["url"]) == ("Read this", "https://example.com/article")

    @pytest.mark.parametrize("repeat", [
        {"frequency": "daily"},
        {"frequency": "weekdays"},
        {"frequency": "weekly", "day_of_week": 2},
        {"frequency": "monthly_date", "day_of_month": 15},
    ])
    def test_repeat_shortcuts_make_a_template(self, authed_client, repeat):
        status, data = _post(authed_client, {"title": "Standup", "type": "work",
                                             "repeat": repeat})
        assert status == 201
        assert data["repeat"] is not None
        for key, value in repeat.items():
            assert data["repeat"][key] == value

    def test_full_capture_payload(self, authed_client, app):
        with app.app_context():
            p = Project(name="Audit", type=ProjectType.WORK)
            db.session.add(p)
            db.session.commit()
            project_id = str(p.id)
        status, data = _post(authed_client, dict(FULL_CAPTURE))
        assert status == 201
        assert (data["title"], data["tier"], data["type"], data["url"]) == (
            "Read", "today", "work", "https://example.com")
        assert data["repeat"]["frequency"] == "weekly"
        assert data["project_id"] == project_id

    def test_overlong_capture_is_refused_with_the_reason(self, authed_client):
        # #447: the capture bar shows this message and keeps the text.
        status, data = _post(authed_client, {"title": "x" * 501, "type": "work"})
        assert status == 422
        assert data["error"] == "Title is too long: 501 characters, the limit is 500."
