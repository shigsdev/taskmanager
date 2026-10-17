# ADR-041: A read-only WebDAV egress path for the iCloud Calendar reader

Date: 2026-10-17

Status: ACCEPTED (backlog #371a; spec `docs/design/371-icloud-calendar-pull.md`)

## Context

The user asked to see their iCloud Calendar events in the app (#371). On
2026-10-17 they chose to **pull** them over CalDAV, read-only, from all event
calendars, cached in memory for 15 minutes and never stored.

iCloud CalDAV authenticates with HTTP Basic and an Apple **app-specific
password**. That password is not scoped to calendars: it also opens the
user's iCloud Mail and Contacts. That is a bigger blast radius than any
credential the app held before.

ADR-023 routes every outbound call through `egress.py`. Its two existing
paths don't fit:

- `safe_call_api` is POST + JSON only.
- `safe_fetch_user_url` is for user-supplied URLs (an SSRF defense) and
  sends no credentials.

CalDAV needs `PROPFIND` and `REPORT` with XML bodies. The host is not
constant: discovery starts at `caldav.icloud.com`, and the server then
points at a per-account partition host (`p42-caldav.icloud.com`).

## Decision

Add `egress.safe_call_dav(method, url, headers, body, vendor, host_allowed,
timeout_sec=10)`:

- **Read methods only.** `PROPFIND` and `REPORT`. Anything else (`PUT`,
  `DELETE`, `PROPPATCH`, `MKCALENDAR`, `POST`, `GET`) is refused before the
  network, so no bug upstream can write to the account.
- **https only**, and the caller's `host_allowed(hostname)` must say yes.
  For iCloud that is `^(caldav|p\d{1,4}-caldav)\.icloud\.com$`
  (`icloud_service.host_allowed`), checked again on every hop of discovery.
- **No redirects.** `allow_redirects=False`; a 3xx is an error. A redirect
  is how a credential gets walked to another host.
- **Errors carry the status, not the URL.** `EgressError` gained an
  optional `status` attribute. Its message names the vendor and the status,
  never the URL (it holds the account number) or a header.

Around it:

- **Credentials:** `ICLOUD_USERNAME` / `ICLOUD_APP_PASSWORD` live in env
  only. Both unset means the feature is off and nothing calls Apple.
- **Log scrubbing:** the scrubber redacts any `Authorization: <scheme>
  <credential>` (#497) and the `xxxx-xxxx-xxxx-xxxx` password shape.
- **XML parsing:** `defusedxml`, so no entity expansion and no external
  entities.
- **Auth failures:** a refused password (401/403) is surfaced as a 502
  with `auth: true` and a "make a new one at account.apple.com" message.
  It is never a 401, which the page would read as "sign in again".

## Consequences

**Gained:** the user's appointments show on `/calendar` beside their
tasks. One outbound path, in one module, is the only place the password
is ever sent.

**Given up / accepted:**
- A leaked `ICLOUD_APP_PASSWORD` exposes iCloud Mail and Contacts, not
  just calendars. Mitigations are keeping it out of the DB, logs, URLs and
  error messages. Kill-switch: revoke it at account.apple.com (changing
  the Apple password revokes them all).
- The validator cookie, which authenticates read-only GETs, can now read
  the user's calendar events through `GET /api/icloud/events` for as long
  as it is valid. It can't refresh the cache (POST).
- Each Gunicorn worker keeps its own cache, so a cold worker reads iCloud
  again. At one user this is a handful of extra requests per hour.
- The service lock is held across the network reads (up to 10s per
  request), so a second request for a cold window waits instead of
  doubling the calls.

**Guards:**
- `tests/test_egress_dav.py`: every write method refused before the
  network; http refused; a foreign or look-alike host refused;
  `allow_redirects=False`; a 3xx is an error carrying its status; no URL
  or credential in any message.
- `tests/test_icloud_service.py`: the host allowlist; only read methods
  and Basic auth; entity expansion refused.
- `tests/test_logging.py`: the password shape is scrubbed.

## Alternatives considered

- **The `caldav` library.** Rejected: it would make its own HTTP calls
  outside `egress` (against ADR-023), follow redirects by default, and add
  a larger dependency for the three requests we need.
- **Reuse `safe_call_api` with a method parameter.** Rejected: it would
  widen a path every other vendor uses to allow arbitrary methods, and its
  JSON response handling doesn't fit XML.
- **An .ics subscription URL** (a public calendar link). Rejected by the
  user's choice to pull all calendars. A public link would also make the
  events readable by anyone holding the URL.
- **Push app tasks out as a feed** instead of pulling events in. Not what
  the user asked for (they want to see events beside tasks).
