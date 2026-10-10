# Spec #365 — the bulk toolbar must never cover the last row

Status: building (2026-10-10).

## 1. The bug, measured on every page that has the toolbar

`.bulk-toolbar` is `position: fixed; bottom: 16px; z-index: 150`
(`static/style.css:3982`) and nothing adds room under the page while it shows,
so the last row can never scroll clear of it. Measured locally with seeded
data, Select on / one task ticked, scrolled to the maximum, testing whether
the last card's centre is hit-testable (`elementFromPoint`):

| Page (toolbar) | Desktop 1280×800 | Mobile 375×812 |
|---|---|---|
| `/projects` (`#projectsBulkToolbar`) | card 669–750 vs toolbar 703–784: lower half covered (the row's #365 report: a title click hit the toolbar) | card centre **covered** |
| `/tier/<name>` (`#bulkToolbar`) | last card centre **covered** | **covered** |
| `/completed` (`#bulkToolbar`) | last card centre **covered** | **covered** |
| `/` board (`#bulkToolbar`) | clear — other content sits below the last card | clear |
| `/goals` | no bulk toolbar | — |
| `/recurring` | its bulk actions sit inline in the top toolbar, not fixed | — |

Toolbar height varies: ~81–85px on desktop, 114–158px on mobile, where the
buttons wrap onto 2–3 lines.

## 2. Behaviour

While a bulk toolbar is visible, the page gains bottom padding equal to the
toolbar's height + its 16px offset + a 12px gap. So at maximum scroll the
last row sits fully above the toolbar. When the toolbar hides, the padding
goes away. Nothing else changes: the toolbar's look, position and buttons are
untouched.

## 3. Implementation

- New dual-export `static/bulk_toolbar_helpers.js`
  (`window.bulkToolbarHelpers` / `module.exports`, IIFE so nothing lands in
  the shared global scope — #359):
  - `bulkToolbarClearance(heights, bottomPx)` — pure: the largest visible
    toolbar height (0 = hidden) + offset + gap, or 0 when none is visible.
  - `bulkToolbarWatch(doc, win)` — a `ResizeObserver` on every
    `.bulk-toolbar`. Show/hide (`display:none` → height 0), and wrapping
    onto more lines, both change its size, so the existing show/hide code in
    `app.js` / `projects.js` needs no hooks. It sets
    `body.style.paddingBottom` (body has no padding-bottom of its own today).
    No-op when there is no toolbar or no `ResizeObserver`.
    The padding is applied on the next animation frame, never inside the
    observer callback. Added during Phase 6: the new padding can bring in
    a scrollbar, which narrows the toolbar and resizes it again in the same
    frame. Chrome then raised "ResizeObserver loop completed with
    undelivered notifications" as a `window` error event (seen on
    `/tier/backlog`), and `base.html`'s client error reporter would ship
    that to the logs.
- Script include on `index.html`, `tier.html`, `completed.html`,
  `projects.html` (the board doesn't need it, but it shares `#bulkToolbar`,
  and the extra room is harmless).
- Cascade: `sw.js` APP_SHELL + `CACHE_VERSION`, `health.py`
  `EXPECTED_STATIC_FILES`.

## 4. Tests

- Jest `tests/js/unit/bulk_toolbar_helpers.test.js`: the clearance maths
  (hidden → 0, one visible, several → largest, bad input → 0), and the
  watcher with a stub `ResizeObserver` (padding set on show, cleared on
  hide, applied on the next frame not inside the callback, one update per
  frame, timer fallback without `requestAnimationFrame`, no-op without the
  API or without a toolbar).
- Playwright (desktop + mobile): on `/projects` (Select on) and
  `/tier/today` (one task ticked), at maximum scroll the last card's centre
  hit-tests inside the card; after clearing the selection or Cancel, body
  padding-bottom is back to 0.
- CLAUDE.md Phase 6 step 6 gets a line + a report row.

## 5. Out of scope

- The first `.bulk-toolbar` rule (`style.css:1877`, sticky) is mostly
  overridden by the later fixed rule, but it still leaks `right: 0` and
  `flex-wrap`. No visible bug today; not touched here.
