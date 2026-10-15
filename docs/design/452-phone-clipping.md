# #452 — Clipped or broken on the phone (part 1)

Deep review §C4. The row bundled ten findings; verified on live pages
2026-10-15 and split three ways.

## Verified and fixed here

| Finding | Measured | Cause | Fix |
|---|---|---|---|
| Completed card "Re-open" menu | 0 of 7 options tappable at 375 | card `overflow:hidden` (≤600 CSS + inline from swipe.js on touch) | `.task-card:has(.reopen-dropdown)`: `overflow: visible !important` (beats the inline style), `position: relative; z-index: 20; opacity: 1` — each completed card's `opacity: .7` is its own stacking context, so the next cards painted over the menu — and the swipe strip `display: none` (parked past the edge it would peek out and, even invisible, widen the page to 478px) |
| Swipe-to-reveal | blank space ≤600; unstyled Move/Delete inside the card >600 on touch | the whole card slid left with its buttons still past its right edge, inside its own clipped box; button styles lived only in the ≤600 block while swipe.js adds them on any touch device | the card stays put: `.swipe-actions` sits inside it at `right: 0`, `translateX(100%)` (clipped), and slides in — following the finger in swipe.js, locked by `.swiped`. Styles moved out of the media query; `z-index: 30` so it covers the quick-action buttons' #294 touch hit areas |
| `hidden` loses to `display:` | Utilities status boxes, Strength Forge detail rows showing | author `display` beats the UA `[hidden]` rule (#468 fixed one instance) | one global `[hidden] { display: none !important }`. Audited: no element shows itself by `style.display` while keeping `hidden` |
| Board bulk toolbar | 633 px (half of 1280), three rows | `position: fixed; left: 50%` shrink-wraps to the space right of the midpoint | `width: max-content` (`auto` in the ≤600 override, where left + right size it) — one row, 761 px |
| Settings tables | import table 400 px in a 326 px box, cut 74 px, no scroll | the section's `overflow: hidden` | ≤767 px: `.settings-section table { display: block; overflow-x: auto }` |
| (sibling of #451) bulk "Apply" button | white on sage, 2.6:1 | — | `--on-fill` text, light hover |

Already fixed earlier: the empty filter banner (#468).

## Split out

- **#486** Phone header: pin only the nav tabs (user decision 2026-10-15;
  215 px pinned today). The reflection "Analyze together" bar (sticky
  `top: 0`, z 2, under the z-100 nav at every width) and the /docs TOC jump
  offset follow the pinned height.
- **#487** /projects bulk menus open off-screen (always placed under a
  bottom-toolbar button); scan / import review rows overflow at 375.

## Tests

Playwright `tests/e2e/phone_clipping.spec.js`: Re-open menu fully tappable
over a completed card below it (desktop + phone, and on a touch screen with
the page staying 375 wide); swipe with touch emulation (the mobile project
doesn't emulate touch) at 375 and 820 — strip hidden before, both buttons
tappable after, styled; no `[hidden]` element showing on /utilities and
/strength-forge; toolbar one row inside the viewport at 1280; Settings tables
fit or scroll at 375. Red on old CSS + swipe.js (all six real cases).
