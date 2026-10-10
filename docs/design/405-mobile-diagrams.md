# Spec #405 — /architecture diagrams on a phone: full size inline + a full-screen view

Status: built 2026-10-09. User choice: "Both" (inline full size with
sideways scroll, AND a tap-to-open full-screen view). Desktop unchanged.

## 1. Why, in numbers (375×812, 2026-10-09)

Mermaid fits each diagram to its box (`useMaxWidth`, the default for
flowcharts), so on a ~300 px box the 11 flowcharts' labels are
6.1 / 2.3 / 6.5 / 5.4 / 8.6 / 4.4 / 15.6 / 6.2 / 5.6 / 4.9 / 6.9 px. At natural
size every label is 16 px. Natural widths: 276–1909 px, i.e. 0.9–6.3 box
widths (most 2–3). The ER diagram already draws at natural size and scrolls
(#391, 3957 px, 16 px labels).

## 2. Behaviour

**Narrow screens = `max-width: 700px`** (the breakpoint /docs and
/architecture already use for their mobile layout).

### 2a. Inline: full size, swipe sideways

- Every diagram draws at its natural size (16 px labels) and scrolls
  sideways inside its own box; the page itself never scrolls sideways.
- No box opens on an empty first screen. Found in Phase 6: at scroll 0 most
  boxes show their first nodes, but two did not — "What's running" (#2, a
  left-to-right diagram whose start sits 947 px down a 1202 px box) and #11
  (top-down, its top nodes centred ~400 px to the right). Rule
  (`initialScrollLeft`, pure, Jest-tested): if no node is inside the box's
  first screen (box width × min(box height, viewport height)) at
  `scrollLeft 0`, scroll sideways to centre the top-most node; otherwise stay
  at the left edge. The full-screen view applies the same rule on open.
  Applied when each diagram's finished svg appears (MutationObserver — the
  Mermaid start-up is not touched, #395's timing tests depend on it) and
  again when a `<details>` holding diagrams opens (closed boxes have no
  width to measure). Phone only (≤ 700 px).
- The left edge must stay reachable — a centred overflowing svg could be
  clipped on the left and not scrollable to (checked: it isn't, §4).
- Mechanism: Mermaid `flowchart.useMaxWidth: false`, so every flowchart svg
  carries its natural width like the ER one. Desktop keeps today's look via
  the existing `pre.mermaid svg { max-width: 100%; height: auto }` (wider
  diagrams fit the box, narrower ones stay natural). Under 700 px:
  `max-width: none`.

### 2b. Full-screen view

- On narrow screens, each diagram gets a **"⤢ Full screen" button** above
  its box (≥ 44 px tap target). A button, not "tap the diagram": the
  diagram is a swipe area, and a tap-to-open on a swipe area misfires.
  Hidden on desktop.
- Opens a modal `<dialog>` filling the screen: the diagram at natural size,
  pannable in both directions, with a **✕ Close** button (≥ 44 px).
- Closes on ✕, on Escape, and via the browser's dialog cancel. The page
  behind does not scroll while it is open.
- The SAME svg element is moved into the dialog and moved back on close
  (no clone: Mermaid's svg uses ids for its scoped styles and arrowhead
  markers; a copy would duplicate them).
- Focus: lands on ✕ when it opens; returns to that diagram's Full-screen
  button when it closes.
- Logic in `static/diagram_zoom.js` (dual-export, `window.diagramZoom` /
  `module.exports`), wired by the page.

## 3. Tests

- **Jest** (`tests/js/unit/diagram_zoom.test.js`, jsdom): open moves the svg
  into the dialog and opens it; close puts it back in the same place (same
  element, same position among siblings); focus goes to ✕ then back to the
  opener; Escape/cancel closes and restores; opening while open is a no-op;
  no svg yet (Mermaid still drawing) → no-op.
- **Playwright** (`tests/e2e/architecture_mermaid.spec.js`): at mobile, every
  flowchart is wider than its box with ≥ 10 px labels, its box scrolls
  (`scrollWidth > clientWidth`) from `scrollLeft 0` showing the svg's left
  edge, and the page doesn't overflow; Full screen → dialog open with the
  svg inside at natural width; Escape → closed, svg back in its box, focus
  on the button; ✕ does the same. At desktop: no Full-screen button
  visible, and every diagram's drawn width is the same as before this
  change (recorded below).

## 4. Desktop baseline (to keep)

Recorded before the change at 1280×800, drawn width per diagram, in page
order — must be identical after.

`706×468, 742×453, 714×1604, 762×2781, 3957×4515 (ER), 502×993, 742×1531,
276×1040, 690×2434, 742×934, 742×3368, 620×1979` (width×height px, all
`<details>` open).

Also checked before building: at 375 px the ER box (`text-align: center`,
svg inline, 3957 px) opens at `scrollLeft 0` with the svg's left edge 16 px
inside the box — Chrome starts an overflowing centred line at its start, so
no left-edge clipping.

## 5. Docs / cascade

- New static asset → `static/sw.js` APP_SHELL, `health.py`
  EXPECTED_STATIC_FILES, CACHE_VERSION bump (open tabs reload once).
- New UI interaction → CLAUDE.md Phase 6 checklist + Regression Test Report
  rows for /architecture.
- `templates/architecture.html` comment on the Mermaid config.

## 6. Out of scope

- Desktop zoom / full-screen (desktop unchanged by request).
- Pinch-zoom inside the dialog beyond what the browser already does.
