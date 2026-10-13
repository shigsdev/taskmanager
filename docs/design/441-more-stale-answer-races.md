# #441 — More stale-answer races (siblings of #418 / #421)

Deep review 2026-10-11 §B7. Same class as #418: code waits for the server,
then writes into a screen that may no longer be showing what it asked about.

## Surface (mapped 2026-10-12)

| # | Where | What goes wrong today |
|---|---|---|
| A1 | `static/weekly_focus.js` `saveSlot` / `clearSlot` | A save started on This Week lands after the user switched to Next Week: `state = fresh; render()` paints this week's slots under the Next Week tab. ✨ Plan week then plans next week with this week's text. |
| A2 | `loadFocus` | Two quick tab clicks: whichever GET answers last wins, so the This Week tab can show next week. While a tab's GET is in flight the old week's slots are still on screen and editable, but `currentWeekOffset` already points at the new week, so a blur saves the old week's text into the new week. A failed switch leaves the old tab highlighted over the "Couldn't load next week's focus" message. |
| A3 | `render()` after every save | Rebuilds all slots. Typing in slot 2 while slot 1's save answers loses what was typed and focus. An edit made while the same slot's save is in flight is skipped (`_saveInflight`) and then painted over. Every blur PATCHes even when nothing changed. |
| B1 | `static/app.js` `taskDetailLoadSubtasks` | Task A's subtask list answers after task B opened: A's subtasks render in B's panel (ticking one completes A's subtask). Two quick ticks start two loads, each clears before its await and appends after, so every row shows twice. A tick's follow-up reload runs `taskDetailLoadSubtasks(A)` even if B is open now. |
| B2 | `taskDetailPopulateParentLink` | The fallback fetch for a non-active parent answers after another task opened: the wrong parent link renders. |
| C1 | `static/goals.js` linked-task checkbox + `goalAddLinkedTask` | After `await goalsLoad()` they call `goalRenderLinkedTasks(goalA)` even if goal B is open now: A's tasks paint into B's panel. |
| D1 | `static/app.js` `_openPreviewTemplate` | Click a recurring preview card (fetches every task), open another task meanwhile: the late answer calls `taskDetailOpen(spawn)` and replaces the open panel, unsaved edits and all. Two preview clicks: the slower answer wins. |

Already safe (checked, no change): `projectsAfterTaskSave` and
`goalsAfterTaskSave` re-read the open id after their await;
`_goalRefreshHardDeleteState` checks `goalId` before painting; the
Completed (N) sections are rebuilt per render, so a late load fills a
detached element.

## Fix

- **Weekly Focus**
  - `loadFocus` takes a request guard (#418's `createRequestGuard`): only
    the last tab asked for renders. The tab highlight follows what is
    drawn, the loaded week or the failure message.
  - New `shownWeekOffset`: the week the slots on screen belong to. Save,
    clear and both ✨ Plan buttons use it, not the tab just clicked. An
    edit made while the next week is loading saves to the week it was
    typed in.
  - A save/clear answer only updates the screen if the same week's slots
    are still the ones showing (a `viewSeq` bumped on every week load).
  - `render()` updates the slots in place when the same week is already
    drawn. It never overwrites an input that has focus or that the user
    changed since the last paint, and never replaces the nodes (focus and
    caret survive). A week change still rebuilds.
  - An edit made while that slot's save is in flight is saved right after
    it, not dropped. A blur with no change sends nothing.
  - Pure decisions in new `static/weekly_focus_helpers.js`:
    `slotInputValue` (what the input should show after an answer) and
    `slotNeedsSave` (whether a blur has anything to send). Jest-tested.
- **Task panel**: `taskDetailOpen` / `taskDetailClose` cancel the subtask
  and parent-link guards. `taskDetailLoadSubtasks` does nothing if the
  panel no longer shows that parent, clears the list after its await (not
  before), and draws only if its answer is still current.
  `taskDetailPopulateParentLink` the same.
- **Goal panel**: `goalRenderLinkedTasks(id)` draws only if the open goal
  is `id`. One check covers every caller.
- **Recurring preview**: a guard per click, plus a count of panel opens.
  The answer opens the spawn (or shows the "hasn't spawned" alert) only
  if no newer preview click and no other panel open happened meanwhile.
- `request_guard_helpers.js` moves to `base.html` (app.js runs on every
  page that has the task panel). It is no longer loaded twice on `/` and
  `/import`.

## Not in scope

- The server replacing the carried-forward (fallback) slots on the first
  save of a new week. That is how the server already behaves; this ship
  doesn't change it.
- The #421 Auto-categorize race (its own row).

## Tests

- Jest `tests/js/unit/weekly_focus_helpers.test.js`.
- Playwright (`tests/e2e/pages.spec.js`, "#441"), each red on the old code:
  1. A save held while switching to Next Week: Next Week's slots stay.
  2. Two quick tab clicks, the first answer held: the second tab's week shows.
  3. Typing in slot 2 while slot 1's save answers: the text and focus stay.
  4. Task A's subtask load held, open B: A's subtasks never show in B.
  5. Goal A's tick held, open goal B: B's linked list is B's.
  6. Preview click held, open another task: the panel keeps that task.
