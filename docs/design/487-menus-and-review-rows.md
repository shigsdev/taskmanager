# #487 — /projects bulk menus off-screen; scan/import review rows overflow at 375

Split from #452 on 2026-10-15. Measured on the dev server at 375×812.

## What is wrong

**/projects bulk menus.** `showProjectsBulkDropdown` (`static/projects.js`)
always puts its popover under the button that opened it. The buttons sit in
the sticky toolbar at the bottom of the screen, so the menu opens below it:

| Button | Button top–bottom | Menu top–bottom | Screen height |
|---|---|---|---|
| Type   | 691–735 | 739–805  | 812 |
| Status | 691–735 | 739–861  | 812 |
| Goal   | 743–787 | 791–1091 | 812 |

Status loses its last option and Goal is almost entirely off-screen. Nothing
keeps the menu inside the screen on the left or right either. (The board's
own bulk menu in `app.js` always opens upward and clamps left/right, so it
is fine.)

**Review rows.** The title box is `flex: 1` but keeps the browser's built-in
minimum width for a text box (about 199px), so the controls after it spill
out of the row:

| Screen | Page width at 375 |
|---|---|
| /scan → Tasks | 375 (fits) |
| /scan → Goals (title, category, priority, quarter) | **718** |
| /scan → Projects (title, type, quarter) | **527** |
| /import → a *duplicate* task or project row (adds the "duplicate" badge) | **419** |
| /import → a non-duplicate row | 375 (fits) |

## This ship

1. **`static/menu_helpers.js`** (dual export, `window.menuHelpers`):
   `placeMenu(anchor, menu, viewport, opts)` returns `{ left, top, maxHeight }`
   in viewport coordinates.
   - Opens below the anchor when the menu fits there. Otherwise it opens above
     when it fits there. Otherwise it opens on the side with more room, with
     `maxHeight` equal to that room, so the menu scrolls instead of running
     off the screen.
   - `left` starts at the anchor's left. It is clamped so the menu stays at
     least `margin` (8px) from both screen edges.
   - The 4px gap between the anchor and the menu is kept.
   This is the placement half of the shared menu helper that #457 asks for.
   #457 adds Escape, focus movement and menu roles, and moves the other
   dropdowns onto it.
2. `showProjectsBulkDropdown` places its popover with `placeMenu`
   (`position: fixed`, the same as the board's bulk menu).
3. **CSS:** `.import-candidate-title, .scan-candidate-title { min-width: 0 }`
   at every width. At ≤600px the scan row and the import row head wrap: the
   title shares the first line only with its checkbox, and the menus, the
   quarter box and the duplicate badge go on the next line.
4. New static file → `sw.js` APP_SHELL, `health.py` EXPECTED_STATIC_FILES,
   CACHE_VERSION bump.

## Found while testing (fixed here, same surfaces)

- **/projects bulk checkboxes were all at the page's top-right corner.**
  `.project-bulk-cb` is `position: absolute`, but `.project-card` was never
  positioned. So all 12 checkboxes stacked at (right 8, top 8) of the page,
  under the nav, from PR35 on. A click on the card still selected it, so
  bulk mode worked by card click, but the checkbox couldn't be used. Fix:
  `.project-card { position: relative }`.
- **A menu opened from the toolbar's second row went under its first row.**
  At 375 the toolbar wraps, so Goal ▾ is on row two. Its menu opens upward
  over row one, and the toolbar (`z-index: 150`) painted over the popover
  (`100`). The popover is now `160`.
- **The scan quarter box had no style** (browser inset border). It now uses
  the title box's style.
- Filed **#488**: the /scan review says "Review Task Candidates" and
  "Add All to Inbox" for goals and projects too.

## Tests

- Jest `tests/js/unit/menu_helpers.test.js`: room below → below; no room below
  → above; room on neither side → the larger side with `maxHeight`; clamped
  at the right and left edges.
- Playwright `tests/e2e/menus_review_rows.spec.js`:
  - /projects Select → tick a card's checkbox (a real click, which the old
    stacked checkbox failed) → every bulk menu button: the whole menu is
    inside the screen at both widths, and its last option is the element
    under its own midpoint.
  - Status ▾ → "On hold" (off the screen before) sends `{status: "on_hold"}`
    (the PATCH is stubbed).
  - /scan with the upload stubbed, once for each of Tasks, Goals and Projects:
    no sideways scroll at 375, and every control is inside its row.
  - /import Paste Project Names with a duplicate name: no sideways scroll at
    375.

## Out of scope

- Escape, focus and menu roles for every dropdown (#457).
- The goals Excel import review uses the same row head and gets the same fix,
  but it needs an .xlsx fixture to exercise. It is covered by the shared CSS,
  not by its own test.
