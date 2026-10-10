# Spec #381 — Escape closes the top panel; Tab stays inside it

Status: building (2026-10-10). User chose "All 4 side panels".

## 1. Surface

Escape does nothing on any panel today. The only Escape handlers in the app
are `static/strength_forge.js` (its own modals) and the native
`<dialog>` on /architecture (#405). And while a panel is open, Tab walks
out into the page behind the backdrop.

**The four side panels** all share one shape: a `.detail-overlay` (z-index
200, `display:none` when closed), a `.detail-header` with a ✕ button, a
backdrop click that closes, and their own close function.

| Panel | Pages | ✕ / close fn | Focus today |
|---|---|---|---|
| Task `#detailOverlay` (`_task_detail_panel.html`) | board, /tier, /completed, /calendar, /goals, /projects | `#detailClose` → `taskDetailClose` (app.js:2738) | #377: in to ✕ on open, back to the opener on close |
| Goal `#goalDetailOverlay` | /goals | `#goalDetailClose` → `goalDetailClose` (goals.js:357) | none (goal cards aren't focusable) |
| Project `#projectDetailOverlay` | /projects | `#projectDetailClose` → `projectDetailClose` (projects.js:856) | none (project cards aren't focusable) |
| Recurring edit `#recurEditOverlay` | /recurring | `#recurEditClose` → `closeEditor` (recurring.js:378) | none |

**Stacking (#372):** on /goals and /projects the task panel opens on top of
the goal/project panel. Every `.detail-overlay` shares z-index 200, and the
task panel's include comes later in the DOM (goals.html:179 after :72,
projects.html:178 after :67), so the later visible one is the top one.

**Other modals:** these are different markup, so they're out of scope here
and filed as a new row (§5). They are /recycle-bin's purge confirm
`#recycleModalOverlay`, /reflection's `#reflFocusModal` and
`#weeklyFocusPlanModal`, the board's `#autoCategorizeModal`, and the voice
memo repeat picker `.voice-recur-overlay`.

**No conflicts:** the only other `keydown` listeners are Enter handlers
on single inputs (capture bar, subtask, linked task, the #372 rows,
weekly focus). Inside the panel, a native `<select>` or date picker
swallows its own Escape. `confirm()` blocks the page. The pages with their
own Escape handling (/strength-forge, /architecture's diagram dialog) have
no `.detail-overlay`, so one Escape can never close both.

## 2. Behaviour (this ship: all four `.detail-overlay` panels)

- **Escape closes the top-most open panel only**, exactly as its ✕ does.
  On /goals or /projects with the task panel stacked on top, the first
  Escape closes the task panel (#377 focus goes back to the row), and a
  second closes the goal/project panel.
  - Escape = ✕ means **unsaved edits are discarded**, just as ✕ and a
    backdrop click do today. No panel tracks unsaved edits; adding that
    would be a separate change.
  - Ignored when another handler already took it (`defaultPrevented`),
    during IME composition (`isComposing`), or with no panel open.
- **Tab / Shift+Tab cycle inside the top-most open panel.** Tab from the
  last focusable control goes to the first; Shift+Tab from the first goes
  to the last. If focus is outside the panel (for example still on the
  card behind a goal panel opened by mouse), Tab goes to the panel's first
  control and Shift+Tab to its last. Hidden controls (collapsed repeat
  pickers, `display:none` sections) and disabled ones are skipped.
- **Unchanged:** what each panel focuses on open (only the task panel
  moves focus in, #377), mouse and touch behaviour, the backdrop click,
  and pages with no panel open.

## 3. Implementation

- New dual-export `static/panel_keys.js` (IIFE, `window.panelKeys` /
  `module.exports`, #359-safe):
  - `topOverlay(overlays)`: pure. Of the visible entries, the last in DOM
    order, or null.
  - `trapTarget(focusables, current, shift)`: pure. Which element Tab /
    Shift+Tab should move to, or null to let the browser do it (a move
    strictly inside the list).
  - `attachPanelKeys(doc)`: one `keydown` listener on `document`. It finds
    the open `.detail-overlay`s, takes the top one, and on Escape clicks its
    `[data-panel-close]` button, which runs that panel's own close path,
    #377 focus return included. On Tab it applies `trapTarget` and calls
    `preventDefault` only when it moves focus itself.
- The 4 ✕ buttons gain `data-panel-close` (task, goal, project and
  recurring templates).
- Loaded once from `base.html`. It's a no-op on pages without a
  `.detail-overlay`.
- Cascade: `sw.js` APP_SHELL + `CACHE_VERSION`, `health.py`
  `EXPECTED_STATIC_FILES`, and a line in ARCHITECTURE.md (UI conventions).
  Help (`templates/docs.html`) gets one keyboard line, with a fact-check
  table.

## 4. Tests

- Jest `tests/js/unit/panel_keys.test.js` (jsdom): `topOverlay`
  (none, one, two stacked → the later one); `trapTarget` (wrap at both
  ends, outside → first/last, middle → null, empty list); the attached
  listener (Escape clicks only the top ✕; ignored when defaultPrevented,
  composing, or nothing is open; Tab wraps; hidden and disabled controls
  skipped).
- Playwright, desktop + mobile projects:
  - board: open a task, Escape closes it.
  - /goals: open a goal, open a linked task (stacked). Escape closes only
    the task panel and focus is back on the row; Escape again closes the
    goal panel.
  - /projects: the same with a project and a side-list task.
  - Tab from the task panel's last control wraps to ✕, and Shift+Tab from
    ✕ wraps to the last control.
  - /recurring: Escape closes the editor.
- CLAUDE.md Phase 6: steps 6/7 and /recurring gain the Escape and Tab
  checks, plus report rows.

## 5. Out of scope, filed as a new row

Escape and a focus trap for the five non-`.detail-overlay` modals listed in
§1. Each has its own markup and close semantics: the recycle purge confirm
is type-to-confirm, and the reflection modals carry in-progress state.
