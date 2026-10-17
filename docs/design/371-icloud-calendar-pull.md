# #371 — Show iCloud Calendar events in the app (read-only)

User request 2026-10-02. The direction and design were decided by the user
on 2026-10-17 (AskUserQuestion, recommended options taken unless noted):

| Decision | Choice |
|---|---|
| Direction | **Pull iCloud events in** (CalDAV), read-only. Not an .ics feed out |
| Which calendars | **All** calendars that hold events |
| Where shown | **/calendar grid**, **board day strip**, **daily digest email** |
| Freshness / storage | **In-memory server cache, 15 min**; nothing stored in the DB; a Refresh control forces a fetch |
| Click | **Read-only details**: title, time, location, calendar |

## Credentials and risk

- `ICLOUD_USERNAME` (Apple ID email) and `ICLOUD_APP_PASSWORD` (an Apple
  **app-specific** password, which needs 2FA) are set by the user as
  Railway env vars. Both unset means the feature is off and every surface
  is unchanged.
- That password also opens the user's iCloud Mail and Contacts, a bigger
  blast radius than any key the app holds today. Mitigations:
  - env-only, never in the DB;
  - read-only use: PROPFIND / REPORT, never PUT / DELETE;
  - an https host allowlist (`caldav.icloud.com`, `p<N>-caldav.icloud.com`);
  - no redirects followed;
  - the scrubber covers Basic auth (#497) and the
    `xxxx-xxxx-xxxx-xxxx` password shape.

  The user can revoke the password at account.apple.com at any time, and an
  Apple password change revokes all of them. The threat model in CLAUDE.md
  gets a bullet. ADR-041 covers the new egress path.
- **ADR-023 says every external call goes through `egress`.**
  `safe_call_api` is POST + JSON only (`egress.py:236-266`), so add
  `egress.safe_call_dav(method, url, headers, body, vendor)`:
  - PROPFIND / REPORT only;
  - XML text back;
  - `allow_redirects=False`;
  - https and the host allowlist checked before every call;
  - errors carry no URL and no credentials.

## Ships

**#371a — read path + /calendar.**
- `icloud_service.py`:
  - discovery: `PROPFIND /` current-user-principal (Depth 0), then
    calendar-home-set (Depth 0), then the calendars (Depth 1, VEVENT only);
  - `REPORT calendar-query` with a time-range and `<C:expand>`;
  - client-side expansion via `recurring-ical-events` when the server
    doesn't expand;
  - parse with `icalendar`;
  - normalise to `{uid, title, start, end, all_day, location, calendar,
    color}` in DIGEST_TZ.
- In-memory TTL cache (15 min, keyed by window, lock-guarded; workers each
  keep their own, which is fine at one user). A Refresh button busts it.
- Routes:
  - `GET /api/icloud/events?start&end` (≤70 days, like previews);
  - `POST /api/icloud/refresh`;
  - both `@login_required`;
  - `{enabled: false}` when unconfigured; `{error}` + 502 on an iCloud
    failure (the page says so, and the tasks still draw).
- `/calendar`: a third list per cell (`.calendar-cell-events`), styled
  apart from tasks and previews, not draggable; click or Enter opens a
  read-only details dialog (uses #419's focus watcher). A notice appears
  when iCloud fails or the password is revoked (401/403).
- `/healthz` `icloud` check: `skipped` when unset; `warn` on an auth or
  network failure, never `fail`. iCloud being down must not block a deploy.
- Help section, README env rows, `.env.example`, ARCHITECTURE (route
  catalog, egress, data flow).
- New deps: `icalendar`, `recurring-ical-events` (pip-audit clean).

**#371b — board day strip + digest.** Reuses #371a's service and cache.

## Tests (TDD)

- pytest:
  - XML discovery and calendar-list parsing against recorded iCloud-shaped
    fixtures;
  - event normalisation: all-day, timed, TZID, recurring expansion;
  - cache TTL and refresh;
  - route 200 / 400 / 502 and unconfigured;
  - egress allowlist: a foreign host refused, http refused, no redirect;
  - scrubber: password shape.
- Jest: a dual-export `icloud_event_helpers.js` (bucket events by day, label
  times).
- e2e: `/calendar` with the events API stubbed. Events draw in their cells,
  click opens the details, a failure notice shows, and the tasks are
  unchanged.

## As built — #371a (2026-10-17)

- `egress.safe_call_dav` (ADR-041); `EgressError.status`.
- `icloud_service.py`: discovery cached 1 h, events 15 min per window
  (at most 16 windows), 10 s per request, lock held across reads.
  Calendar color kept only when it is `#RRGGBB`. No `<C:expand>` in the
  REPORT: expansion is always client-side, so the result doesn't depend on
  the server.
- `icloud_api.py`: `GET /api/icloud/events` (end inclusive, as the grid
  asks; the service window ends a day later) and `POST /api/icloud/refresh`
  (OUTBOUND_FETCH rate limit).
- `/healthz` `icloud`: skipped / ok / warn, read from the last fetch only.
- `/calendar`: a strip above the grid ("Showing your iCloud Calendar
  (read-only)", ↻ Refresh iCloud, failure text) shown only when on; events
  above each day's tasks; details dialog is a `.modal-overlay`, so #406 /
  #419 give it Escape, Tab trap and focus return.
- Scrubber: `[REDACTED:APP_PASSWORD]` for the password shape.
- #371b (board day strip + digest) is its own row.
