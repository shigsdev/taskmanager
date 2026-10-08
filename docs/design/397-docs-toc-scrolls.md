# Spec #397 — the /docs table of contents scrolls on its own

**Filed:** 2026-10-08 (user report: "on the left side of the page you cannot
scroll up and down", https://web-production-3e3ae.up.railway.app/docs)
**Status:** fix approved 2026-10-08
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

Desktop `.docs-toc` gains `max-height: calc(100vh - 32px)` and
`overflow-y: auto`: still sticky, always fully inside the window, and it gets
its own scrollbar when taller than the window. At its end the wheel carries on
into the page (browser default — no `overscroll-behavior` override). The mobile
rule (≤ 700 px), where the TOC is a static block, resets both
(`max-height: none; overflow-y: visible`). `static/sw.js` `CACHE_VERSION` bumped.

## 3. Tests (`tests/e2e/docs_toc.spec.js`, desktop; skipped < 700 px)

- **The sidebar fits the window and its last link can be reached mid-page** —
  page parked halfway down /docs: TOC top ≥ 0, bottom ≤ window height, TOC
  scrollable, and scrolling the TOC to its end brings the last link into view
  without moving the page. Red before (TOC bottom at 1081 px in a 720 px window).
- **A sidebar too short to scroll still lets the wheel scroll the page** —
  /architecture, mid-page, wheel over the sidebar moves the page. A behaviour
  guard, not a reproduced bug: one Phase 6 reading suggested
  `overscroll-behavior: contain` trapped the wheel there; it did not reproduce
  (3/3 runs scrolled — an earlier "red check" had silently patched the wrong
  CSS rule), and the fix does not use `contain`.

## 4. Phase 6

/docs and /architecture at 1280×800 and 375×812, page scrolled mid-way:
desktop TOC sticky at 16 px, bottom 784/800 on /docs, scrollable, wheel scrolls
it (297 px to its end) without moving the page; /architecture TOC fits and the
wheel scrolls the page; mobile TOC static; no overflow; 0 console errors.
Screenshot: /docs mid-page with the sidebar scrolled to "Backups & restore".
