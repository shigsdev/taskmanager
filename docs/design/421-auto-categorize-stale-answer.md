# #421 — 💡 Auto-categorize drops a stale answer

Found 2026-10-11 by the #418 spec §3. Checked 2026-10-15 against
`static/inbox_categorize.js`.

## What's wrong

The 💡 Auto-categorize review is one shared dialog (`#autoCategorizeModal`).
`openModal` awaits three things before it draws rows: `loadTasks`, then
`/api/projects` + `/api/goals`, then `POST /api/inbox/categorize` (a Claude
call, seconds long). Nothing checks, after each wait, that this is still
the dialog showing:

1. ~~Close, reopen, first answer lands late~~ — **can't happen any more**:
   checked 2026-10-15, #429 wraps the 💡 button in `withInflight`, so it
   stays disabled (`aria-busy`) until the run's answer arrives, and the
   dialog can't be reopened mid-run. (The row was filed before #429.) The
   guard below still covers it.
2. **Close while it's thinking** → the answer still draws rows, un-hides the
   table and Apply button inside the hidden dialog (they show on the next
   open until that run replaces them).
3. **`applyAll` still running when the dialog is closed and reopened** → at
   the end it calls `closeModal()` (closing the new run) or rewrites the new
   run's Apply button ("Apply remaining (n failed)") and re-enables it
   mid-load. The same for a single row's Apply: `updateAfterRowChange`
   counts the new run's rows and can close it.

## This ship

Reuse `static/request_guard_helpers.js` exactly as `weekly_focus.js` does
for ✨ Plan (#418):

- `openModal` → `var mine = guard.begin()`; after each `await`,
  `if (!guard.isCurrent(mine)) return;`. `closeModal` → `guard.cancel()`.
- `applyAll` and a single row's Apply take the run's token at the start. The
  PATCHes they already sent finish (the user asked for them), and the board
  still reloads, but the dialog — close, button text, enabled state, row
  count — is only touched while that token is current.
- `openModal` also clears the hint text, so a previous run's "Showing the
  first N…" / "Inbox is empty" can't carry over.

No user-visible change when the dialog is used one run at a time.

## Tests

Playwright (`pages.spec.js`, after the #418 block), with
`/api/inbox/categorize` answers held until the test releases them:

- close while thinking, release → the dialog stays closed, no rows.
- Apply all with a PATCH held, close, reopen run B, release → B stays open
  with its own rows and button.
- the quiet case: one run, Apply all → closes and the board reloads.

## Not in this ship

- #423 (board not reloaded after a partial failure) — same function, own row,
  next in the queue.
