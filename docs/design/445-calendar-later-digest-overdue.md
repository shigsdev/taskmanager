# #445 — Calendar "Later" group; the digest lists overdue Today tasks once

Filed by the deep review (§B9). Two halves; the overdue half of the calendar
finding already shipped in #467.

## Calendar — tasks dated after the grid

`bucketTasks` puts a dated task in `byDate[due_date]`; the grid only draws
`weeks × 7` cells from this Monday, so a task dated after the last cell has no
cell and shows nowhere.

Prod on 2026-10-13: 69 active tasks; on the default 2-week view (ends Oct 25)
**6 Backlog tasks dated Oct 26 – Nov 8 are invisible**. 0 at 4 or 8 weeks
today, but any date past 8 weeks always is.

### Decision (user, 2026-10-13)

A separate **"Later" group at the bottom of the Unscheduled side panel**
(chosen over "list under its section with its date" and "a count + hint").

- Label: `Later · after Oct 25 (6)`; rows sorted by date, each led by its
  date (`Nov 2 · Renew passport` — first, so a long title's ellipsis can't
  cut it off; the year too when it isn't this year).
- Only drawn when it has tasks. It is **not a drop target** (dropping on
  "later" means nothing); its rows still drag onto a day cell or a section
  group, and click opens the task panel, like every other row.
- The panel heading `Unscheduled (N)` keeps counting only the unscheduled
  groups; the Later group carries its own count.
- A dated subtask past the grid is listed too (a scheduled subtask shows where
  it was scheduled — #231).

### Change

- `bucketTasks(tasks, todayIso, tomorrowIso, startIso, endIso)`: new optional
  `endIso`; a task whose cell date is after it goes to a new `later` list
  (sorted by `due_date`). Without `endIso`, nothing changes (old callers).
- New pure `laterGroupLabel(endIso)` → `"Later · after Oct 25"` and
  `shortDueLabel(dueIso, todayIso)` → `"Nov 2"` / `"Jan 12, 2027"`.
- `calendar.js`: pass `endIso`; `_renderUnscheduled(unscheduled, later, endIso)`
  appends the Later group (`.calendar-later-zone`) when non-empty; its rows
  get a `.calendar-task-date` span and a "due Nov 2" hover.
- CSS: the date span (dim, mono), no hover highlight on the Later box.

## Digest — overdue Today tasks listed twice

`digest_service._build_digest_data` builds `overdue` from every active task
with a past date, so a Today task with a past date is in **Today** and again in
**⚠ Overdue**. /print already leaves Today out of its Overdue list
(`app.py` `print_page`). Prod at filing: 1 such task.

### Change

- `overdue` excludes `Tier.TODAY` (same rule as /print).
- `_task_view` gains `overdue: bool`; the HTML Today row shows an
  **overdue** pill (red, like the amber "due today" one) so the warning isn't
  lost. Plain text already says `(overdue: 2026-10-08)` on the Today line.

## Help

- /calendar Unscheduled bullet: the Later group.
- Email digest "What's in it": overdue = other sections; a Today one is in
  Today, marked overdue.

## Out of scope (filed)

- **#472** — Help's digest section says "Plain text only — no HTML" (it's
  multipart HTML + text since #212) and lists sections in the old order; Help's
  /print "Overdue" line says every past-dated task (Today ones are excluded).

## Tests

- Jest: `bucketTasks` with `endIso` (after → later, sorted; last day stays on
  grid; subtask listed; no `endIso` = old), `laterGroupLabel`, `shortDueLabel`.
- pytest: an overdue Today task appears once in plain text and HTML, with the
  overdue mark; an overdue Backlog task is still under Overdue (red on old).
- Playwright: 2-week view, a task dated 3 weeks out is in the Later group with
  its date and not on the grid; switch to 4 weeks → on its cell, no Later
  group. The quiet case: nothing past the grid → no Later group.
