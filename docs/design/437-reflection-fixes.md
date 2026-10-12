# #437 — Reflection: local "today", retryable Apply, readable errors

Deep review 2026-10-11 §B3. One row, one ship.

## 1. "Today" and the ISO week come from UTC

`reflection_service.current_iso_week()` defaults to
`datetime.now(UTC).date()`, and `analyze_transcript` tells Claude
`today=datetime.now(UTC).date()`. After 8 pm ET (midnight UTC) Claude is
told tomorrow's date, and a Sunday-evening reflection is filed under the
next ISO week. Every reflection row gets its `iso_week` from
`current_iso_week()` (four call sites).

**Fix:** both use `utils.local_today_date()` (`DIGEST_TZ`), the
app-wide answer to "what day is it for the user" (audit fix #128, #340
for reflection labels).

## 2. A partly failed Apply can't be retried

`apply_selected_actions` records per-step failures in `summary["errors"]`
(#174) but then sets `applied_at` anyway, so the route answers any retry
with 409. The failed actions can never be applied from that reflection.

Every service call it makes commits its own work (`create_*_from_import`,
`create_tasks_from_candidates`, `update_*`, `delete_*`), so a failure's
`rollback()` undoes only the failing step. Which actions landed is
therefore exact:

- creates of one kind succeed or fail together (one creator call per kind);
- each update / delete succeeds or fails on its own.

**Fix (server):**
- Track which of the sent actions failed; return their positions as
  `summary["failed"]` (indices into the request's `actions`).
- Set `applied_at` only when nothing failed.
- Keep the audit record cumulative: `applied_actions.actions` lists every
  action that has landed so far.
- **Never apply the same action twice.** On every confirm, an action that
  equals one already landed for this reflection (canonical JSON) is
  skipped and counted in `summary["already_applied"]`. A retry can
  therefore resend anything, including a full re-apply after reopening the
  reflection, without creating duplicates. The review rows are not
  editable, so equality is exact.
- The 409 is unchanged once `applied_at` is set.

**Fix (page):** after a partial apply (HTTP 207), the review screen stays
up instead of jumping to the done screen:
- rows that landed are unticked, disabled and marked "✓ applied";
- rows that failed stay ticked and are shaded;
- a message under the buttons says how many were applied, lists what
  didn't save, and says to press Apply again (or untick what you no
  longer want).

Apply Selected then sends only the failed rows. When a later apply
finishes with nothing failed, the done screen shows as before. The
mapping from response to rows lives in `reflection_helpers.js`
(`applyOutcome`, Jest-tested).

History shows "◐ partly applied" for a reflection with landed actions and
no `applied_at`, next to the existing "✓ applied".

## 3. Raw database errors in the error text

Errors are built as `f"{step}: {type(e).__name__}: {e}"`. For a database
failure that is the raw SQLAlchemy / psycopg message, the leak #189
removed from the global error handler.

**Fix:** a failure is logged with `logger.exception` (full detail, server
side), and the user sees a plain sentence naming the item, e.g.
`Couldn't create 3 tasks — nothing was saved for them.` or
`Couldn't update task "Book dentist" — it no longer exists.`

## 4. A failed Apply throws away the review

`reflection.js` sends a thrown Apply error (network, 500) to the error
screen (`showErr`), which hides the review. The only way back is
re-opening the reflection from History.

**Fix:** stay on the review, re-enable Apply, and show the reason under
the buttons (the #431 pattern for "Analyze so far").

**Submit / analyze failures — checked, not changed:** when submitting or
re-analyzing fails, no new review exists yet. The transcript is already
saved and the error screen says it can be re-analyzed from History. The
deep review grouped these with Apply; there is no review to keep. #464
already tracks the one wrong message on that path.

## Out of scope

- If the final audit-record commit itself fails after everything landed,
  nothing records what landed, so a re-apply could duplicate. That needs
  a database failure between two commits in the same request. Noted here,
  not filed: nothing realistic triggers it.

## Tests

- pytest: `current_iso_week()` and the prompt's `today` at 23:30 ET on a
  Sunday (UTC Monday) give Sunday's date and week; a confirm where the
  task create fails returns 207 with `failed`, leaves `applied_at` unset,
  and the retry applies only the failed action; resending landed actions
  doesn't create duplicates (`already_applied`); a DB error's text
  doesn't reach the response; a fully successful retry sets `applied_at`
  and a third confirm is 409.
- Jest: `applyOutcome` maps sent row keys + failed indices to applied /
  failed keys.
- Playwright: on /reflection with analysis stubbed, make the confirm
  answer 207 with one failure. The review stays, the landed row is
  disabled, the failed row is still ticked, and Apply sends only it. A
  thrown 500 keeps the review with the reason shown.
