# Spec #375 — /projects and /goals: real counts, and completed tasks on demand

Status: building (2026-10-10). User choice: "Counts + load on demand".

## 1. The bug, and the numbers that shaped the fix

Both pages fetch `GET /api/tasks` with no `status`, which the API defaults to
`active` (`tasks_api.py:64-72`). So:

- /projects card label `${counts.active} active / ${counts.total} total`
  (`static/projects.js:571`) always shows the same number twice;
- completed tasks never appear on a project card, in the project panel's
  Linked tasks, or in a goal's Linked Tasks — and the `status === "archived"`
  done-styling branches there (`projects.js:592,808`, `goals.js:422,437`) are
  dead code. The user asked during #372 for completed linked tasks to be
  openable.

Goal CARDS are already right: their bar is server-side `goal_progress_batch`
(`goal_service.py:269`), which counts completed tasks.

Prod, 2026-10-10: 73 active tasks (40 KB) vs **1,355 completed (821 KB)**;
one project has 356 completed, one goal 422, 11 projects > 25. `status=all`
also returns cancelled (287) and deleted (105). Hence: never download every
completed task with the page; never use `status=all` here.

## 2. Behaviour

**Counting rule** (identical to goal progress): every task row linked to the
project/goal, subtasks included; `done` = `archived`; `active` = `active`;
cancelled and deleted are in neither.

### /projects

- `GET /api/projects` and `GET /api/projects/<id>` add
  `task_counts: {active, done}` per project — one batched `GROUP BY` query
  for the list (like `goal_progress_batch`), no per-project queries.
- Card label: **`4 active · 356 done`**; `No tasks linked` when both are 0.
  If `task_counts` is missing (stale cached JS against a new server or vice
  versa) the label falls back to today's client count, never "undefined".
- Card task lines: unchanged — active tasks only (#344 drag, #372 open, #377
  focus all keep working on exactly the lines they work on today).
- Project panel: Linked tasks lists active tasks as today, then a collapsed
  **Completed (N)** section (N = `task_counts.done`; hidden when 0).

### /goals

- Goal card: unchanged.
- Goal panel Linked Tasks: active tasks as today, then a collapsed
  **Completed (N)** section, N = the goal's existing `progress.completed`
  (so it always agrees with the card's bar).

### The Completed section (both panels, one shared behaviour)

- Collapsed by default. Opening it the first time fetches only that
  project's / goal's completed tasks:
  `/api/tasks?status=archived&project_id=<id>` (or `goal_id=`) — filters the
  API already supports.
- Sorted newest first by `updated_at` (there is no `completed_at`; editing a
  done task moves it up — accepted, noted).
- Shows 50, then **Show 50 more** (button text says how many remain).
- Each row is a done-styled line that opens the task panel (#372), same as
  an active row; on /goals the existing checkbox branch renders checked and
  disabled (no un-complete from here — unchanged rule).
- Loading / error states are visible ("Loading…", "Couldn't load completed
  tasks — try again"); a stale response (panel switched to another
  project/goal meanwhile) is dropped (#379 generation pattern).
- After a task save or completion the page reloads as today; the count
  updates from the server; if the Completed section is open it re-fetches.

## 3. Code

- `project_service.project_task_counts_batch(ids)`; `projects_api` index +
  show attach `task_counts`.
- `static/completed_tasks_helpers.js` (dual export, Jest-tested):
  `projectCountLabel(counts)`, `completedSummaryLabel(n)`,
  `sortCompletedNewestFirst(tasks)`, `completedPage(tasks, shown, step)` →
  `{visible, remaining}`, `moreButtonLabel(remaining, step)`.
- `projects.js` / `goals.js`: render the section with those helpers; reuse
  each page's existing row builder so done rows look like today's dead
  done-branch intended.
- New static file → `sw.js` APP_SHELL, `health.py` EXPECTED_STATIC_FILES,
  CACHE_VERSION bump.

## 4. Tests

- pytest: counts batch (active/done/cancelled/deleted/subtasks/other
  project/empty ids); `/api/projects` and `/api/projects/<id>` carry
  `task_counts`; one query regardless of project count.
- Jest: every helper branch (0/1/many labels, singular, missing counts
  fallback, sort ties / missing `updated_at`, paging edges).
- Playwright (desktop + mobile): card label shows real active/done; panel
  Completed (N) collapsed → open loads newest-first rows → a row opens the
  task panel; Show more appears past 50 (stubbed); goal panel same; the
  existing "completing from the panel refreshes the side list" test
  extended: the task leaves the active list AND the count moves to done.
- Phase 6 at both viewports.

## 5. Docs

`templates/docs.html` (Help) wherever it describes the project card label or
Linked Tasks — fact-check table in the review message; ARCHITECTURE.md
projects API data flow (`task_counts`); CLAUDE.md Phase 6 checklist lines for
/projects and /goals (Completed section).

## 6. Out of scope

- Showing completed tasks on project CARDS (user chose label-only).
- Un-completing from the panels.
- A `completed_at` column.
