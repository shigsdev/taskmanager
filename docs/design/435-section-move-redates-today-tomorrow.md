# #435 — A section-only move to Today / Tomorrow re-dates the task

Deep review 2026-10-11 §B1. One row in, one ship out.

## The bug

Several paths change a task's section (`tier`) without sending a `due_date`:

| Path | Code | Sends |
|---|---|---|
| Bulk toolbar Section ▾ → Apply | `static/app.js` bulk apply → `PATCH /api/tasks/bulk` | `{tier}` (plus any other staged field) |
| Voice Shortcut "move" | `voice_review_api.py` `move` | `update_task(id, {"tier": tier})` |
| ✨ Plan promote / demote | `static/weekly_focus.js` `applyPlan` | `{tier: "today" / "this_week" / "next_week" / "backlog"}` |
| Inbox triage bulk move | `static/app.js` triage handler | `{tier}` |
| AI review suggestion | `static/review.js` `applySuggestion` | `{tier: suggested_tier}` |

(`static/plan.js` "move" always sends `due_date`, even `null`, so it
isn't tier-only.)

`update_task` keeps the old date: `_auto_fill_tier_due_date` fills a date
only when there is none. So:

- A Today task bulk-moved to Tomorrow keeps today's date, and the Today
  panel's #161 pull (tier=tomorrow, date=today) shows it in **both** panels.
- An overdue task voice-moved to Today stays overdue, so the Shortcut's
  queue lists it under "overdue" again on every run.
- A ✨ Plan "Promote to Today" on a dated task keeps the old date.

The board's own tier buttons and drag (`taskMoveTier`,
`_patchBodyForTierDrop`) already send `dueDateForTier(tier)` alongside the
tier, so they don't have the bug.

## The fix (this ship)

In `task_service.update_task`: when the payload names `tier` but not
`due_date`, and the task ends up **active** in **Today** or **Tomorrow**,
set `due_date` to that day (today / today + 1, local `DIGEST_TZ`),
replacing any older date. That's the same rule the board buttons follow,
now on the server, so every path gets it, including future ones.

- It applies even when the tier didn't change: "move to Today" on an
  overdue Today task means "do it today", the same as the board's Today
  button.
- If the payload has `due_date` (the task panel, bulk Due, a /plan move
  with a date), that date wins, as before.
- Not applied to a task that isn't active.
- Create (`create_task`) is unchanged: it already fills a missing date
  for Today / Tomorrow.

## Not in this ship (user decision 2026-10-12)

Moves to **This Week / Next Week / Backlog** whose date falls outside
that section keep the date (Next Week still clears it, #220). The user
chose the narrow fix. The remaining symptoms (a ✨ Plan "Promote to This
Week" undone by the 00:03 realign, a today-dated task moved to Backlog
pulled back into This Week overnight, a voice "move to backlog" on an
overdue task re-queued) are filed as **#466**.

## Tests

- pytest (`tests/test_task_section_move_date.py`): tier-only PATCH to
  Today / Tomorrow over an older date, overdue → Today on the same tier,
  explicit `due_date` wins, This Week / Backlog / Inbox / Freezer leave
  the date alone, inactive task untouched, the bulk endpoint, and the
  voice `/move` endpoint.
- Playwright: bulk-select a Today card → Section ▾ Tomorrow → Apply. The
  card is in Tomorrow only, and its date is tomorrow.

## Help

`templates/docs.html` "Due-date auto-fill": add the move rule. Also fix
the "moving out of Today/Tomorrow does NOT clear the date" sentence,
which is already wrong for Next Week (#220).
