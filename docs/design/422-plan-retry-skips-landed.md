# #422 — ✨ Plan's "Apply remaining" only retries what failed

Filed 2026-10-11 by the #418 spec §3. When some of a ✨ Plan's approved
changes fail, the button reads "Apply remaining (N failed)", but
`applyPlan` (`static/weekly_focus.js`) keeps every change in
`pendingChanges`, still ticked. Clicking it sends the whole list again.

## 1. Surface

Every "apply a reviewed list, then let the user retry" loop in the app:

| Loop | What a retry sends | Duplicate? |
|---|---|---|
| ✨ Plan `applyPlan` (`weekly_focus.js`) | every ticked change, including the ones that landed | **Yes** — a `create_new` that landed is POSTed again: a second task with the same title. Promote/demote PATCHes repeat harmlessly. |
| 💡 Auto-categorize `applyAll` (`inbox_categorize.js` ~414) | only rows still on screen; each applied row is removed (`tr.remove()`) | No |
| `/plan` `applyAll` (`plan.js` ~354) | only rows whose state is still `pending`; applied rows become `accepted` | No (PATCH/DELETE only anyway) |

So only ✨ Plan is in scope.

## 2. This ship

1. In `applyPlan`, mark each change that lands (`_landed`) and each that
   fails (`_failed`; cleared at the start of each try).
2. After the loop — and only if the dialog is still ours (the #418 guard) —
   drop landed changes from `pendingChanges` and re-render. Landed rows
   leave the list (as in Auto-categorize). Failed rows stay ticked and get a
   light red tint (`weekly-focus-plan-row-failed`, same colour as
   `auto-categorize-row-failed`), so it is clear which ones didn't go through.
3. `renderPlanRow` keeps a row's tick as the user left it
   (`change._applied !== false`) instead of re-ticking everything, so a
   change the user unticked stays unticked after the re-render.
4. The button text stays "Apply remaining (N failed)". A retry sends only
   the ticked rows, which are now just the failures.
5. CACHE_VERSION bump (v292).
6. Tests — Playwright, desktop + mobile, red on the old code: a plan with a
   `create_new` and a promote, plus one unticked promote, and the promote's
   PATCH fails once. After Apply: the created task's row is gone, the failed
   row is tinted and still ticked, the unticked row is still unticked.
   "Apply remaining" then sends exactly one request (the failed PATCH) and
   the dialog closes; exactly one POST /api/tasks was sent in total.
7. Help (`docs.html`, "Planning against your focus"): one sentence on what
   a partial failure looks like and what Apply remaining sends.
8. CLAUDE.md Phase 6 line plus a report row.

## 3. Out of scope (filed)

- **#423** — 💡 Auto-categorize doesn't reload the board after a partial
  failure: `applyAll` calls `loadTasks` only when everything worked
  (`inbox_categorize.js` ~434-438), so the tasks that did move stay in the
  Inbox column behind the dialog until the next reload.
