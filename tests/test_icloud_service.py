"""icloud_service -- read-only iCloud Calendar events over CalDAV (#371).

The XML below is shaped like iCloud's real answers: an un-prefixed DAV:
default namespace, a calendar-home-set on a per-account partition host
with an explicit :443, a Reminders list that holds VTODO only, and an
inbox collection. Nothing here talks to Apple: every request goes through
egress.safe_call_dav, which these tests replace.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import egress
import icloud_service as svc

PRINCIPAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:">
 <response>
  <href>/</href>
  <propstat>
   <prop><current-user-principal><href>/123456789/principal/</href></current-user-principal></prop>
   <status>HTTP/1.1 200 OK</status>
  </propstat>
 </response>
</multistatus>"""

HOME_XML = """<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:">
 <response>
  <href>/123456789/principal/</href>
  <propstat>
   <prop>
    <calendar-home-set xmlns="urn:ietf:params:xml:ns:caldav">
     <href xmlns="DAV:">https://p42-caldav.icloud.com:443/123456789/calendars/</href>
    </calendar-home-set>
   </prop>
   <status>HTTP/1.1 200 OK</status>
  </propstat>
 </response>
</multistatus>"""

CALENDARS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav" xmlns:A="http://apple.com/ns/ical/">
 <response>
  <href>/123456789/calendars/</href>
  <propstat><prop><resourcetype><collection/></resourcetype></prop>
   <status>HTTP/1.1 200 OK</status></propstat>
 </response>
 <response>
  <href>/123456789/calendars/home/</href>
  <propstat><prop>
   <displayname>Home</displayname>
   <resourcetype><collection/><C:calendar/></resourcetype>
   <C:supported-calendar-component-set><C:comp name="VEVENT"/></C:supported-calendar-component-set>
   <A:calendar-color>#1BADF8FF</A:calendar-color>
  </prop><status>HTTP/1.1 200 OK</status></propstat>
 </response>
 <response>
  <href>/123456789/calendars/tasks/</href>
  <propstat><prop>
   <displayname>Reminders</displayname>
   <resourcetype><collection/><C:calendar/></resourcetype>
   <C:supported-calendar-component-set><C:comp name="VTODO"/></C:supported-calendar-component-set>
  </prop><status>HTTP/1.1 200 OK</status></propstat>
 </response>
 <response>
  <href>/123456789/calendars/inbox/</href>
  <propstat><prop>
   <resourcetype><collection/><C:schedule-inbox/></resourcetype>
  </prop><status>HTTP/1.1 200 OK</status></propstat>
 </response>
 <response>
  <href>/123456789/calendars/work/</href>
  <propstat><prop>
   <displayname>Work</displayname>
   <resourcetype><collection/><C:calendar/></resourcetype>
   <C:supported-calendar-component-set>
    <C:comp name="VEVENT"/><C:comp name="VTODO"/>
   </C:supported-calendar-component-set>
   <A:calendar-color>javascript:alert(1)</A:calendar-color>
  </prop><status>HTTP/1.1 200 OK</status></propstat>
 </response>
</multistatus>"""

VTZ_NY = """BEGIN:VTIMEZONE
TZID:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
DTSTART:20070311T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
TZNAME:EDT
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
DTSTART:20071104T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
TZNAME:EST
END:STANDARD
END:VTIMEZONE"""


def _ics(*events: str, tz: str = VTZ_NY) -> str:
    body = "\n".join(events)
    return (
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Apple Inc.//iCloud//EN\n"
        f"{tz}\n{body}\nEND:VCALENDAR\n"
    ).replace("\n", "\r\n")


DENTIST = """BEGIN:VEVENT
UID:dentist-1
DTSTAMP:20261001T120000Z
DTSTART;TZID=America/New_York:20261020T093000
DTEND;TZID=America/New_York:20261020T103000
SUMMARY:Dentist
LOCATION:12 Main St
END:VEVENT"""

# Written in Los Angeles time; shown in the app's zone (New York).
LA_CALL = """BEGIN:VEVENT
UID:la-call
DTSTAMP:20261001T120000Z
DTSTART;TZID=America/Los_Angeles:20261021T090000
DTEND;TZID=America/Los_Angeles:20261021T093000
SUMMARY:Call with LA
END:VEVENT"""

TRIP = """BEGIN:VEVENT
UID:trip
DTSTAMP:20261001T120000Z
DTSTART;VALUE=DATE:20261022
DTEND;VALUE=DATE:20261024
SUMMARY:Trip
END:VEVENT"""

WEEKLY = """BEGIN:VEVENT
UID:standup
DTSTAMP:20261001T120000Z
DTSTART;TZID=America/New_York:20261005T090000
DTEND;TZID=America/New_York:20261005T091500
RRULE:FREQ=WEEKLY;COUNT=10
EXDATE;TZID=America/New_York:20261026T090000
SUMMARY:Standup
END:VEVENT"""

UTC_EVENT = """BEGIN:VEVENT
UID:utc-one
DTSTAMP:20261001T120000Z
DTSTART:20261023T170000Z
DTEND:20261023T180000Z
SUMMARY:UTC meeting
END:VEVENT"""

FLOATING = """BEGIN:VEVENT
UID:floating
DTSTAMP:20261001T120000Z
DTSTART:20261024T080000
DTEND:20261024T083000
END:VEVENT"""

OUTSIDE = """BEGIN:VEVENT
UID:outside
DTSTAMP:20261001T120000Z
DTSTART;TZID=America/New_York:20261201T093000
DTEND;TZID=America/New_York:20261201T103000
SUMMARY:Far away
END:VEVENT"""


def _report_xml(*ics_texts: str) -> str:
    parts = "".join(
        f"<response><href>/123456789/calendars/home/e{i}.ics</href>"
        "<propstat><prop><getetag>\"1\"</getetag>"
        f"<C:calendar-data>{t.replace('&', '&amp;').replace('<', '&lt;')}</C:calendar-data>"
        "</prop><status>HTTP/1.1 200 OK</status></propstat></response>"
        for i, t in enumerate(ics_texts)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
        f"{parts}</multistatus>"
    )


HOME_CAL = {"name": "Home", "color": "#1BADF8"}
WINDOW = (date(2026, 10, 19), date(2026, 11, 2))


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("DIGEST_TZ", "America/New_York")
    monkeypatch.setenv("ICLOUD_USERNAME", "me@icloud.com")
    monkeypatch.setenv("ICLOUD_APP_PASSWORD", "abcd-efgh-ijkl-mnop")
    svc.refresh()
    svc._last.update(ok=None, at=None, error=None)
    yield
    svc.refresh()
    svc._last.update(ok=None, at=None, error=None)


class _FakeDav:
    """Stands in for egress.safe_call_dav; answers by (method, url)."""

    def __init__(self, reports=None, fail=None):
        self.calls: list[tuple[str, str, dict, str]] = []
        self.reports = reports or {}
        self.fail = fail

    def __call__(self, *, method, url, headers, body, vendor, host_allowed, **_):
        self.calls.append((method, url, headers, body))
        assert vendor == "iCloud"
        assert host_allowed is svc.host_allowed
        if self.fail is not None:
            raise self.fail
        if method == "PROPFIND" and url == "https://caldav.icloud.com/":
            return PRINCIPAL_XML
        if method == "PROPFIND" and url == "https://caldav.icloud.com/123456789/principal/":
            return HOME_XML
        if method == "PROPFIND" and url == "https://p42-caldav.icloud.com:443/123456789/calendars/":
            return CALENDARS_XML
        if method == "REPORT":
            return self.reports.get(url, _report_xml())
        raise AssertionError(f"unexpected {method} {url}")


# --- configuration + host allowlist ----------------------------------------


class TestConfigured:

    def test_both_vars_set(self):
        assert svc.configured() is True

    @pytest.mark.parametrize("missing", ["ICLOUD_USERNAME", "ICLOUD_APP_PASSWORD"])
    def test_either_missing_is_off(self, monkeypatch, missing):
        monkeypatch.delenv(missing)
        assert svc.configured() is False

    def test_unconfigured_fetch_returns_nothing_and_calls_no_one(self, monkeypatch):
        monkeypatch.delenv("ICLOUD_APP_PASSWORD")
        fake = _FakeDav()
        monkeypatch.setattr(egress, "safe_call_dav", fake)
        assert svc.fetch_events(*WINDOW) == []
        assert fake.calls == []


class TestHostAllowed:

    @pytest.mark.parametrize("host", [
        "caldav.icloud.com", "p42-caldav.icloud.com", "p1-caldav.icloud.com",
    ])
    def test_icloud_caldav_hosts(self, host):
        assert svc.host_allowed(host)

    @pytest.mark.parametrize("host", [
        "", "icloud.com", "www.icloud.com", "caldav.icloud.com.evil.com",
        "evil.com", "p42-caldav.icloud.co", "pX-caldav.icloud.com", "contacts.icloud.com",
    ])
    def test_everything_else(self, host):
        assert not svc.host_allowed(host)


# --- XML parsing --------------------------------------------------------------


class TestParse:

    def test_principal(self):
        assert svc.parse_principal(PRINCIPAL_XML) == "/123456789/principal/"

    def test_home_on_the_partition_host(self):
        assert svc.parse_home(HOME_XML) == "https://p42-caldav.icloud.com:443/123456789/calendars/"

    def test_calendars_keep_event_calendars_only(self):
        cals = svc.parse_calendars(CALENDARS_XML)
        assert [c["name"] for c in cals] == ["Home", "Work"]
        assert cals[0]["href"] == "/123456789/calendars/home/"

    def test_color_is_kept_only_when_it_is_a_hex_color(self):
        cals = {c["name"]: c for c in svc.parse_calendars(CALENDARS_XML)}
        assert cals["Home"]["color"] == "#1BADF8"
        assert cals["Work"]["color"] == ""

    def test_unreadable_xml_is_an_icloud_error(self):
        with pytest.raises(svc.IcloudError):
            svc.parse_principal("<not xml")

    def test_entity_expansion_is_refused(self):
        bomb = (
            '<?xml version="1.0"?><!DOCTYPE m [<!ENTITY a "aaaaaaaaaa">'
            '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
            '<multistatus xmlns="DAV:"><response><href>&b;</href></response></multistatus>'
        )
        with pytest.raises(svc.IcloudError):
            svc.parse_calendars(bomb)

    def test_calendar_data_from_a_report(self):
        texts = svc.parse_calendar_data(_report_xml(_ics(DENTIST)))
        assert len(texts) == 1
        assert "SUMMARY:Dentist" in texts[0]

    def test_report_body_has_the_utc_window(self):
        body = svc.report_body(date(2026, 10, 19), date(2026, 11, 2))
        assert 'start="20261019T000000Z"' in body
        assert 'end="20261102T000000Z"' in body
        assert 'name="VEVENT"' in body


# --- event normalisation -----------------------------------------------------


def _events(*ics_events, window=WINDOW):
    return svc.events_from_ics([_ics(*ics_events)], HOME_CAL, *window)


class TestEventsFromIcs:

    def test_timed_event(self):
        [ev] = _events(DENTIST)
        assert ev["title"] == "Dentist"
        assert ev["start"] == "2026-10-20T09:30-04:00"
        assert ev["end"] == "2026-10-20T10:30-04:00"
        assert ev["all_day"] is False
        assert ev["location"] == "12 Main St"
        assert ev["calendar"] == "Home"
        assert ev["color"] == "#1BADF8"

    def test_another_zone_is_shown_in_the_app_zone(self):
        [ev] = _events(LA_CALL)
        assert ev["start"] == "2026-10-21T12:00-04:00"

    def test_utc_is_shown_in_the_app_zone(self):
        [ev] = _events(UTC_EVENT)
        assert ev["start"] == "2026-10-23T13:00-04:00"

    def test_floating_time_is_the_app_zone_and_a_missing_title_says_so(self):
        [ev] = _events(FLOATING)
        assert ev["start"] == "2026-10-24T08:00-04:00"
        assert ev["title"] == "(no title)"

    def test_all_day_spanning_two_days_keeps_its_exclusive_end(self):
        [ev] = _events(TRIP)
        assert ev["all_day"] is True
        assert ev["start"] == "2026-10-22"
        assert ev["end"] == "2026-10-24"

    def test_weekly_repeat_is_expanded_and_the_exdate_skipped(self):
        evs = _events(WEEKLY)
        # 10-26 is the EXDATE; 11-02 is the window's exclusive end.
        assert [e["start"] for e in evs] == ["2026-10-19T09:00-04:00"]

    def test_repeat_across_the_dst_change_keeps_wall_clock_time(self):
        evs = _events(WEEKLY, window=(date(2026, 10, 19), date(2026, 11, 10)))
        assert [e["start"] for e in evs] == ["2026-10-19T09:00-04:00", "2026-11-02T09:00-05:00",
                                             "2026-11-09T09:00-05:00"]
        assert len({e["uid"] for e in evs}) == 3

    def test_an_event_outside_the_window_is_dropped(self):
        assert _events(OUTSIDE) == []

    def test_one_broken_calendar_object_does_not_hide_the_rest(self):
        evs = svc.events_from_ics(["BEGIN:VCALENDAR\r\nnonsense", _ics(DENTIST)], HOME_CAL, *WINDOW)
        assert [e["title"] for e in evs] == ["Dentist"]

    def test_sorted_by_start(self):
        evs = _events(TRIP, LA_CALL, DENTIST)
        assert [e["title"] for e in evs] == ["Dentist", "Call with LA", "Trip"]

    def test_long_text_is_capped(self):
        long = DENTIST.replace("SUMMARY:Dentist", "SUMMARY:" + "x" * 1000)
        [ev] = _events(long)
        assert len(ev["title"]) == 300


# --- fetch + cache -----------------------------------------------------------


HOME_URL = "https://p42-caldav.icloud.com:443/123456789/calendars/home/"
WORK_URL = "https://p42-caldav.icloud.com:443/123456789/calendars/work/"


class TestFetchEvents:

    def test_discovers_then_reads_every_event_calendar(self, monkeypatch):
        fake = _FakeDav(reports={
            HOME_URL: _report_xml(_ics(DENTIST)),
            WORK_URL: _report_xml(_ics(LA_CALL)),
        })
        monkeypatch.setattr(egress, "safe_call_dav", fake)
        evs = svc.fetch_events(*WINDOW)
        assert [(e["title"], e["calendar"]) for e in evs] == [
            ("Dentist", "Home"), ("Call with LA", "Work"),
        ]
        methods = [c[0] for c in fake.calls]
        assert methods == ["PROPFIND", "PROPFIND", "PROPFIND", "REPORT", "REPORT"]
        reported = [c[1] for c in fake.calls if c[0] == "REPORT"]
        assert reported == [HOME_URL, WORK_URL]

    def test_only_read_methods_and_basic_auth(self, monkeypatch):
        fake = _FakeDav()
        monkeypatch.setattr(egress, "safe_call_dav", fake)
        svc.fetch_events(*WINDOW)
        for method, _url, headers, _body in fake.calls:
            assert method in ("PROPFIND", "REPORT")
            assert headers["Authorization"].startswith("Basic ")
        depths = [c[2]["Depth"] for c in fake.calls]
        assert depths == ["0", "0", "1", "1", "1"]

    def test_second_read_of_the_same_window_is_cached(self, monkeypatch):
        fake = _FakeDav(reports={HOME_URL: _report_xml(_ics(DENTIST))})
        monkeypatch.setattr(egress, "safe_call_dav", fake)
        first = svc.fetch_events(*WINDOW)
        n = len(fake.calls)
        assert svc.fetch_events(*WINDOW) == first
        assert len(fake.calls) == n

    def test_cache_expires_after_the_ttl(self, monkeypatch):
        fake = _FakeDav()
        monkeypatch.setattr(egress, "safe_call_dav", fake)
        clock = [1000.0]
        monkeypatch.setattr(svc.time, "monotonic", lambda: clock[0])
        svc.fetch_events(*WINDOW)
        n = len(fake.calls)
        clock[0] += svc.CACHE_TTL_SEC + 1
        svc.fetch_events(*WINDOW)
        # Calendars are still known (1h), so only the REPORTs repeat.
        assert [c[0] for c in fake.calls[n:]] == ["REPORT", "REPORT"]

    def test_refresh_forgets_events_and_calendars(self, monkeypatch):
        fake = _FakeDav()
        monkeypatch.setattr(egress, "safe_call_dav", fake)
        svc.fetch_events(*WINDOW)
        n = len(fake.calls)
        svc.refresh()
        svc.fetch_events(*WINDOW)
        assert [c[0] for c in fake.calls[n:]] == [
            "PROPFIND", "PROPFIND", "PROPFIND", "REPORT", "REPORT",
        ]

    def test_the_cache_does_not_grow_without_bound(self, monkeypatch):
        monkeypatch.setattr(egress, "safe_call_dav", _FakeDav())
        for i in range(svc.MAX_CACHED_WINDOWS + 10):
            day = date(2026, 1, 1) + timedelta(days=i)
            svc.fetch_events(day, day + timedelta(days=1))
        assert len(svc._events_cache) <= svc.MAX_CACHED_WINDOWS

    def test_401_is_an_auth_error_that_says_what_to_do(self, monkeypatch):
        refused = egress.EgressError("iCloud returned HTTP 401", status=401)
        monkeypatch.setattr(egress, "safe_call_dav", _FakeDav(fail=refused))
        with pytest.raises(svc.IcloudAuthError) as ei:
            svc.fetch_events(*WINDOW)
        assert "app-specific password" in str(ei.value)
        assert "abcd-efgh-ijkl-mnop" not in str(ei.value)
        assert svc.last_status()["ok"] is False
        assert svc.last_status()["error"] == "auth"

    def test_a_server_error_is_an_icloud_error(self, monkeypatch):
        down = egress.EgressError("iCloud returned HTTP 503", status=503)
        monkeypatch.setattr(egress, "safe_call_dav", _FakeDav(fail=down))
        with pytest.raises(svc.IcloudError) as ei:
            svc.fetch_events(*WINDOW)
        assert not isinstance(ei.value, svc.IcloudAuthError)
        assert "503" in str(ei.value)
        assert svc.last_status()["error"] == "fetch"

    def test_a_failure_is_not_cached(self, monkeypatch):
        down = egress.EgressError("x", status=503)
        monkeypatch.setattr(egress, "safe_call_dav", _FakeDav(fail=down))
        with pytest.raises(svc.IcloudError):
            svc.fetch_events(*WINDOW)
        fake = _FakeDav()
        monkeypatch.setattr(egress, "safe_call_dav", fake)
        assert svc.fetch_events(*WINDOW) == []
        assert fake.calls
        assert svc.last_status()["ok"] is True

    def test_no_principal_is_a_readable_error(self, monkeypatch):
        def dav(**kw):
            return '<multistatus xmlns="DAV:"></multistatus>'
        monkeypatch.setattr(egress, "safe_call_dav", dav)
        with pytest.raises(svc.IcloudError, match="where your calendars are"):
            svc.fetch_events(*WINDOW)

    def test_last_status_starts_unknown(self):
        assert svc.last_status() == {"ok": None, "at": None, "error": None}
