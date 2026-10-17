"""/api/icloud/* routes (#371): read-only iCloud Calendar events.

The service is replaced here (its own tests cover CalDAV); these pin the
route contract the /calendar page relies on: off is a plain 200 with
``enabled: false``, an iCloud failure is a 502 with a readable error (never
401/403, which the page's apiFetch would read as "sign in again"), and the
window is the same inclusive start..end, 70-day cap, as the previews.
"""
from __future__ import annotations

from datetime import date

import pytest

import icloud_service

EV = {
    "uid": "dentist-1|2026-10-20T09:30-04:00", "title": "Dentist",
    "start": "2026-10-20T09:30-04:00", "end": "2026-10-20T10:30-04:00",
    "all_day": False, "location": "12 Main St", "calendar": "Home", "color": "#1BADF8",
}


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("ICLOUD_USERNAME", "me@icloud.com")
    monkeypatch.setenv("ICLOUD_APP_PASSWORD", "abcd-efgh-ijkl-mnop")
    calls = []

    def fake_fetch(start, end):
        calls.append((start, end))
        return [EV]

    monkeypatch.setattr(icloud_service, "fetch_events", fake_fetch)
    return calls


@pytest.fixture
def off(monkeypatch):
    monkeypatch.delenv("ICLOUD_USERNAME", raising=False)
    monkeypatch.delenv("ICLOUD_APP_PASSWORD", raising=False)


URL = "/api/icloud/events?start=2026-10-19&end=2026-11-01"


class TestAuth:

    def test_events_need_a_login(self, client, on):
        assert client.get(URL).status_code in (302, 401)

    def test_refresh_needs_a_login(self, client, on):
        assert client.post("/api/icloud/refresh").status_code in (302, 401)

    def test_refresh_is_not_a_get(self, authed_client, on):
        assert authed_client.get("/api/icloud/refresh").status_code == 405


class TestEvents:

    def test_off_is_a_quiet_200(self, authed_client, off, monkeypatch):
        def boom(*a):
            raise AssertionError("must not fetch when off")
        monkeypatch.setattr(icloud_service, "fetch_events", boom)
        resp = authed_client.get(URL)
        assert resp.status_code == 200
        assert resp.get_json() == {"enabled": False, "events": []}

    def test_returns_events_and_asks_for_an_exclusive_end(self, authed_client, on):
        resp = authed_client.get(URL)
        assert resp.status_code == 200
        assert resp.get_json() == {"enabled": True, "events": [EV]}
        # end=2026-11-01 is the last day shown, so the service window ends 11-02.
        assert on == [(date(2026, 10, 19), date(2026, 11, 2))]

    @pytest.mark.parametrize("qs", [
        "", "?start=2026-10-19", "?end=2026-10-19",
        "?start=nope&end=2026-10-19", "?start=2026-10-19&end=2026-13-01",
    ])
    def test_bad_window_is_400(self, authed_client, on, qs):
        resp = authed_client.get("/api/icloud/events" + qs)
        assert resp.status_code == 400
        assert resp.get_json()["error"]
        assert on == []

    def test_end_before_start_is_400(self, authed_client, on):
        resp = authed_client.get("/api/icloud/events?start=2026-10-19&end=2026-10-18")
        assert resp.status_code == 400

    def test_more_than_70_days_is_400(self, authed_client, on):
        resp = authed_client.get("/api/icloud/events?start=2026-10-01&end=2026-12-31")
        assert resp.status_code == 400
        assert "70" in resp.get_json()["error"]

    def test_an_eight_week_grid_fits(self, authed_client, on):
        # /calendar's longest outlook: 8 weeks = 56 days.
        resp = authed_client.get("/api/icloud/events?start=2026-10-19&end=2026-12-13")
        assert resp.status_code == 200

    def test_icloud_down_is_a_502_with_a_readable_error(self, authed_client, on, monkeypatch):
        def fail(*a):
            raise icloud_service.IcloudError(
                "Couldn't read iCloud Calendar: iCloud returned HTTP 503")
        monkeypatch.setattr(icloud_service, "fetch_events", fail)
        resp = authed_client.get(URL)
        assert resp.status_code == 502
        body = resp.get_json()
        assert body["enabled"] is True
        assert "503" in body["error"]
        assert body.get("auth") is not True

    def test_a_revoked_password_is_a_502_never_401(self, authed_client, on, monkeypatch):
        def fail(*a):
            raise icloud_service.IcloudAuthError("iCloud refused the app-specific password.")
        monkeypatch.setattr(icloud_service, "fetch_events", fail)
        resp = authed_client.get(URL)
        assert resp.status_code == 502
        assert resp.get_json()["auth"] is True
        assert "app-specific password" in resp.get_json()["error"]


class TestRefresh:

    def test_refresh_forgets_the_cache(self, authed_client, on, monkeypatch):
        called = []
        monkeypatch.setattr(icloud_service, "refresh", lambda: called.append(1))
        resp = authed_client.post("/api/icloud/refresh")
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}
        assert called == [1]

    def test_refresh_when_off_is_harmless(self, authed_client, off):
        resp = authed_client.post("/api/icloud/refresh")
        assert resp.status_code == 200
