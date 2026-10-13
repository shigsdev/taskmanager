# #467 + #468 — Overdue tasks on the calendar; the empty filter bar

## #467 — overdue tasks don't show on the calendar

`calendar_bucket_helpers.bucketTasks` puts a task on its `due_date` cell. The
grid starts at this Monday (`calendar.js` `thisMonday`), so a task dated
before it has no cell and is invisible. Mid-week an overdue Today task shows
on its past day, not today.

Prod on 2026-10-13: 75 active tasks, 5 past-dated — 2 Today (1 before this
Monday), 3 Backlog (all before this Monday, oldest 158 days). No subtasks.

### Decisions (user, 2026-10-13)

- Marker: a **rust left stripe** on the row, no extra text. Hover / screen
  reader gives "overdue — was due Oct 8".
- A past-dated task in **Today** goes on **today's cell** (it is on the board's
  Today list, so the calendar agrees).
- Any other past-dated task whose day is **before the grid's first day** is
  listed in **Unscheduled under its section** (Backlog & Freezer, This Week,
  …), so it is visible without crowding today.
- A past-dated non-Today task whose day IS on the grid (earlier this week)
  stays on that day. Every past-dated task carries the stripe, wherever it
  shows.

### Change

- `bucketTasks(tasks, todayIso, tomorrowIso, startIso)`: new optional
  `startIso`. Today + past date → today's cell; other tiers with a date before
  `startIso` → `unscheduled` (subtasks there are suppressed, as for undated
  ones). Without `startIso` the old rule holds for past dates on other tiers.
- New pure `isOverdue(task, todayIso)` and `overdueTitle(task)`. `calendar.js`
  `_makeTaskLi` adds `calendar-task-overdue` + the hover text.
- CSS: `.calendar-task-overdue { border-left: 3px solid var(--rust) }` in
  cells and the Unscheduled list.
- Help → /calendar: one bullet.

## #468 — empty filter-banner bar

`.filter-banner { display: flex }` beats the UA `[hidden]` rule, so the
hidden banner drew as an empty copper bar. Add
`.filter-banner[hidden] { display: none; }`.

## Tests

- Jest: `bucketTasks` past-date routing (Today → today, before-grid backlog →
  unscheduled, on-grid backlog stays, no `startIso` = old behaviour),
  `isOverdue`, `overdueTitle`.
- Playwright: a Today task dated before this Monday shows on today's cell with
  the stripe; a backlog one shows under Backlog & Freezer; the board's
  `#filterBanner` takes no height with no filters, and shows with one.
