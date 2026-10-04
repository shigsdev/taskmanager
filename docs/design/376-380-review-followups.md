# Spec #376–#380 — #372 review follow-ups

**Filed:** 2026-10-03 (deferred minors from #372's final whole-branch review)
**Status:** approved 2026-10-03 ("Approved")
**Shape:** five rows, five ships, in the order below. Each ship gets its
own branch, full gates, Phase 6 where the UI changes, deploy validation
and prod smoke.
**Backend changes:** none in any of the five.

---

## Ship order and why

| Order | Row | Size | Touches | CACHE bump |
|---|---|---|---|---|
| 1 | #380 tap-height breakpoint | XS, CSS | `style.css` | v264 → v265 |
| 2 | #378 two missing tests | S, tests only | `pages.spec.js` | none |
| 3 | #376 long-press guard from release | XS | `projects.js` | v265 → v266 |
| 4 | #379 superseded refresh can paint old data | S | `goals.js`, `projects.js` | v266 → v267 |
| 5 | #377 panel keyboard focus | M | `app.js`, `goals.js`, `projects.js` | v267 → v268 |

Smallest and most independent first. #377 goes last because it changes
`app.js` `loadTasks()` (shared by every page), and the earlier ships
should not have to be re-verified against that change.

---

## 1. #380 — the 44px rule uses two breakpoints on the #372 rows

**Surface (mapped):** the touch-target `min-height: 44px` rules in
`static/style.css` sit under three different breakpoints:
- **600px:** the app-wide mobile block (buttons, nav, task cards, panel
  selects).
- **700px:** `.reopen-dropdown`, `.parent-picker-clear`, and #372's
  `.linked-task-row[role="button"]` (~2495).
- **767px:** #344's card lines, #343's goal-card project chips and
  toggle, and #372's `.project-side-task[role="button"]`.

**This ship:** move `.linked-task-row[role="button"] { min-height: 44px }`
into a `@media (max-width: 767px)` block. That matches its neighbours on
the same two pages (the #343 and #344 rules, and the side list).
- **Test (Playwright):** at a 740×900 viewport, a /goals linked row is
  ≥ 44px tall. RED today: 740 is above 700.
- No docs change. Not user-facing copy.

**Out of scope, filed as #382:** the app-wide spread of touch-target
rules across 600/700/767px. Unifying it would touch every page.

## 2. #378 — two #372 behaviours have no direct test

Test-only. These tests describe behaviour that already works, so they
pass on first run. Each is proven by a **mutation check**: break the
code on purpose, watch the test go red, restore. That stands in for TDD's
RED step on a test-only row.

1. **A real pointer drag never opens the panel.** The test drags a
   /projects card task line onto another work project's card with
   Playwright's real mouse (`locator.dragTo`). It asserts that
   `#detailOverlay` stays hidden.
   - If Chromium's real-mouse HTML5 drag also moves the task, the test
     asserts the saved `project_id` too.
   - If it doesn't (#344's notes say `page.dragAndDrop` doesn't trigger
     this app's `dragstart`), the test still proves the important half:
     a press–move–release gesture produces no panel. The test comment
     will say which case it is.
   - **Mutation:** make the card-line click handler ignore the guard
     and also open on `mouseup`. The test should go red.
2. **The goal panel's hard-delete button re-enables after the last task
   moves away.** Setup: an archived goal A with one active task, and an
   active goal B.
   - Filter Archived, open A: `#goalHardDelete` is disabled.
   - Open the task, set its goal to B, save. `#goalHardDelete` becomes
     enabled, with no stale "still point at this goal" hint.
   - **Mutation:** remove the `_goalRefreshHardDeleteState` call from
     `goalsAfterTaskSave`. The test should go red.

## 3. #376 — the long-press guard should run from release

**Surface:** `static/projects.js`.
- `onTaskTouchStart` stamps `_touchLongPressAt` when the 500ms timer
  fires.
- `onProjectsTouchEnd` ends the drag and doesn't touch the stamp.
- The guard is `taskLineClickOpens(_touchLongPressAt, now)`, with 700ms
  in `project_task_drag_helpers.js`.

**This ship:** in `onProjectsTouchEnd`, when a drag was live
(`_touchDrag` was set), stamp `_touchLongPressAt = Date.now()` again. The
700ms window then starts when the finger lifts. A long-press that never
became a drag needs nothing: the timer never fired, so there's no stamp.
- The helper is unchanged, so its Jest tests are too.
- **Test (Playwright, extends #372's long-press test):** touchstart, hold
  600ms (drag starts), hold still 900ms more, touchend, `li.click()`.
  `#detailOverlay` stays hidden. RED today: the click lands about 1000ms
  after the stamp.

## 4. #379 — a superseded refresh can paint older data

**Surface:** `goalsLoad()` (`goals.js`) and `projectsLoad()`
(`projects.js`). Each awaits fetches, then writes module state and
re-renders.
- Since #372, both pages refresh from two triggers: the post-save hook,
  and app.js's 60s poll, tab-visible and cross-tab refreshes.
- If two loads overlap, the one that finishes last wins, even when it
  carries the older response.
- **Correction to the row:** /calendar does NOT have this race. #219
  added a generation guard to `renderCalendar` (`calendar.js:62-72`,
  `:225`). That guard is the pattern this ship reuses.

**This ship:** the same generation guard in `goalsLoad` and
`projectsLoad`.
- Bump a module counter on entry.
- Fetch everything into locals; `goalsLoad` currently assigns
  `goalsData` before its second await, so that moves too.
- After the awaits, return without touching state if a newer load has
  started.
- New names: `_goalsLoadGeneration` and `_projectsLoadGeneration`. Both
  are checked for collisions with app.js globals.
- **Test (Playwright, both pages):**
  1. Route-delay the FIRST `GET /api/tasks` by about 1.5s. It is fetched
     before the rename, so it carries the old title.
  2. Call the hook, rename the task via the API, then call the hook
     again; the second fetch is undelayed.
  3. After both settle, the row shows the NEW title.
  RED today: the slow, old response paints last.

## 5. #377 — keyboard focus into the task panel and back

**Surface (`static/app.js`):**
- `taskDetailOpen` never moves focus. `taskDetailOpenNew` focuses the
  title, which is create-mode only.
- `taskDetailClose` never restores focus.
- Close is called from several places: ✕, the backdrop, after save
  (`await loadTasks()` then close), Complete / Cancel (close BEFORE the
  async op), delete, and duplicate.
- `loadTasks()` calls `window.taskDetailAfterSave()` without awaiting
  it. So on /goals and /projects the list re-renders after the panel has
  closed, and replaces the row that would get focus back.
- Openers that can take focus today: #372's rows on /goals and /projects
  (`tabindex="0"`). Board task cards can't take focus (#295), so this
  ship changes nothing on the board, by design.

**This ship:**
- **On open** (only when the panel was closed, so the duplicate-reopen
  path doesn't lose its target): remember the element that had focus,
  if it can take focus, plus its task id and the id of its nearest
  container with an `id` (for example `linkedTasksList` or
  `projectTaskList`). Then focus `#detailClose`.
  - Why ✕ rather than the title: focusing a text field pops the phone
    keyboard on every tap-open.
  - A script-moved focus shows no focus ring after a mouse or tap open,
    only after a keyboard one (`:focus-visible`).
  - `taskDetailOpenNew` keeps focusing the title.
- **On close:** if the remembered element is still on the page, focus
  it. If it isn't, keep the target pending.
- **`loadTasks()` awaits `window.taskDetailAfterSave()`**, then retries a
  pending restore by finding `[data-task-id="<id>"]` inside the
  remembered container.
  - For that, /goals linked rows and /projects side lines gain
    `data-task-id`. Card lines already have it.
  - If no such row exists (a completed task leaves the active-only list),
    focus is not forced anywhere. The pending target clears after one
    retry.
- No change to the board, /calendar or /completed beyond the `await`.
  Their openers aren't focusable, so nothing is remembered.
- **Tests (Playwright):**
  - /goals: Enter on a linked row moves focus inside `#detailPanel`;
    ✕ returns focus to that row. After a save, focus lands on the
    re-rendered row with the same task id.
  - /projects: the same on a card line.
  - Regression: a mouse-click open on the board still works, with no
    error from the restore path. A pure Jest helper isn't worth it; the
    logic is DOM lookups.
- **Docs:** none user-facing (no Help copy describes focus).
  `ARCHITECTURE.md`'s panel-host note says `loadTasks` now awaits the
  hook. CLAUDE.md Phase 6 step 6/7 gain "keyboard-open, close → focus
  returns".

**Out of scope, filed as #381:** an Escape key to close the task panel,
and a focus trap while it's open. Today Tab can walk behind the overlay.
That changes keyboard behaviour on every page, so it gets its own spec.

## 6. New rows this spec files

- **#381** — Task panel has no Escape-to-close and no focus trap
  (board-wide keyboard behaviour). From #377's scope line.
- **#382** — Touch-target 44px rules are spread across
  600/700/767px breakpoints app-wide. From #380's sweep.
- Nothing filed for /calendar: #379's suspected race was checked and
  already has a guard (#219).
