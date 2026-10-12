# #436 — /plan and the AI planners

Deep review 2026-10-11 §B2. Four defects, one row, one ship.

## 1. The weekly planner has never seen recurring fires

`weekly_planner_service._load_recurring_fires` calls
`compute_previews_in_range(start, end)`, but that function takes
keyword-only arguments, so every call raises `TypeError`. The `except
Exception` swallows it and returns `[]`, so the prompt always says "(no
recurring fires this week)". It also reads `p["due_date"]`, but the
preview's key is `fire_date`.

Help ("Plan my week" → "What goes into the plan") promises that recurring
fires count as already-committed time.

**Fix:** call it with `start=`/`end=` and read `fire_date`. Narrow the
`except` so a future signature drift fails loudly in tests: the call
moves out of the `try`, which keeps only the import (the import is the
only part that is genuinely optional here).

## 2. Accepting a "move" with no date wipes the task's date

`plan.js` `readOverrides` builds
`due = get("due_date") || s.suggested_due_date`. If the row has no
suggested date and the input is empty, that gives `null`, and `null !==
undefined`, so the PATCH sends `due_date: null`. That clears an existing
date and, because `due_date` is in the payload, skips the server's
Today/Tomorrow date rules (#28 / #435). Auto-categorize hit the same
trap and fixed it in #208.

**Fix:** send `due_date` only when the input or the suggestion has a
date. With neither, the move is section-only, and the server's rules
apply: Today/Tomorrow get that day's date (#435), and other sections
keep the date.

The payload builder moves to a new `static/plan_helpers.js`
(dual-export, Jest-tested), per the anti-pattern #3 rule.

## 3. "Apply all accepted" applies every pending row

`applyAll` applies every row still **pending**, deletes included.
Rows you already accepted are done; ignored rows are skipped. The label
says the opposite, but Help describes it correctly.

**Fix:** the button reads **Apply all remaining**, and Help uses the same
words. The behavior is unchanged.

## 4. Archived goals are offered to the AI planners

`inbox_categorize_service._load_inbox_context`,
`weekly_planner_service._load_goals` and
`weekly_focus_service._load_plan_context` select goals by
`status != DONE` only, so an archived goal (`is_active = False`, #349)
is offered to Claude. Each service validates suggested goal IDs against
that same list, so an archived goal can be suggested and applied.

**Fix:** also require `Goal.is_active`. The /plan page's own goal
dropdown already excludes archived goals: `/api/goals` defaults to
active only.

## Out of scope

Nothing else was found while scoping this.

## Tests

- pytest: `_load_recurring_fires` returns a template firing in the
  window, with its `fire_date`; the planner prompt contains it. Each of
  the three loaders leaves out an archived goal and keeps an active one.
- Jest (`tests/js/unit/plan_helpers.test.js`): a move with no date sends
  no `due_date`; the input date wins over the suggestion; the suggestion
  is used when the input is empty; freeze / delete / project / goal
  rules are unchanged.
- Playwright: /plan with the planner stubbed. A move row with no date
  keeps the task's date when accepted, and the button reads "Apply all
  remaining".

## Cascade

New static file → `sw.js` APP_SHELL + `health.py` EXPECTED_STATIC_FILES +
CACHE_VERSION bump; `<script>` in `templates/plan.html`. Help copy
changes, so the fact-check table is required.
