# #449 — The capture box is 67 px wide on the phone board

Deep review §C1.

## What happens

At ≤600 px the capture bar takes the full nav row (`style.css` mobile block),
but its children stay on one line: the type select (≈78 px) and four 44 px
icon buttons leave `#captureInput` 67 px on the board (117 px on /tier, which
has fewer buttons). The placeholder is cut to "Add a ta…".

## Change

In the ≤600 px block: `.capture-bar { flex-wrap: wrap }` and
`.capture-bar input[type="text"] { flex-basis: 100% }` — the text box gets
the first row (355 px at 375), the select and buttons wrap onto the second.
Every page with a capture bar (board, /tier, /completed, /calendar, /goals,
/projects, /recurring, /docs, /architecture) shares the rule. Desktop
unchanged. `CACHE_VERSION` bump.

## Tests

Playwright `tests/e2e/capture_bar_width.spec.js` on /, /tier/today, /goals:
at ≤600 px the box is the bar's full width (≥ 300 px) and every other control
sits below it, inside the viewport; at desktop all stay on one row (the quiet
case). Red on old CSS at mobile.

## Knock-on (found by the gate)

The phone header grows from 165 px to 215 px, so the /docs and /architecture
TOC jump offset (#400, `.docs-page [id] { scroll-margin-top }` at ≤600 px)
moves from 181 px to 231 px — `tests/e2e/docs_toc.spec.js` went red exactly as
its comment promises. Nothing else depends on the header height (the desktop
TOC's sticky `top` is reset on mobile).
