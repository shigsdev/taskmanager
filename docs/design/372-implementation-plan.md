# #372 Linked Tasks Open the Task Panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking, tapping, or pressing Enter/Space on a linked task line on /goals or /projects opens the full task detail panel in place, and saving from it refreshes the page and the still-open goal/project panel.

**Architecture:** `goals.html` and `projects.html` include `_task_detail_panel.html` after their own overlay, so `app.js init()` takes the existing #270 panel-only branch and DOM order stacks the task panel on top. Each page registers `window.taskDetailAfterSave` to reload its data and re-render the open goal/project panel's list. A pure `taskLineClickOpens` helper decides whether a click that follows a touch long-press should open the panel.

**Tech Stack:** Flask/Jinja templates, vanilla JS (classic scripts), Jest, Playwright.

**Spec:** `docs/design/372-linked-tasks-open-the-task-panel.md`

## Global Constraints

- Branch `feature/372-linked-tasks-open-panel` (already holds the spec commit `4128d21`). Never commit to `main` directly.
- No backend change. No `app.js` change.
- Row affordance on all three surfaces: `tabindex="0"`, `role="button"`, `aria-label` exactly `Open task: <title>`, pointer cursor; click and Enter/Space call `taskDetailOpen(task)` with the task object the page already holds. Keyboard handler acts only when `e.target === row` (a keypress inside the checkbox must not open the panel).
- Long-press click guard window: **700ms** after the 500ms long-press timer fires.
- DOM via `createElement` / `textContent` only. Never add `innerHTML`; leave the existing `innerHTML` lines in `goals.js` / `projects.js` alone.
- `goals.js` / `projects.js` are classic scripts sharing global scope with `app.js`: new top-level names must not collide (`allTasks`, `allGoals`, `allProjects`, `loadTasks` belong to `app.js`).
- `static/sw.js` `CACHE_VERSION` `v263` → `v264`. No new static files.
- Stage files explicitly; never `git add -A`; never `SESSION_HANDOFF.md`; revert gate-run audit-row churn in `BACKLOG.md` (`git diff --ignore-cr-at-eol BACKLOG.md`) before staging.
- Commits via `git commit -F <scratchpad file>`, ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **The goal-row checkbox still only completes.** Clicking it must not also open the panel (click bubbles to the row). → Task 2 Playwright `checkbox completes without opening the panel`.
2. **Space on the focused checkbox** bubbles a keydown to the row; it must tick the box, not open the panel. → Task 2 Playwright `Space on the checkbox does not open the panel`.
3. **A save that moves the task OFF the open goal** (goal dropdown changed in the task panel): the row leaves the goal panel's list, the count drops, and the hard-delete hint is re-checked rather than left stale. → Task 2 Playwright `re-goaling a task removes it from the open goal panel`.
4. **Complete from the stacked task panel on /projects** (list is active-only): the row leaves the side list and the panel summary count drops. → Task 3 Playwright `completing from the panel refreshes the side list`.
5. **Mouse drag on a card line still never opens the panel** (no click after native drag) and the #344 suite is unchanged. → Task 3 runs the whole `Projects - drag a task to another project (#344)` describe block green, unmodified.

---

### Task 1: `taskLineClickOpens` helper

**Files:**
- Modify: `static/project_task_drag_helpers.js` (new function + both export blocks, lines ~114-125; header comment gains a #372 paragraph)
- Test: `tests/js/unit/project_task_drag_helpers.test.js` (new `describe("taskLineClickOpens (#372)")`)

**Interfaces:**
- Produces: `taskLineClickOpens(longPressAt: number|null, now: number) -> boolean` — `true` when `longPressAt` is null/undefined or `now - longPressAt > 700`; `false` otherwise. Exported on `module.exports` and `window.projectTaskDragHelpers`.

- [ ] **Step 1: Write the failing tests** — `opens when no long-press has fired` (`(null, 1000)` → true; `(undefined, 1000)` → true); `swallows a click right after a long-press` (`(1000, 1000)` → false, `(1000, 1700)` → false); `opens once the window has passed` (`(1000, 1701)` → true); `opens for a stale long-press` (`(1000, 60000)` → true).
- [ ] **Step 2: Run** `npx jest tests/js/unit/project_task_drag_helpers.test.js` — Expected: FAIL (`taskLineClickOpens is not a function`).
- [ ] **Step 3: Implement** in `static/project_task_drag_helpers.js` with a named constant `TASK_LINE_LONG_PRESS_GUARD_MS = 700`; comment says why (a released long-press can still synthesize a click on touch browsers).
- [ ] **Step 4: Run** the same command — Expected: all PASS.
- [ ] **Step 5: Commit** `feat(#372): helper decides whether a task-line click follows a long-press`.

### Task 2: /goals — host the panel, open from Linked Tasks, refresh after save

**Files:**
- Modify: `templates/goals.html` (insert `{% include "_task_detail_panel.html" %}` after the `#goalDetailOverlay` closing `</div>` at line 173, before `{% endblock %}`)
- Modify: `static/goals.js` — `goalRenderLinkedTasks` (350-393); `goalsInit` (48) registers the hook
- Modify: `static/style.css` — pointer cursor + `:focus-visible` outline on `.linked-task-row[role="button"]`; mobile min-height 44px
- Test: `tests/e2e/pages.spec.js` — new `test.describe("Goals - a linked task opens the task panel (#372)")` at the end of the file

**Interfaces:**
- Consumes (app.js, unchanged): `taskDetailOpen(task)`, `#detailOverlay`, `#detailTitle`, `#detailGoal`, `#detailForm`, `#detailComplete`; `loadTasks()` calls `window.taskDetailAfterSave()` on panel-only hosts.
- Produces: `async function goalsAfterTaskSave()` assigned to `window.taskDetailAfterSave` in `goalsInit`. Body: `await goalsLoad()`; if `#goalDetailOverlay` is visible and `#goalId` has a value, `goalRenderLinkedTasks(id)` and `_goalRefreshHardDeleteState(<that goal from goalsData>)`.

- [ ] **Step 1: Write the failing Playwright tests.** Fixture per test via API: a work goal (`E2E 372 goal <stamp>`) plus an active task linked to it; clean up in `finally`. Locate the row with `#linkedTasksList .linked-task-row` filtered by the task title.
  - `clicking a linked task stacks the task panel on the goal panel` — open the goal card, click the row: `#detailOverlay` visible, `#detailTitle` has the task title, `document.elementFromPoint` at `#detailPanel`'s centre is inside `#detailOverlay`; click `#detailClose`: `#detailOverlay` hidden, `#goalDetailOverlay` still visible.
  - `saving from the panel refreshes the open goal panel` — edit `#detailTitle` to a new title, submit `#detailForm`: the goal panel's linked list shows the new title with no `page.reload()`; API `GET /api/tasks/<id>` returns the new title.
  - `Enter on a focused linked row opens the panel` — `row.focus()`, press Enter → `#detailOverlay` visible; row has `role="button"` and `aria-label="Open task: <title>"`.
  - `checkbox completes without opening the panel` — click the row's checkbox: `#detailOverlay` stays hidden; API task `status === "archived"`.
  - `Space on the checkbox does not open the panel` — focus the checkbox, press Space: `#detailOverlay` hidden.
  - `re-goaling a task removes it from the open goal panel` — second goal in the fixture; in the panel set `#detailGoal` to it and save: row gone from `#linkedTasksList`, `#linkedTaskCount` decremented, API `goal_id` equals the second goal.
  - `#355: a task on an archived goal keeps its goal after a save` — archive the goal via `PATCH /api/goals/<id>` `{is_active:false}`; select `archived` in `#filterArchived`; open the goal, open the task, submit unchanged: API `goal_id` unchanged.
- [ ] **Step 2: Run** `npx playwright test tests/e2e/pages.spec.js -g "#372" --project=chromium` (gate runner manages the bypass server; for an ad-hoc run start it per CLAUDE.md and stop with `python scripts/stop_dev_bypass.py`) — Expected: FAIL (`#detailOverlay` not found).
- [ ] **Step 3: Implement.** Template include; in `goalRenderLinkedTasks` give the row the Global-Constraints affordance with `click` → `taskDetailOpen(task)` and `keydown` (Enter/Space, `e.target === row`, `preventDefault`) → same; the checkbox gets a `click` listener calling `e.stopPropagation()`. Add `goalsAfterTaskSave` and register it. CSS as listed.
- [ ] **Step 4: Run** the same command — Expected: all PASS. Then `npx playwright test tests/e2e/pages.spec.js -g "Goals" --project=chromium` — Expected: PASS (existing #343 / #349 / #368 / filter tests unaffected).
- [ ] **Step 5: Commit** `feat(#372): /goals linked tasks open the task panel`.

### Task 3: /projects — host the panel, open from card lines and the side list

**Files:**
- Modify: `templates/projects.html` (include after `#projectDetailOverlay` closing `</div>` at line 172)
- Modify: `static/projects.js` — card task `<li>` (525-560); extract `projectRenderSideTasks` from `projectDetailOpen` (705-732, the "Task summary" + side-list blocks); `onTaskTouchStart` long-press callback (1047-1058); init registers the hook
- Modify: `static/style.css` — pointer cursor + `:focus-visible` on `.project-card-task[role="button"]`, `.project-side-task[role="button"]`; side-task mobile min-height 44px
- Test: `tests/e2e/pages.spec.js` — new `test.describe("Projects - a linked task opens the task panel (#372)")`

**Interfaces:**
- Consumes: Task 1 `window.projectTaskDragHelpers.taskLineClickOpens(longPressAt, now)`; `taskDetailOpen(task)`; `_projectsTaskById(id)`.
- Produces: `function projectRenderSideTasks(projectId: string)` — fills `#projectTaskCount`, `#projectTaskPlural`, `#projectTaskSummary`, `#projectTaskList`, `#projectTaskListWrap` from `projectTaskCounts` / `projectTasksById`; `projectDetailOpen` calls it. Module-level `let _touchLongPressAt = null;` set to `Date.now()` when the 500ms timer fires; the card-line click handler keeps `e.stopPropagation()`, returns early (and resets `_touchLongPressAt = null`) when the helper says false, else `taskDetailOpen(t)`. `async function projectsAfterTaskSave()` assigned to `window.taskDetailAfterSave`: `await projectsLoad()`; if `#projectDetailOverlay` visible and `#projectId` set, `projectRenderSideTasks(id)`.

- [ ] **Step 1: Write the failing Playwright tests.** Fixture: an active work project (`E2E 372 project <stamp>`) plus an active task on it; cleanup in `finally`. Card line = `.project-card-task[data-task-id="<id>"]`; side line = `#projectTaskList .project-side-task` filtered by title.
  - `clicking a card task line opens only the task panel` — `#detailOverlay` visible with the title; `#projectDetailOverlay` hidden.
  - `a side-list task stacks on the project panel and refreshes on save` — open the card, click the side line: topmost-element check as in Task 2; rename and save: side line shows the new title without reload; close → `#projectDetailOverlay` still visible.
  - `completing from the panel refreshes the side list` — click `#detailComplete`: line gone from `#projectTaskList`, `#projectTaskCount` decremented, API `status === "archived"`.
  - `Enter on a focused card line opens the panel` — plus `role` / `aria-label` assertions.
  - `#355: a task on an archived project keeps its project after a save` — `PATCH /api/projects/<id>` `{is_active:false}`, select `archived` in `#projectFilterActive`, open the card's line, save unchanged: API `project_id` unchanged.
  - `a long-press does not open the panel; a tap does` — reuse the #344 `fire(...)` TouchEvent pattern inside `page.evaluate`: touchstart, wait 600ms, touchend, then `li.click()` → `#detailOverlay` hidden; then (after >700ms) touchstart, 120ms, touchend, `li.click()` → visible. (Synthetic TouchEvents never synthesize a click, so the test dispatches the click the browser would.)
- [ ] **Step 2: Run** `npx playwright test tests/e2e/pages.spec.js -g "#372" --project=chromium` — Expected: the new /projects tests FAIL.
- [ ] **Step 3: Implement** per Interfaces; side lines get the same affordance as card lines (no long-press guard — they are not draggable).
- [ ] **Step 4: Run** the same command — Expected: all PASS. Then `-g "#344"` and `-g "#353"` — Expected: PASS, test files for those blocks unmodified.
- [ ] **Step 5: Commit** `feat(#372): /projects task lines open the task panel`.

### Task 4: Cache bump, prod smoke, docs, backlog

**Files:**
- Modify: `static/sw.js:8` (`v263` → `v264`)
- Modify: `tests/e2e-prod/smoke.spec.js` — one test per page, read-only: on `/goals?nosw=1` open the first goal card with a linked task (skip with `test.skip` + reason if the live data has none), click the first `.linked-task-row`, assert `#detailOverlay` visible and `#detailTitle` value equals the row's title text, click `#detailClose`. Same on `/projects` with the first `.project-card-task`. Never submit.
- Modify: `templates/docs.html` — Goals and Projects sections: one line each, "Click (or tap) a linked task to open and edit it without leaving the page." Fact-check table (each claim → `file:line`) goes in the review message, not the doc.
- Modify: `CLAUDE.md` — Phase 6 step 6 (/projects) and step 7 (/goals) each gain an "open a linked task; it stacks, closes back, and a save refreshes the list" check; Regression Test Report gains `Goals: linked task opens panel` and `Projects: task line opens panel` rows (both columns).
- Modify: `ARCHITECTURE.md:457-463` — note that `/calendar`, `/goals` and `/projects` include the partial as #270 panel-only hosts refreshing via `window.taskDetailAfterSave`.
- Modify: `BACKLOG.md` — file **#375** (text from spec §5); #372 row → `🔄 IN PROGRESS — code + tests on branch, deploy pending`.

- [ ] **Step 1: Run** `python scripts/arch_sync_check.py` and `python scripts/check_no_string_match_only_tests.py` after the edits — Expected: both exit 0.
- [ ] **Step 2: Run** the `cascade-check` skill against the branch diff — Expected: every row ✅ or ⏭️ with a reason.
- [ ] **Step 3: Commit** `docs(#372): help, Phase 6 rows, architecture note, file #375; bump SW cache`.

### Task 5: Gates, Phase 6, ship

- [ ] **Step 1:** `export PYTEST_ADDOPTS='--basetemp=C:/Users/higs7/AppData/Local/Temp/claude/C--Users-higs7-OneDrive-Coding-taskmanager/<session>/scratchpad/pytest-basetemp'; bash scripts/run_all_gates.sh > <scratchpad>/gates.log 2>&1` run bare — Expected: log contains `ALL GATES GREEN`.
- [ ] **Step 2:** Phase 6 at 1280×800 and 375×812 on /goals and /projects (`python scripts/seed_dev_data.py`, `preview_start taskmanager-dev-bypass`, `?nosw=1`): every surface opens the panel, stacking + close-returns + refresh-after-save, mobile tap vs long-press, 44px rows on mobile, `scrollWidth <= innerWidth`, 0 console errors in a fresh tab. Teardown `python scripts/stop_dev_bypass.py`; `ls .env.dev-bypass` → no such file.
- [ ] **Step 3:** Merge to `main`, push (tell the user the cache bump reloads their open tab), `python scripts/validate_deploy.py --monitor-minutes 5` in the foreground with no `| tail`, then prod smoke with `TASKMANAGER_SESSION_COOKIE` exported.
- [ ] **Step 4:** Separate docs commit flipping #372 to ✅; delete the branch; print Quality Gate, Regression, Deploy Validation and SOP reports.
