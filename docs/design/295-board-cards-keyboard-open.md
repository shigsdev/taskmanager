# #295 — Board task cards open from the keyboard

Carved out of #294 (2026-06-22).

## What was wrong

A task card (`taskCardEl` in `static/app.js`) opened its panel only on a
click. The card is a plain `<div>`, so a keyboard user could reach its ✓,
Move ▾ and quick buttons (#458), but nothing that opens the task. The same
was true of the completed and cancelled cards on `/completed` and the board's
Completed / Cancelled sections. The calendar's task lines, the `/goals` and
`/projects` rows and cards, and `/recurring`'s rows already open by keyboard
(#372, #454).

## Decisions

1. **The title is the button, not the card.** The card holds its own ✓,
   Move ▾, quick buttons and checkboxes, and a button wrapped around buttons
   is invalid and reads badly to a screen reader. The title is the card's
   name, and on desktop it's the part you click (#462). `#454`'s
   `panelKeys.makeOpener` gives it a Tab stop, `role="button"`,
   `aria-label="Open task: <title>"`, and Enter / Space to open. It is the
   same helper the other surfaces use.
2. **Tab order.** Per card: bulk checkbox → title → Move ▾ → ✓ → quick
   buttons. That is one more stop per card than before. The row's concern
   was "a board of 40+ cards is a tab marathon"; roving tabindex would make
   the card's own buttons unreachable without new arrow-key rules, which is
   a bigger change than this row. The page already has "Skip to main
   content" (#458) and collapsible sections. Not done here.
3. **Focus back.** The title carries `data-task-id`, so #377's
   `_taskDetailRememberOpener` remembers it and, after a save re-draws the
   list, finds the new title inside the same section (`[id]` container) and
   focuses it. Escape and ✕ hand focus straight back.
4. **Touch.** On a phone the whole card is still the tap target, and it's
   well over 44px, so #453's floor holds. Long-press drag is untouched.
   Clicks open exactly as before.

## This ship

- `taskCardTitleOpener(title, task)` in `app.js`, called by the active
  card, the completed card and the cancelled card.
- Help → Keyboard in panels: "Opening one" names task cards.
- CACHE_VERSION bump.

## Tests

`tests/e2e/card_keyboard_open.spec.js`, red before the fix (3 of 4 tests;
the 4th, a click opening the card, is the quiet case), at both viewports:
- board: Enter opens with focus on ✕, and Escape puts focus back on the
  title;
- Space opens, and Tab from the title reaches the card's ✓;
- `/completed`: Enter opens;
- a click still opens.

There's no new pure logic: `makeOpener` is already Jest-tested (#454). The
a11y names spec (`a11y_gaps.spec.js`), #454's `keyboard_open.spec.js` and
`mobile_tap_targets.spec.js` still pass.
