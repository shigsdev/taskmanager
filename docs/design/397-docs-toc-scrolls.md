# Spec #397 — the /docs table of contents scrolls on its own

**Filed:** 2026-10-08 (user report: "on the left side of the page you cannot
scroll up and down", https://web-production-3e3ae.up.railway.app/docs)
**Status:** fix approved 2026-10-08; extended the same day in Phase 6 (§2a)
**UI change** (`static/style.css`) → Phase 6, `CACHE_VERSION` bump, deploy.

---

## 1. The problem (measured on prod, 2026-10-08)

The /docs sidebar (`.docs-toc`, #33) is `position: sticky; top: 16px` with no
height cap and `overflow-y: visible`. It has grown to **1065 px** (30 links);
windows are 800–900 px tall. So it stays pinned while the page scrolls, cannot
scroll itself, and its last ~265 px of links ("Admin" group down to "Backups &
restore") only come into view at the very end of the 42,000 px page — on a
shorter laptop screen, even more is unreachable. /architecture uses the same
sidebar but its TOC is 579 px, so it was not yet affected.

## 2. Behaviour after the fix

Desktop `.docs-toc` gains a height cap and `overflow-y: auto`: still sticky,
always fully inside the space under the header, and it gets its own scrollbar
when taller than that. At its end the next wheel gesture carries on into the
page (browser default — no `overscroll-behavior` override). The mobile rule
(≤ 700 px), where the TOC is a static block, resets both
(`max-height: none; overflow-y: visible`). `static/sw.js` `CACHE_VERSION` bumped.

### 2a. Stick below the header (found in Phase 6)

The site header (`.nav`) is itself `position: sticky; top: 0; z-index: 100`,
**91 px** tall on desktop at every width from 701 to 1600 px (its tab row
scrolls sideways instead of wrapping). With the TOC stuck at `top: 16px`, the
header covered the TOC's top ~75 px mid-page — the "Docs" heading and the first
link ("Install on iPhone (Safari)") were hidden under it even with the TOC
scrolled to its top. Pre-existing, but it defeats this row's promise that every
link is reachable at any scroll position, so it ships here.

Final desktop values: `top: 107px` (91 px header + 16 px gap) and
`max-height: calc(100vh - 123px)` (107 px top + 16 px bottom gap). The header
height is hard-coded, not measured — the test below goes red if it changes.

## 3. Tests (`tests/e2e/docs_toc.spec.js`, desktop; skipped < 700 px)

- **The sidebar sits below the header, fits the window, and its first and last
  links can be reached mid-page** — page parked halfway down /docs: TOC top ≥
  the header's bottom, TOC bottom ≤ window height, TOC scrollable; at TOC
  scrollTop 0 the first link, and at its end the last link, is the element
  actually under its own midpoint (`elementFromPoint` — `toBeInViewport()`
  alone cannot see the header covering it); the page never moves. Red before
  §1 (TOC bottom at 1081 px in a 720 px window) and before §2a (TOC top 16 <
  header bottom 91).
- **A sidebar too short to scroll still lets the wheel scroll the page** —
  /architecture, mid-page, wheel over the sidebar moves the page. A behaviour
  guard, not a reproduced bug: one Phase 6 reading suggested
  `overscroll-behavior: contain` trapped the wheel there; it did not reproduce
  (3/3 runs scrolled — an earlier "red check" had silently patched the wrong
  CSS rule), and the fix does not use `contain`.

## 4. Phase 6

/docs and /architecture at 1280×800 and 375×812, page scrolled mid-way.
Desktop /docs: TOC sticky at 107 px (header ends at 91), bottom 784/800,
max-height 677 px, scrollable; **all 30 links** pass the `elementFromPoint`
check when scrolled into the TOC, without moving the page; a real wheel over
the TOC scrolls it (300 px, then to its end at 388) with the page still, and
the next gesture scrolls the page (+500). /architecture: TOC 579 px fits, the
wheel scrolls the page. Mobile: TOC static, `max-height: none`, no own scroll.
No horizontal overflow (scrollWidth ≤ innerWidth), 0 console errors.
Screenshot: /docs mid-page, sidebar below the header, scrolled to "Backups &
restore".

Out of scope, filed as #398: on mobile the TOC links are 20 px tall, under the
44 px tap-target floor.
