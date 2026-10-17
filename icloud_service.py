"""Read-only iCloud Calendar events over CalDAV (#371).

The user's Apple ID and an Apple *app-specific* password come from the
environment (``ICLOUD_USERNAME`` / ``ICLOUD_APP_PASSWORD``). Both unset means
the feature is off: :func:`configured` is False and nothing calls Apple.

What this module does, and no more:

- discovers the user's calendars (PROPFIND, read-only), and
- reads the events in a date window (REPORT calendar-query), expands
  repeating events itself (``recurring-ical-events``) and returns plain dicts.

It never writes to iCloud (no PUT / DELETE / PROPPATCH) and never stores
anything in the database: events live in a 15-minute in-memory cache
(user decision 2026-10-17). Each Gunicorn worker keeps its own cache, which
at one user just means an occasional extra read. Every request goes through
:func:`egress.safe_call_dav`, which refuses any method but PROPFIND / REPORT,
any host but iCloud's CalDAV hosts, plain http, and redirects (ADR-041).

The password also opens the user's iCloud Mail and Contacts, so it is never
logged, never put in an error message and never sent anywhere but
``*.icloud.com`` over https. Spec: docs/design/371-icloud-calendar-pull.md.
"""
from __future__ import annotations

import base64
import os
import re
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events
from defusedxml import DefusedXmlException, ElementTree

import egress

VENDOR = "iCloud"
ROOT_URL = "https://caldav.icloud.com/"
CACHE_TTL_SEC = 15 * 60
DISCOVERY_TTL_SEC = 60 * 60
MAX_WINDOW_DAYS = 70          # same cap as /api/recurring/previews
MAX_CACHED_WINDOWS = 16       # /calendar asks for 1-3 windows; this is slack
TIMEOUT_SEC = 10.0            # per request; a fetch is 1-2 + one per calendar

# caldav.icloud.com, or the per-account partition host the server hands
# back (p22-caldav.icloud.com). Nothing else.
_HOST_RE = re.compile(r"^(?:caldav|p\d{1,4}-caldav)\.icloud\.com$")
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}")

_NS = {
    "d": "DAV:",
    "c": "urn:ietf:params:xml:ns:caldav",
    "a": "http://apple.com/ns/ical/",
}

_PRINCIPAL_BODY = (
    '<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/>'
    "</d:prop></d:propfind>"
)
_HOME_BODY = (
    '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    "<d:prop><c:calendar-home-set/></d:prop></d:propfind>"
)
_CALENDARS_BODY = (
    '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" '
    'xmlns:a="http://apple.com/ns/ical/"><d:prop><d:displayname/>'
    "<d:resourcetype/><c:supported-calendar-component-set/>"
    "<a:calendar-color/></d:prop></d:propfind>"
)


class IcloudError(RuntimeError):
    """A failure the user can read. Never holds the password or a URL."""


class IcloudAuthError(IcloudError):
    """iCloud refused the credentials (401 / 403)."""


def configured() -> bool:
    return bool(os.environ.get("ICLOUD_USERNAME") and os.environ.get("ICLOUD_APP_PASSWORD"))


def host_allowed(host: str) -> bool:
    return bool(_HOST_RE.match(host or ""))


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(os.environ.get("DIGEST_TZ") or "America/New_York")
    except Exception:  # noqa: BLE001 -- a bad TZ name falls back, like the digest
        return ZoneInfo("America/New_York")


def _auth_headers(depth: str) -> dict[str, str]:
    raw = f"{os.environ.get('ICLOUD_USERNAME', '')}:{os.environ.get('ICLOUD_APP_PASSWORD', '')}"
    token = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return {
        "Authorization": "Basic " + token,
        "Depth": depth,
        "Content-Type": "application/xml; charset=utf-8",
    }


def _dav(method: str, url: str, body: str, depth: str) -> str:
    try:
        return egress.safe_call_dav(
            method=method, url=url, headers=_auth_headers(depth), body=body,
            vendor=VENDOR, host_allowed=host_allowed, timeout_sec=TIMEOUT_SEC,
        )
    except egress.EgressError as e:
        if e.status in (401, 403):
            raise IcloudAuthError(
                "iCloud refused the app-specific password. It may have been "
                "revoked (changing your Apple password revokes them all): make a "
                "new one at account.apple.com and update ICLOUD_APP_PASSWORD."
            ) from e
        raise IcloudError(f"Couldn't read iCloud Calendar: {e}") from e


def _responses(xml_text: str) -> list[Any]:
    try:
        root = ElementTree.fromstring(xml_text)
    except (ElementTree.ParseError, DefusedXmlException) as e:
        raise IcloudError("iCloud sent an answer that couldn't be read.") from e
    return root.findall("d:response", _NS)


def _text(el: Any) -> str:
    return el.text.strip() if el is not None and el.text else ""


def parse_principal(xml_text: str) -> str | None:
    for r in _responses(xml_text):
        h = _text(r.find(".//d:current-user-principal/d:href", _NS))
        if h:
            return h
    return None


def parse_home(xml_text: str) -> str | None:
    for r in _responses(xml_text):
        h = _text(r.find(".//c:calendar-home-set/d:href", _NS))
        if h:
            return h
    return None


def parse_calendars(xml_text: str) -> list[dict[str, str]]:
    """Event calendars only: resourcetype has <c:calendar/> and the component
    set (when listed) includes VEVENT. Reminders lists and the inbox drop out."""
    out = []
    for r in _responses(xml_text):
        href = _text(r.find("d:href", _NS))
        if not href or r.find(".//d:resourcetype/c:calendar", _NS) is None:
            continue
        comps = [c.get("name") for c in
                 r.findall(".//c:supported-calendar-component-set/c:comp", _NS)]
        if comps and "VEVENT" not in comps:
            continue
        color = _COLOR_RE.match(_text(r.find(".//a:calendar-color", _NS)))
        out.append({
            "href": href,
            "name": _text(r.find(".//d:displayname", _NS))[:100] or "Calendar",
            "color": color.group(0) if color else "",
        })
    return out


def report_body(start: date, end: date) -> str:
    s = start.strftime("%Y%m%dT000000Z")
    e = end.strftime("%Y%m%dT000000Z")
    return (
        '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        "<d:prop><d:getetag/><c:calendar-data/></d:prop>"
        '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
        f'<c:time-range start="{s}" end="{e}"/>'
        "</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>"
    )


def parse_calendar_data(xml_text: str) -> list[str]:
    out = []
    for r in _responses(xml_text):
        el = r.find(".//c:calendar-data", _NS)
        if el is not None and el.text:
            out.append(el.text)
    return out


def _as_local(value: Any, tz: ZoneInfo) -> tuple[str, bool]:
    """(ISO string, all_day). A date is all-day; a naive datetime is the
    app's zone (floating time); an aware one is converted to it."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=tz)
        return value.astimezone(tz).isoformat(timespec="minutes"), False
    if isinstance(value, date):
        return value.isoformat(), True
    raise ValueError("not a date")


def events_from_ics(ics_texts: list[str], calendar: dict[str, str],
                    start: date, end: date) -> list[dict]:
    """Expand and flatten the VEVENTs overlapping [start, end). Pure: no I/O.
    Repeating events are expanded here (recurring-ical-events), whatever the
    server did, so the result doesn't depend on iCloud's expand support."""
    tz = _tz()
    out = []
    for text in ics_texts:
        try:
            cal = icalendar.Calendar.from_ical(text)
            occurrences = recurring_ical_events.of(cal).between(start, end)
        # One unreadable calendar object mustn't hide the rest of the window;
        # nothing from it is logged (it is the user's private event text).
        except Exception:  # noqa: BLE001, S112  # nosec B112
            continue
        for ev in occurrences:
            dtstart = ev.get("DTSTART")
            if dtstart is None:
                continue
            try:
                s_iso, all_day = _as_local(dtstart.dt, tz)
                dtend = ev.get("DTEND")
                if dtend is not None:
                    e_iso, _ = _as_local(dtend.dt, tz)
                elif all_day:
                    e_iso = (dtstart.dt + timedelta(days=1)).isoformat()
                else:
                    e_iso = s_iso
            except (ValueError, TypeError):
                continue
            out.append({
                "uid": f"{ev.get('UID', '')}|{s_iso}",
                "title": str(ev.get("SUMMARY", "") or "(no title)")[:300],
                "start": s_iso,
                "end": e_iso,
                "all_day": all_day,
                "location": str(ev.get("LOCATION", "") or "")[:300],
                "calendar": calendar.get("name", ""),
                "color": calendar.get("color", ""),
            })
    out.sort(key=lambda e: (e["start"], e["title"]))
    return out


# --- Cache -------------------------------------------------------------------

_lock = threading.Lock()
_events_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_discovery: dict[str, Any] = {"at": 0.0, "calendars": None}
_last: dict[str, Any] = {"ok": None, "at": None, "error": None}


def _calendars() -> list[dict[str, str]]:
    now = time.monotonic()
    if _discovery["calendars"] is not None and now - _discovery["at"] < DISCOVERY_TTL_SEC:
        return _discovery["calendars"]
    principal = parse_principal(_dav("PROPFIND", ROOT_URL, _PRINCIPAL_BODY, "0"))
    if not principal:
        raise IcloudError("iCloud didn't say where your calendars are.")
    principal_url = urljoin(ROOT_URL, principal)
    home = parse_home(_dav("PROPFIND", principal_url, _HOME_BODY, "0"))
    if not home:
        raise IcloudError("iCloud didn't say where your calendars are.")
    home_url = urljoin(principal_url, home)
    cals = parse_calendars(_dav("PROPFIND", home_url, _CALENDARS_BODY, "1"))
    for c in cals:
        c["url"] = urljoin(home_url, c["href"])
    _discovery.update(at=now, calendars=cals)
    return cals


def fetch_events(start: date, end: date) -> list[dict]:
    """Every event overlapping [start, end) across all event calendars.
    Cached 15 minutes per window. Raises IcloudError / IcloudAuthError.

    The lock is held across the network reads, so two requests for the same
    cold window make one set of calls, not two."""
    if not configured():
        return []
    key = (start.isoformat(), end.isoformat())
    with _lock:
        hit = _events_cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_SEC:
            return hit[1]
        try:
            events: list[dict] = []
            for cal in _calendars():
                xml = _dav("REPORT", cal["url"], report_body(start, end), "1")
                events.extend(events_from_ics(parse_calendar_data(xml), cal, start, end))
            events.sort(key=lambda e: (e["start"], e["title"]))
        except IcloudError as e:
            _last.update(ok=False, at=datetime.now().isoformat(timespec="seconds"),
                         error="auth" if isinstance(e, IcloudAuthError) else "fetch")
            raise
        if len(_events_cache) >= MAX_CACHED_WINDOWS:
            _events_cache.clear()
        _events_cache[key] = (time.monotonic(), events)
        _last.update(ok=True, at=datetime.now().isoformat(timespec="seconds"), error=None)
        return events


def refresh() -> None:
    """Forget cached events and calendars; the next read asks iCloud."""
    with _lock:
        _events_cache.clear()
        _discovery.update(at=0.0, calendars=None)


def last_status() -> dict[str, Any]:
    """For /healthz: did the last fetch work? No network call."""
    return dict(_last)
