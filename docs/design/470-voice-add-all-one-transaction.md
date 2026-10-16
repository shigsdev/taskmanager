# #470 — Voice memo Add All is all-or-nothing

Filed 2026-10-13 by the #442 spec (+ #447's sweep). Checked 2026-10-16
against `voice_api.confirm`, `scan_service.create_tasks_from_candidates`,
`import_service.create_goals_from_import` / `create_projects_from_import`
and `recurring_service.create_recurring_template_from_voice_candidate`.

## What was wrong

- `confirm` ran four steps — tasks, recurring templates, goals, projects —
  and each committed on its own. A failure part-way (a goal or project
  insert) came back as an error with the earlier steps saved. #442 keeps
  the reviewed list so you can retry, and said "check your Inbox first",
  but Add All again re-created what had landed.
- The recurring step caught `Exception` without a rollback. On Postgres a
  database error there leaves the session failed, so the goal / project
  steps after it would fail too (likely a 500 after the tasks were saved).

## This ship (the "one transaction" option from the row)

- The four creators take `commit=True` (keyword-only); `commit=False`
  flushes only. Every other caller (scan, import, reflection, the
  /recurring page) is unchanged.
- `confirm` runs all steps with `commit=False` and commits once. Any
  exception: `rollback()`, log it, answer 500 `{error: "something went
  wrong on the server", saved: false}` — nothing was saved.
- Each recurring item runs in its own savepoint (`begin_nested`), as the
  bulk task update already does. A bad item is still skipped on its own
  (#155's intent) and reported in `warning` (#425); its rollback no longer
  poisons the batch. `create_recurring_template_from_voice_candidate` now
  swallows only a refused shape (ValidationError / ValueError / TypeError),
  so a database error reaches that savepoint.
- Page (`voice_memo.js`): `voiceMemoHelpers.confirmFailureTail(err)` —
  an error the server answered (it has a `status`, #464) means nothing was
  added: "Nothing was added, and your list is still here — Add All again."
  No answer (a lost reply after the save) keeps the "check your Inbox"
  caution. (A dropped connection is usually handled by apiFetch's own
  reload prompt first, which shows no message here — unchanged.)
- Help → Voice memo: one sentence.

## Tests

- pytest `tests/test_voice_confirm_atomic.py`: the whole batch lands (the
  quiet case); a failed goal step / project step saves nothing (red on the
  old code — the tasks were saved) and a retry adds each item once; a
  database error in one recurring item skips only it (green on SQLite
  before too: SQLite doesn't fail the session the way Postgres does —
  kept as the guard for the savepoint); a refused recurring shape is still
  skipped.
- Jest `voice_memo_helpers.test.js`: `confirmFailureTail`.
- Playwright: the #442 "failed Add keeps the list" test now expects the
  new message (red on the old page code).

## Not in this ship

Nothing new found.
