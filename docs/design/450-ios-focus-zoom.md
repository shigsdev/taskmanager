# #450 — iOS zooms the page when you tap most text fields

Deep review §C2.

## What happens

iOS Safari zooms in when a focused field's text is under 16 px; in the
installed PWA the page stays zoomed until you pinch back. Only the task panel
(and one settings number box) had a 16 px rule (`style.css` mobile block).
Measured at 375 px before the fix — 13 of 18 pages had fields under 16 px:
the capture box (14.4), its type select (12.8), board search, Focus slot
goal selects (13.6), goal / project / recurring panel fields, filters,
import review fields, /docs search, and more.

## Change

One rule in the ≤767 px block: every `input` that opens the keyboard (the
`:not()` chain excludes checkbox, radio, range, file, color, button, submit,
reset, hidden, image), every `select` and `textarea` → `font-size: 16px
!important`. `!important` because it is a floor that has to beat component
rules of every weight (`.capture-bar select`, ids, …). Desktop unchanged.
`CACHE_VERSION` bump.

## Tests

Playwright `tests/e2e/ios_zoom_font.spec.js`, phone viewport, 18 pages: every
typing field in the DOM — closed panels and pop-ups included, computed style
exists for hidden elements — computes to ≥ 16 px. Red on old CSS (13 pages).
This replaces the row's suggestion of a `test_mobile_css.py` string check:
the rendered check measures what the browser actually applies.
