# ADR-040: /healthz answers one other origin — the off-Railway status page

Date: 2026-10-17

Status: ACCEPTED (backlog #204 option E; spec `docs/design/204-status-page.md`)

## Context

During the 2026-05-19 Railway/GCP outage there was no way to tell, from
anywhere but Railway's own dashboard, whether the app was down, how long it
had been down, or what was deployed (#204). Option E of the #204 design was
a static page hosted somewhere other than Railway that polls the app's
`/healthz`. The user approved publishing it on GitHub Pages
(`https://shigsdev.github.io/taskmanager/`, the repo is public) on
2026-10-17.

A page on another origin can only read `/healthz` from the browser if the
response opts in with CORS. Until now the app set no CORS headers anywhere,
so every response was readable only by its own origin.

`/healthz` was already unauthenticated and public (CLAUDE.md's threat
model: "`/healthz` is unauthenticated and returns the deployed git_sha").
Its body holds the git SHA, start time, digest schedule and per-check status
strings. It holds no task data, no email addresses and no keys; the checks
are written to stay small and non-sensitive (`health._short`).

## Decision

`/healthz` sets `Access-Control-Allow-Origin` to exactly
`STATUS_PAGE_ORIGIN = "https://shigsdev.github.io"` (`app.py`) when the
request's `Origin` header equals it, on both 200 and 503, and always sends
`Vary: Origin`. Nothing else changes:

- Exact match only. No wildcard, no suffix or prefix match, no `http://`,
  no `null`.
- No `Access-Control-Allow-Credentials`, so the browser sends no cookies
  cross-origin and the page can't act as the user.
- Simple GET only. No preflight handling and no other method or header is
  allowed.
- Only `/healthz`. Every other route stays same-origin.

## Consequences

**Gained:** a status page that loads when Railway can't serve anything, and
says up / degraded / down, how long since the app was last healthy, and
what's deployed. No secrets live on it and it has no write path.

**Given up / accepted:**
- Any page served from `shigsdev.github.io`, the user's GitHub Pages
  domain, can read `/healthz` in a browser. That body is already public to
  anyone with `curl`; CORS only governs browsers. The blast radius is "the
  same public health report, readable by one more kind of page".
- If `/healthz` ever grows a sensitive field, it is now readable
  cross-origin from that domain as well. Keep `/healthz` free of user data.
  That was already the rule, since it is unauthenticated.

**Guards:** `tests/test_healthz_cors.py`: the status origin gets the
header (also on a 503); four look-alike or foreign origins and a request
with no `Origin` get none.
