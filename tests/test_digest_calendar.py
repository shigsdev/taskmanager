"""#498: today's iCloud Calendar events lead the daily digest.

User decision 2026-10-17: a "Today's calendar" list at the TOP of the
email, before Today's tasks, in both the HTML and the plain-text part. An
iCloud failure is one line and never stops the email. Off (no ICLOUD_*)
leaves the email exactly as it was.
"""
from __future__ import annotations

from datetime import date

import pytest

import icloud_service
from models import Task, TaskType, Tier, db

DAY = date(2026, 10, 20)   # a Tuesday


def _ev(title, start, end, all_day=False, location=""):
    return {"uid": title, "title": title, "start": start, "end": end,
            "all_day": all_day, "location": location, "calendar": "Home", "color": ""}


DENTIST = _ev("Dentist <b>", "2026-10-20T09:30-04:00", "2026-10-20T10:30-04:00",
              location="12 Main St")
HOLIDAY = _ev("Team offsite", "2026-10-20", "2026-10-21", all_day=True)
CALL = _ev("Call with LA", "2026-10-20T14:00-04:00", "2026-10-20T14:30-04:00")
RED_EYE = _ev("Red-eye flight", "2026-10-19T22:00-04:00", "2026-10-20T06:30-04:00")
ENDED_AT_MIDNIGHT = _ev("Late show", "2026-10-19T21:00-04:00", "2026-10-20T00:00-04:00")


@pytest.fixture
def on(monkeypatch):
    calls = []
    monkeypatch.setattr(icloud_service, "configured", lambda: True)

    def fetch(start, end):
        calls.append((start, end))
        return [RED_EYE, ENDED_AT_MIDNIGHT, DENTIST, HOLIDAY, CALL]

    monkeypatch.setattr(icloud_service, "fetch_events", fetch)
    return calls


@pytest.fixture
def off(monkeypatch):
    monkeypatch.setattr(icloud_service, "configured", lambda: False)

    def boom(*a):
        raise AssertionError("must not read iCloud when off")

    monkeypatch.setattr(icloud_service, "fetch_events", boom)


def _task(app):
    db.session.add(Task(title="Write report", type=TaskType.WORK, tier=Tier.TODAY))
    db.session.commit()


class TestPlainText:

    def test_calendar_leads_before_todays_tasks(self, app, on):
        from digest_service import build_digest
        with app.app_context():
            _task(app)
            body = build_digest(target_date=DAY)
        assert body.index("TODAY'S CALENDAR (4)") < body.index("TODAY'S TASKS")
        assert on == [(DAY, date(2026, 10, 21))]

    def test_all_day_first_then_by_time_with_a_carried_over_event(self, app, on):
        from digest_service import build_digest
        with app.app_context():
            body = build_digest(target_date=DAY)
        block = body[body.index("TODAY'S CALENDAR"):body.index("TODAY'S TASKS")]
        lines = [ln.strip() for ln in block.splitlines()[1:] if ln.strip()]
        assert lines == [
            "All day — Team offsite",
            "until 6:30 AM — Red-eye flight",
            "9:30 AM — Dentist <b> (12 Main St)",
            "2:00 PM — Call with LA",
        ]

    def test_an_event_that_ended_at_midnight_is_not_listed(self, app, on):
        from digest_service import build_digest
        with app.app_context():
            body = build_digest(target_date=DAY)
        assert "Late show" not in body

    def test_nothing_today_says_so(self, app, monkeypatch):
        from digest_service import build_digest
        monkeypatch.setattr(icloud_service, "configured", lambda: True)
        monkeypatch.setattr(icloud_service, "fetch_events", lambda s, e: [])
        with app.app_context():
            body = build_digest(target_date=DAY)
        assert "TODAY'S CALENDAR: nothing scheduled" in body

    def test_a_failure_is_one_line_and_the_email_still_builds(self, app, monkeypatch):
        from digest_service import build_digest

        def fail(s, e):
            raise icloud_service.IcloudAuthError("iCloud refused the app-specific password.")

        monkeypatch.setattr(icloud_service, "configured", lambda: True)
        monkeypatch.setattr(icloud_service, "fetch_events", fail)
        with app.app_context():
            _task(app)
            body = build_digest(target_date=DAY)
        assert ("TODAY'S CALENDAR: couldn't read your iCloud Calendar this morning, "
                "so today's events aren't listed.") in body
        assert "Write report" in body

    def test_even_an_unexpected_error_never_stops_the_email(self, app, monkeypatch):
        from digest_service import build_digest

        def boom(s, e):
            raise RuntimeError("anything")

        monkeypatch.setattr(icloud_service, "configured", lambda: True)
        monkeypatch.setattr(icloud_service, "fetch_events", boom)
        with app.app_context():
            body = build_digest(target_date=DAY)
        assert "couldn't read your iCloud Calendar" in body
        assert "anything" not in body

    def test_off_leaves_the_email_as_it_was(self, app, off):
        from digest_service import build_digest
        with app.app_context():
            body = build_digest(target_date=DAY)
        assert "CALENDAR" not in body
        assert body.splitlines()[2].startswith("TODAY'S TASKS")


class TestHtml:

    def test_calendar_block_before_today_and_escaped(self, app, on):
        from digest_service import build_digest_html
        with app.app_context():
            html = build_digest_html(target_date=DAY)
        assert html.index("Today's calendar · 4") < html.index("Today · ")
        assert "Dentist &lt;b&gt;" in html
        assert "Dentist <b>" not in html
        assert "until 6:30 AM" in html
        assert "12 Main St" in html

    def test_failure_line_in_html(self, app, monkeypatch):
        from digest_service import build_digest_html

        def fail(s, e):
            raise icloud_service.IcloudError("down")

        monkeypatch.setattr(icloud_service, "configured", lambda: True)
        monkeypatch.setattr(icloud_service, "fetch_events", fail)
        with app.app_context():
            html = build_digest_html(target_date=DAY)
        assert "Couldn&#39;t read your iCloud Calendar this morning" in html \
            or "Couldn't read your iCloud Calendar this morning" in html

    def test_off_has_no_calendar_block(self, app, off):
        from digest_service import build_digest_html
        with app.app_context():
            html = build_digest_html(target_date=DAY)
        assert "Today's calendar" not in html
