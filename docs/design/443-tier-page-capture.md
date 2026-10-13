# #443 — The capture bar on /tier/<name> always files to Inbox

Deep review 2026-10-11 §B9.

`parseCapture` (static/parse_capture.js) starts every result with
`tier: "inbox"`, so in `capture.js` the tier page's `data-default-tier`
("Add a task to Today…", templates/tier.html) never applies — the
`!parsed.tier` check is always false.

## Fix

- `parseCapture` sets `tier` only when a section hashtag matched.
- `capture.js` already falls back to the bar's `data-default-tier`; with no
  default (the board, /goals, /projects, /completed …) `tier` is omitted and
  the server's own default applies (`task_service.create_task`: Inbox).
- A hashtag still wins on a tier page (`#backlog` on /tier/today → Backlog).
- Help → capture bar: "Default section is Inbox" gains the tier-page case.

No server change. Surface checked: `parseCapture` has one caller
(`capture.js`); nothing else reads `parsed.tier`.

## Tests

- Jest: no hashtag → `tier` undefined (was "inbox"); hashtags unchanged.
- Playwright: /tier/today capture → Today; `#backlog` there → Backlog; the
  board's plain capture → Inbox (the quiet case).
