# #466 — A section move into This Week / Backlog drops a date that doesn't fit

Left by #435 (2026-10-12). Checked 2026-10-16 against `task_service.
update_task`, `realign_tiers_with_due_dates` (00:03) and every path that
moves a task by section.

## What was wrong

A write that names `tier` but not `due_date` kept the date when the task
went to This Week or Backlog. Then the 00:03 re-sort filed it by the date
again:

- a ✨ Plan "Promote to This Week" of a task due weeks out was back in
  Backlog the next morning;
- a due-today task moved to Backlog stayed on today's calendar square,
  and the next night came back to This Week;
- a voice "move to backlog" on an overdue task stayed overdue and was
  re-queued on every run.

Not only the bulk toolbar, ✨ Plan and the Shortcut: the board's own
section buttons, drag and Move ▾ send only the section for This Week /
Backlog too (`tierHelpers.dueDateForTier` is null there). Next Week already
clears any date (#220). The task panel always sends its date.

## The decision (user, 2026-10-16)

Asked with three options (clear a date that doesn't fit / clear only stale
dates / keep every date and pin by hand). **Chosen: clear a date that
doesn't fit** — the cost (a far-off deadline dropped when promoting into
This Week) was stated in the question.

## The rule (`task_service._clear_unfitting_section_date`)

On a write that names `tier` and not `due_date`, that MOVES an active task
to This Week or Backlog (the section changed), a date stays only if it is
after today and `_tier_for_due_date` files it to that section: later this
week (not today / tomorrow) for This Week, after next Sunday for Backlog.
Otherwise it is cleared. Inbox and Freezer keep any date; Next Week is
#220's; the same section re-sent changes nothing. Runs before #435's
Today / Tomorrow re-date.

## Changed tests (they encoded the old rule)

- `test_task_section_move_date.py`: "other sections keep the date" →
  Inbox / Freezer only; new class for #466 (13 + 2 endpoint tests).
- `test_promote_due_today.py` (#220's "punt to This Week / Backlog does
  NOT clear") and `test_tasks_api.py` (#28's "move out of Today leaves the
  date") flipped to the new rule.
- Playwright: the #149 drag test (due-today → This Week) now asserts the
  drag sends no date and the server drops today's; the #436 /plan test
  moves to Backlog (where a far date fits) so it still proves a dateless
  move sends no `due_date`.
- New `tests/e2e/section_move_date.spec.js`: Move ▾ / the phone row —
  due-today → Backlog drops the date; far-dated Backlog → This Week drops
  it; far-dated → Backlog keeps it.

## Help

Sections and auto-fill: one paragraph after #435's.

## Not in this ship

Nothing new found.
