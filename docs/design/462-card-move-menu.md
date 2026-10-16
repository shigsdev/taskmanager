# #462 — Board card quick actions covered the title

Filed 2026-10-11 during #427's Phase 6. Checked 2026-10-15 on the seeded
board at 1280×800.

## What was wrong

Above 600px wide, `.task-card .task-quick-actions` (the "Today / Tomorrow /
This Week / Next Week / Backlog / Freezer / + Subtask" buttons) was
`position: absolute; top: 6px; right: 44px; max-width: 60%`, `opacity: 0`
until the card was hovered — on top of the title line (#278 took it out of
the flow so it stopped squeezing the title).

- Measured: the bar is 314–423px wide. On 7 of 26 seeded cards it covered
  title text, and on 5 the badge line too — worst in the 591px Backlog /
  Freezer columns. A click aimed at the title (the mouse is hovering, so
  the bar has faded in) moved the task instead of opening it — twice in
  #426 / #427's Phase 6.
- It stayed clickable while invisible (`opacity: 0`, no
  `pointer-events: none`).
- On a touch screen wider than 600px (iPad) nothing hovers, so the buttons
  were never shown but were still tappable over the title.

Moving the bar elsewhere inside the card doesn't help: the badge line is
covered too, and a 591px card has no free strip 400px wide.

## The decision (user, 2026-10-15)

Asked with three options (Move ▾ menu / own row on every card / keep the
hover bar but slower). **Chosen: a "Move ▾" button.** Above 600px every
board card shows a small always-visible "Move ▾" button left of the ✓. It
opens a menu with the same choices the bar had (every section except the
card's own and Inbox, then "+ Subtask" on a task that isn't a subtask).
Moving a task by card takes two clicks instead of one; nothing ever covers
the title. Same shape as the completed cards' "Re-open ▾".

At 600px and below nothing changes: the buttons stay as their own visible
row under the title (#281).

## This ship

- `static/app.js` `taskCardCreate`: the quick actions are one list of
  `{label, title, className, run}`; the mobile row and the Move ▾ menu are
  both drawn from it, so they can't drift.
- The menu is appended to `<body>`, `position: fixed`, placed by
  `menuHelpers.placeMenu` (below the button, above when it doesn't fit).
  It can't live inside the card: each `.tier` runs the `scFadeUp`
  animation with `fill-mode: both`, which leaves a transform on the tier —
  a fixed child would be placed relative to the tier, and the next tier
  would paint over it.
- `menuHelpers.attachMenu(anchor, menu, {tabFromOpener: true})` — new
  option: Tab out of a menu that isn't next to its opener in the page puts
  focus back on the opener first, so Tab lands on the control after
  Move ▾ (the ✓), not at the end of the page. Shift+Tab, the control
  before it.
- Escape, an outside click, a scroll or a resize closes the menu. Opening
  it again toggles it shut.
- `static/style.css`: the bar's absolute / opacity / hover rules go. The
  row is `display: none` above 600px; the Move ▾ button is
  `display: none` at 600px and below.

## Tests

- Jest `menu_helpers.test.js`: `tabFromOpener` focuses the opener on Tab;
  without it, Tab still doesn't (the quiet case).
- Playwright `tests/e2e/card_move_menu.spec.js`:
  - at 1280 a click at the title's centre opens the task panel (red on the
    old code: it hit the "Today" button);
  - no quick-action button is on screen or hit-testable above 600px;
  - Move ▾ → Freezer moves the card; the menu lists the right sections and
    + Subtask; Escape returns focus to Move ▾; Tab from an item lands on ✓;
  - on a touch screen at 820px, Move ▾ shows and works;
  - at 375 the row is still visible under the title and Move ▾ isn't (the
    quiet case).
- Updated: `pages.spec.js` #430 quick-button test goes through Move ▾ at
  desktop; `a11y_gaps.spec.js` #458 "Tab onto a quick action" becomes
  "Tab reaches Move ▾"; prod smoke #278 asserts Move ▾ instead of an
  absolute bar.

## Not in this ship

Nothing new found.
