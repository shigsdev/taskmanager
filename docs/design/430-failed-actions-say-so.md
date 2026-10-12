# #430 — Board actions that fail say so

Filed 2026-10-11 by the deep review (§A6).

## 1. Surface

No failure handling (no catch, no message) — the card stays where it was
dropped (the DOM moves during `dragover`) or the panel closes, as if it
worked, until the next ~55 s poll quietly puts it back:

| Site | Code |
|---|---|
| Drag-and-drop: single, from Completed, multi-select group, same-tier reorder | `app.js` `finishDrop` |
| Quick tier buttons / ✓ | `taskMoveTier`, `taskComplete` |
| Panel Delete / Complete, swipe-Delete | `taskDelete`, `taskComplete` (panel closes first), `swipe.js` → `taskDelete` |
| Inbox triage | `bulkMoveTier` — `Promise.all`, one failure skips the reload |
| Drop on Completed (desktop + touch, multi-select) | `app.js` bulk PATCH `.then` only |
| Subtask checkbox | `app.js` subtask row |
| /goals linked-task checkbox, Archive / Unarchive | `goals.js` |

`/api/tasks/bulk` answers 200 with `errors` / `not_found` for the tasks that
failed; the drag group and the Completed drop ignored them (the toolbar's
`bulkPatch` already reports them — the model here).

`saveReorder` sends a whole tier; `/api/tasks/reorder` 422s over 200 ids
(#187), so a drag in a 200+ card tier failed AFTER its tier change landed.
Prod has 69 active tasks today, so this is latent.

Already right: `taskCancel` (alert + return), `bulkPatch`.

## 2. This ship

1. `api_helpers.actionFailureMessage(what, err, bulk)` (Jest): "Moving the
   task didn't save: <reason>. The page now shows what's saved." /
   "Moving the tasks: 1 of 2 didn't save. …" / null when nothing failed or
   when `apiFetch` already showed its own prompt.
2. `apiFetch` marks the errors it already prompted for (network failure,
   expired sign-in) `userNotified`, so callers don't stack a second dialog.
3. `app.js` `boardActionFailed(what, err)` / `boardBulkFailed(what, result)`:
   say it, then `loadTasks()`. Wired into every board site above; Inbox
   triage uses `allSettled` and reports how many failed; a failed Delete
   keeps the panel open. `goals.js` uses the same message + `goalsLoad()`.
4. `/api/tasks/reorder` cap 200 → 1000 (still bounded).
5. Tests (red on old code): Jest for the message + the `userNotified` flag;
   pytest for a 201-card tier reorder; Playwright x 2 viewports with the
   server refusing (stubbed 500): quick tier button, drag to a tier, panel
   Delete, Inbox triage with one of two failing.
6. CACHE_VERSION; CLAUDE.md Phase 6 line + row. Help: no section documents
   these failures; the new message is fact-checked in the ship report.

## 3. Out of scope

- Other pages' unguarded failure paths (recurring Pause, project panel
  Archive, …) — not in this row; the shared message is there for them.
