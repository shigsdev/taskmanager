# #444 — Stale counts and views after changes

Deep review 2026-10-11 §B9. Five places that show a number or a list that
doesn't follow what just changed.

## Surface (mapped 2026-10-13)

| # | Where | Today |
|---|---|---|
| 1 | Nav Inbox badge (`base.html`) | Template text "0". Only the board/tier pages (`app.js` `updateInboxBadge`, via `renderBoard`), /goals and /projects set it; /calendar, /completed, /recurring, /docs, /settings, /import, /scan, /review, /reflection, /plan, /strength-forge, /recycle-bin, /utilities, /architecture, /voice-memo, /print show "0" whatever the Inbox holds. |
| 2 | `app.js` `bulkPatch`, `bulkDelete`, `taskDelete` | Reload active tasks only. A bulk Mark complete / Cancel / restore or a delete leaves the board's Completed / Cancelled counts and lists, the /completed page and the Today ring (done-today comes from the completed list) as they were. `taskComplete` / `taskCancel` already reload them. |
| 3 | `settings.js` `runUndo` | Reloads the import history and bin count, not the overview counts (active / total tasks, goals, recurring) or the Inbox badge. |
| 4 | `app.js` `loadRecurringPreviews` | Called once at board init; the 60 s poll, tab-visible refresh, cross-tab sync and every save reload tasks but never previews — a template edited or paused elsewhere keeps its old preview cards. |
| 5 | `app.js` Completed card date; task panel "Created / Updated" | The card shows `updated_at.slice(0, 10)` — the UTC date (evening in the Americas shows tomorrow). The panel parses the zone-less UTC string as LOCAL time, so its date can be a day off the other way. |

## Fix

1. Badge starts as "–" (unknown, muted). A small inline script in
   `base.html` fills it from `GET /api/tasks?tier=inbox` on every page,
   silently doing nothing on failure (the login / unauthorized pages render
   the nav too; plain `fetch`, no `apiFetch` prompt). Pages that count
   their own tasks mark the badge (`data-counted`), and the late page-load
   answer never overwrites them. `window.refreshInboxBadge()` re-fetches.
2. `refreshDoneLists()` (Completed + Cancelled reload, which also redraws
   the Today ring) after `bulkPatch` changes `status`, after `bulkDelete`,
   and after `taskDelete`.
3. `runUndo` also reloads the overview counts and the Inbox badge.
4. Once a page has loaded previews, every `loadTasks` fetches them again
   alongside the tasks (one request, in parallel); a failed refresh keeps
   the previews already shown.
5. New `dateHelpers.parseServerTimestamp(s)` (zone-less = UTC). The card
   shows the LOCAL date (`utcIsoToLocalDate`), the panel formats the parsed
   Date.

Out of scope: Completed lists on /goals and /projects panels (own loaders,
refreshed by their host since #375).

## Tests

- Jest: `parseServerTimestamp` (zone-less = UTC, explicit zone respected,
  junk → null).
- Playwright: badge on /settings and /calendar equals the API's Inbox
  count; bulk Mark complete updates the Completed count without a reload;
  Settings Undo re-reads the overview; a changed preview answer shows after
  `loadTasks`; a completed task updated at 02:30 UTC shows the previous
  day in America/New_York.
