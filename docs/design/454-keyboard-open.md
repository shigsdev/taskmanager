# #454 — Projects, goals, recurring templates and calendar items open by keyboard

Deep review §D1 (2026-10-11). Sibling of #295 (board cards) and #372/#377
(task lines on /projects and /goals already had this).

## What was wrong (checked in code 2026-10-15)

| Surface | Opened by | Keyboard |
|---|---|---|
| /projects card | `card` click → `projectDetailOpen` | not focusable |
| /goals card | `card` click → `goalDetailOpen` | not focusable |
| /recurring row | the row's info block click → `openEditor` | not focusable |
| /calendar task line | `li` click → `taskDetailOpen` | not focusable |
| /calendar "add on this day" | a click on a cell's empty space | no control at all |

None of the goal, project or recurring panels moved focus in or back, so
even a mouse-opened panel left keyboard focus on the page behind it.

## This ship

1. **`panelKeys.makeOpener(el, label, onOpen)`** (`static/panel_keys.js`,
   loaded on every page): `tabindex=0`, `role=button`, `aria-label`, and
   Enter / Space aimed at the element itself (not a checkbox or link inside
   it) calls `onOpen`. These are #372's `projectTaskLineAffordance` rules,
   shared. Used for project cards ("Open project: …", same as a click, so
   in Select mode it toggles), goal cards ("Open goal: …"), /recurring rows
   ("Edit template: …") and calendar task lines ("Open task: …", with the
   overdue wording #467 adds).
2. **Focus in and back** for the goal, project and /recurring panels, by the
   task panel's #377 rules: `panelKeys.opened(doc, overlay, closeBtn,
   keyAttr)` remembers what had focus (never a text field) and focuses ✕;
   `closed(doc, overlay)` hands focus back; `afterRender(doc)` finds the card
   again by `data-goal-id` / `data-project-id` / `data-template-id` when a
   save re-rendered the list and focus fell to the page, and never takes
   focus from somewhere the user moved it. The New panels remember "+ New"
   (/recurring's New keeps focusing its title). Calendar task lines get focus
   back from the task panel's existing #377 code (`data-task-id`).
3. **Calendar "+" per day**: a button in each cell's header ("Add a task on
   Thursday, Oct 15") that opens the new-task panel dated that day, the same
   path as the empty-space click (which stays). 24px on desktop, 44px at
   ≤767px (#453's floor). The header's date now wraps instead of fitting on
   one line, so "Wednesday, Oct 14" is never cut short next to the button.
4. Help: "Keyboard in panels" gains "Opening one", and the Calendar section
   mentions the "+".

## Tests

- Jest (`panel_keys.test.js`): makeOpener's role / label / Tab stop; Enter
  and Space open once and are consumed; other keys and keys aimed at a child
  don't; opened → ✕ focused; closed → focus back; afterRender finds the
  re-rendered card; never steals focus moved elsewhere; a text-field opener
  gets nothing back; a re-open keeps the first opener.
- Playwright (`keyboard_open.spec.js`, both widths): Enter on a goal card,
  Space on a project card, Enter on a /recurring row and on a calendar line,
  each with ✕ focused and focus back after Escape (and after Save on a goal);
  a day's "+" opens a new task with that due date. A click still opens a
  goal card (the quiet case). Red on the old code ×10.
- `mobile_tap_targets.spec.js`: the "+" is 44×44 at 375.
