# #457 — Dropdown menus have no Escape, focus movement or menu semantics

Deep review §D4 (2026-10-11). Checked 2026-10-15.

## What was wrong

Six popups were built by hand, each slightly differently: the Inbox triage
menu and a completed card's Re-open menu (`app.js`), the board's bulk ▾
menus (`showBulkDropdown`), Due date ▾ → "Pick a date…"
(`promptCustomDate`), /projects' bulk menus (`showProjectsBulkDropdown`)
and /recurring's (`showDropdown`). None had Escape, none moved focus into
the menu or back out, none had `role=menu` / `aria-expanded`.
`promptCustomDate`'s comment claimed Enter and Escape worked; neither did.
/recurring's menu also always opened under its button (the #487 bug).

## This ship

`static/menu_helpers.js` (now loaded from `base.html` on every page) gains
the behaviour half of the shared menu helper #487 started:

- `menuKeyTarget(count, current, key)` — pure: ↑ / ↓ wrap, Home / End.
- `attachMenu(anchor, el, {kind})` — `aria-haspopup` + `aria-expanded` on
  the opener; for a `menu`, `role=menu` / `menuitem`, focus on the first
  item and arrow keys; for a `dialog` (Pick a date…) focus stays where the
  caller put it. Escape closes it and returns focus to the opener and is
  consumed (so #381's panel Escape doesn't also fire); Tab out closes it.
  Returns `close()`, which the pages' item clicks and outside-click
  handlers now call (so `aria-expanded` goes back to false).

All six popups use it. Pick a date… applies on Enter. /recurring's menu is
placed with `placeMenu`.

## Tests

- Jest (`menu_helpers.test.js`): key targets; roles, expanded state, first
  item focused; arrows wrap; Escape closes, returns focus, is consumed; Tab
  closes; the dialog kind.
- Playwright (`menus_keyboard.spec.js`, both widths): each menu opened by
  Enter, walked with ↓ / ↑, closed by Escape back to its button; Pick a
  date… Escape; /recurring's menu ends on screen; a click outside still
  closes (the quiet case). Red on old ×12.
