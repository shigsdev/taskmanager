# Spec #372 — Linked tasks on /goals and /projects open the task panel

**Filed:** 2026-10-02 (user report, mid-#367)
**Status:** draft 2026-10-03, awaiting approval
**Builds on:** #270 (panel-only host pattern), #344 (project task drag),
#355 (archived link survives a save), #349 (archived goals on /goals)
**Backend changes:** none.
**Frontend:** `goals.html`, `projects.html`, `goals.js`, `projects.js`,
one small helper in `project_task_drag_helpers.js`, `sw.js` cache bump.
**Severity:** Medium. Nothing is lost, but to edit a linked task the user
has to leave the page and find it again on the board.

---

## 1. Problem

> "on the projects and goals page, when you pull it up there are linked
> tasks, however, you can't click on them to open up and manage them"
> — user, 2026-10-02

Linked tasks are listed in three places on these two pages. All three
render the task as inert text:

| # | Surface | Code | Today |
|---|---|---|---|
| A | /goals: goal panel → Linked Tasks | `static/goals.js:350-393` `goalRenderLinkedTasks` | complete-checkbox + plain `<span class="linked-task-title">` + tier badge |
| B | /projects: task lines on each card | `static/projects.js:525-560` | plain `<li>`; click only `stopPropagation()`s (so the card panel doesn't open); draggable since #344 |
| C | /projects: project panel → task list | `static/projects.js:715-732` | plain `<li class="project-side-task">`, no handlers |

The cause is structural, not a missing handler. The task detail panel
markup (`templates/_task_detail_panel.html`, container `#detailOverlay`)
is `{% include %}`d into `index.html`, `tier.html`, `completed.html` and
`calendar.html` only. `goals.html` and `projects.html` already load
`app.js` and `task_detail_payload.js` (the panel's *logic*), but without
the markup `taskDetailOpen()` (`static/app.js:2518`) would throw on its
first `getElementById`.

## 2. Goal

- Clicking (or tapping, or Enter/Space on) any linked task line on
  surfaces A, B and C opens the full task detail panel **in place**.
- On A and C the task panel **stacks on top of** the goal/project panel
  (user decision 2026-10-03). Closing it returns to that panel.
- Saving, completing, cancelling or deleting from the task panel
  refreshes the page **and** the still-open goal/project panel, so the
  edit is visible without a reload.
- #344's drag on surface B keeps working at both viewports. A tap opens;
  a long-press drag does not.
- #355: a task linked to an **archived** goal (shown on /goals under the
  Archived filter) or archived project keeps that link when saved from
  the panel.

## 3. Correction to the scope question

The user picked "all linked tasks openable, including completed". On
inspection, **completed tasks never appear in these lists today.** Both
pages fetch `GET /api/tasks` with no `status` param (`goals.js:70`,
`projects.js:63`), and the server defaults that to `status=active`
(`tasks_api.py:64-72`). The `status === "archived"` styling branches in
A and B are dead code.

So in this ship, "all" means every line the lists render. That is every
active task, with no type or tier exclusions. Making completed tasks
appear is a separate change filed as **#375** (below), along with the
bug it causes.

## 4. Design

### 4.1 Host the panel (templates)

Add `{% include "_task_detail_panel.html" %}` to `goals.html` and
`projects.html`, placed **after** the page's own overlay
(`#goalDetailOverlay` at `goals.html:72`, `#projectDetailOverlay` at
`projects.html:67`). Both overlays use `.detail-overlay`
(`style.css:1439`, `z-index: 200`). At equal z-index, later DOM order
paints on top, so the task panel stacks over the goal/project panel with
no CSS change. A Playwright assertion checks this (topmost element at
the panel's centre), so a future reorder can't silently flip it.

Nothing else in `app.js` changes. `init()` (`app.js:228-262`) already
detects a page that has `#detailOverlay` but no tier board. It takes the
#270 **panel-only** branch: it preloads `allTasks`, loads goals and
projects, and runs `setupDetailPanel()`. /calendar has used this branch
since #270.

Backdrop clicks are already scoped: each overlay closes only when
`e.target === e.currentTarget` (`app.js:2320`, `goals.js:288`).
Clicking the dimmed area around the task panel therefore closes only the
task panel.

### 4.2 Refresh after a mutation

Every panel mutation (save, complete, cancel, delete, subtask edit) goes
through `loadTasks()`. On a panel-only host, `loadTasks()` hands off to
`window.taskDetailAfterSave` (`app.js:119-131`). Each page registers its
own:

- **goals.js:** `await goalsLoad()`, then if the goal panel is open,
  `goalRenderLinkedTasks(<open goal id>)`. `goalsLoad()` already
  re-renders the cards and the server-computed progress bars.
- **projects.js:** `await projectsLoad()` (re-renders the cards and
  counts), then if the project panel is open, re-render its task list.
  The side-list block in `projectDetailOpen` is pulled out into
  `projectRenderSideTasks(projectId)` so the panel's other fields aren't
  reset under the user.

### 4.3 Make the lines open the panel

One shared shape on all three surfaces:

- The row gets `tabindex="0"`, `role="button"`, an `aria-label` of
  `Open task: <title>`, and a pointer cursor.
- Click, or Enter/Space on the row, calls `taskDetailOpen(task)`. The
  `task` object is the full API row the page already holds (same
  serializer as the board), so no extra fetch is needed.
- **A (goals):** the whole row opens the panel, except the
  complete-checkbox. The checkbox gets `stopPropagation()` so ticking it
  still just completes the task, as today.
- **B (project cards):** the existing click handler keeps its
  `stopPropagation()`, so the project panel doesn't also open, and now
  opens the task panel too.
  - **Mouse drag:** browsers don't fire a click after a native HTML5
    drag, so nothing changes there.
  - **Touch:** a quick tap fires a click and opens the panel. The risk is
    a long-press: once the 500ms timer fires (`projects.js:1047`),
    releasing without moving can still produce a click. The fix is to
    record when the long-press fired and swallow the next click on that
    line if it lands within 700ms.
  - That decision is a pure helper,
    `taskLineClickOpens(longPressAt, now)` in
    `project_task_drag_helpers.js`, which already has the dual-export
    pattern. It gets a Jest test, per CLAUDE.md anti-pattern #3.
- **C (project panel list):** the row opens the panel, stacked on top.

### 4.4 #355 archived links

No new code. This is a test-only guarantee. `taskDetailOpen` already
passes `task.goal_id` / `task.project_id` as `currentId` to the populate
functions, so an archived goal or project stays in the dropdown and
round-trips on save. #372 creates the **first** route into the panel
from a page that *lists* archived goals and projects, so the guarantee
needs asserting here.

### 4.5 Cache

`static/sw.js` `CACHE_VERSION` v263 → v264. No new static files, so
`APP_SHELL` and `EXPECTED_STATIC_FILES` are unchanged.

## 5. Out of scope (filed, not built)

- **#375 (new):** /goals and /projects fetch active tasks only. As a
  result:
  - completed tasks never appear in the lists;
  - the "done" styling is dead code;
  - the /projects card label "N active / M total" always shows two equal
    numbers.

  The fix is `?status=all` or a separate count source, plus deciding
  where completed tasks sit in each list.
- Creating a new linked task from the project panel. /goals has an
  add-linked-task input; /projects does not. Not requested.

## 6. Tests

**Jest:** `taskLineClickOpens` covers no long-press, a click inside
the window, a click outside the window, and a null timestamp.

**Playwright (local, `tests/e2e/pages.spec.js`):**
1. /goals: open a goal and click a linked task. The task panel is
   visible and is the topmost element (stacked). Close it and the goal
   panel is still open.
2. /goals: edit the title and save. The linked-task list in the
   still-open goal panel shows the new title without a reload.
3. /goals: focus a linked row and press Enter. The panel opens.
4. /goals, #355: a task on an archived goal (Archived filter), saved
   unchanged, still has the same `goal_id` (checked via API).
5. /projects: click a card task line. The task panel opens and the
   project panel does **not**.
6. /projects: open the project panel and click a side-list task. It
   stacks on top. Save, and the side list refreshes.
7. /projects, #355: a task on an archived project keeps its `project_id`
   after saving.
8. /projects: a touch long-press then release does not open the panel,
   and a tap does. Uses a `hasTouch` context.
9. The existing #344 drag tests still pass unchanged (mouse drag still
   moves a task).

**Prod smoke (`tests/e2e-prod/smoke.spec.js`):** on /goals and
/projects, clicking a linked task opens `#detailOverlay` with that
task's title in `#detailTitle`. The test is read-only: it opens and
closes the panel and never saves.

**Phase 6** at 1280×800 and 375×812, on both pages:
- every surface opens the panel;
- stacking, close-returns, and refresh-after-save behave as in §2;
- mobile tap vs long-press;
- 44px row height on mobile;
- `scrollWidth ≤ innerWidth`;
- 0 console errors.

## 7. Docs / cascade

- `templates/docs.html` (Help): the Goals and Projects sections gain a
  "click a linked task to open it" line, with a fact-check table in the
  review message.
- `CLAUDE.md` Phase 6 checklist: steps 6 and 7 gain an "open a linked
  task" check, and the Regression Test Report template gets the
  matching rows.
- `ARCHITECTURE.md`: no new routes, jobs or columns. One line in the
  #270 panel-host note adding /goals and /projects as panel-only hosts.
- `BACKLOG.md`: file #375. Flip #372 only after prod smoke passes.
