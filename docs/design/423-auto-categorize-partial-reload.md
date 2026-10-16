# #423 — 💡 Auto-categorize reloads the board after a partial failure

Found 2026-10-11 by the #422 spec §3. Checked 2026-10-15.

## What's wrong

`static/inbox_categorize.js` `applyAll` PATCHes each row in turn and removes
the rows that saved. It calls `loadTasks` only when every row saved. When
some fail, the dialog stays open on the failed rows ("Apply remaining (n
failed)") — right — but the board behind it isn't reloaded, so the tasks
that DID move still sit in the Inbox column until the next reload. ✨ Plan
reloads after every apply (`weekly_focus.js` `applyPlan`).

## This ship

`applyAll` reloads the board whenever at least one row saved, whatever
happened to the others. (When none saved there is nothing to redraw.) The
dialog behaviour is unchanged: all saved → it closes; some failed → it stays
open on those rows.

## Tests

Playwright (after the #421 block): two real Inbox tasks, the categorize
answer stubbed to suggest This Week for both, one PATCH stubbed to 500.
Apply all → the saved task's card leaves the Inbox column and shows under
This Week while the dialog stays open on the failed row with "Apply
remaining (1 failed)". Red on the old code.
