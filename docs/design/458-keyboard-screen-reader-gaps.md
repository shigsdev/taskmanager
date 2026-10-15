# #458 — Remaining keyboard / screen-reader gaps

Deep review §D5 (2026-10-11). Checked 2026-10-15 against the live dev pages
and the code (the review's line numbers had drifted).

## What was wrong

1. **Quick-action buttons you can't see.** Each board card's quick actions
   (`.task-quick-actions`: Today, Tomorrow, Week, Backlog, …) are real
   buttons, so Tab reaches them, but they sit at `opacity: 0` until the
   mouse hovers the card. A keyboard user tabs into buttons that aren't
   visible.
2. **Parent picker is mouse-only.** The task panel's "Parent task" typeahead
   (`_setupParentPicker`, `app.js`) lists matches as plain `<div>`s with
   click handlers. ↓ / ↑ / Enter do nothing, and a screen reader isn't told
   a list appeared. Escape closes the whole panel, not just the list.
3. **Staged bulk chips are mouse-only.** The board's "Staged changes" chips
   (`renderBulkPending`) are `<span>`s you click to remove. They can't be
   focused or announced as buttons.
4. **Controls with no name.** A load-time scan of 19 pages found three
   unnamed kinds: the Inbox triage checkbox on every Inbox card, the
   select checkbox on every /recurring row, and the goal select on every
   /utilities project row. Several more fields are named only by their
   placeholder (capture box, search, subtask, linked-task, the import
   textareas, the reflection box, the Focus slots). The panel's checklist
   and subtask checkboxes, the goal panel's linked-task checkboxes, the
   /projects bulk checkboxes, the Pick-a-date input and the Focus goal
   selects are also unnamed or named only by a `title`.
5. **Dialogs aren't announced as modal.** The task, goal, project and
   /recurring panels have no `role=dialog`. The ✨ Plan review,
   💡 Auto-categorize review, reflection Focus dialog and voice-memo
   "Make recurring" dialog have the role but no `aria-modal`. The Strength
   Forge pop-up has neither. Only the Recycle Bin confirm was complete.
   (The panels already trap Tab since #381, so they are modal in behaviour;
   now they also say so.)
6. **No skip link.** Every page makes a keyboard user tab through the whole
   nav before the content.
7. **Tabs without state.** The Focus panel's This Week / Next Week and
   /reflection's Type / Record have `role=tab` but no `aria-selected`, so a
   screen reader can't tell which one is showing.

## This ship

- `style.css`: `.task-quick-actions:focus-within` and a keyboard-focused
  card show the quick actions (opacity 1), as hover does.
- `menu_helpers.js` gains `comboKey(count, current, key, open)`, the pure
  key rule for a typeahead list: ↓ / ↑ move (wrapping, via
  `menuKeyTarget`), Enter picks the highlighted match, Escape closes an
  open list. The parent picker uses it: the input is a `combobox`
  (`aria-expanded`, `aria-controls`, `aria-activedescendant`), the list a
  `listbox` of `option`s, the highlighted row shaded. Enter picks without
  saving the form; Escape with the list open closes only the list (a
  second Escape closes the panel). A click still picks.
- Staged chips become `<button type="button">`s named "Remove staged
  change: <label>: <value>". They look the same.
- Every control in point 4 gets an `aria-label` that names its row where
  there is one ("Select “<title>” for triage", "Complete “<title>”").
- `role="dialog" aria-modal="true" aria-labelledby=<its heading>` on the
  four panels; `aria-modal="true"` on the four dialogs that had the role;
  role, `aria-modal` and a name on the Strength Forge pop-up.
- `base.html`: a "Skip to main content" link, first in the page, shown only
  when focused; `<main id="main" tabindex="-1">` takes the focus.
- `aria-selected` on both tab pairs, kept in step with the `active` class.

## Tests

- Jest `menu_helpers.test.js`: `comboKey` (move, wrap, pick, close, nothing
  when the list is closed or empty).
- Playwright `a11y_gaps.spec.js` (desktop and mobile projects):
  - every control on the 19 pages has a name (aria-label, labelledby,
    label, text, title) at load — placeholder alone doesn't count. This is
    the guard against the next unnamed control.
  - Tab onto a card's quick action → its row is visible (opacity 1).
  - Parent picker: type, ↓ highlights a match, Enter picks it (chip shows,
    panel still open, nothing saved); Escape closes the list only, then the
    panel.
  - A staged chip is a button; Enter on it removes the change.
  - Each panel / dialog has `role=dialog`, `aria-modal=true` and a name.
  - First Tab on a page focuses the skip link; Enter puts focus on main.
  - `aria-selected` follows the Focus tabs and the reflection tabs.

## Not in this ship

- **#489** — the review screens' rows (import, /scan, voice memo, /plan,
  💡 Auto-categorize, /reflection review, Strength Forge log form) build
  ~45 controls in JS with no name. They only exist after an upload or a
  parse, so the load-time guard can't see them; each screen needs its own
  stubbed state. Filed as its own row, with extending the guard to those
  states.
- Deep review §D6 (Weekly Focus re-renders on blur, arrow keys on the goal
  select) — rechecked 2026-10-15: Tab out of a slot keeps focus on the goal
  select and ↓ picks a goal without losing focus. Fixed by #441; nothing
  to file.
