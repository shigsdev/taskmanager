# Spec #398 + #354 — mobile tap targets: docs TOC links and the /goals + /projects filter bars

**Picked:** 2026-10-08, together by user choice ("398 and 354") — one branch,
one ship, two rows.
**UI change** (`static/style.css`) → Phase 6 at both viewports,
`CACHE_VERSION` bump, deploy.

---

## 1. The problem (measured at 375×812 on the dev server, 2026-10-08)

| Row | Surface | Measured | Floor |
|---|---|---|---|
| #398 | `/docs` TOC links (30) | 20 px tall, ~5 px apart | 44 px |
| #398 | `/architecture` TOC links (11) | 20 px | 44 px |
| #354 | `/goals` `.goals-filters` selects (5: category, priority, status, archived, quarter) | 31 px | 44 px |
| #354 | `/projects` `.projects-filters` selects (3: type, active, goal) | 32 px | 44 px |

#354 asked to check `/projects` and `/calendar` for the same bar: `/projects`
has it (same 44 px miss); `/calendar` has no filter bar. The home board's
filter region (`.filters-region`) is already 44 px.

## 2. Behaviour after the fix

**#398 — docs TOC (both pages share `.docs-toc`).** In the existing
`@media (max-width: 768px)` docs block, where the TOC is already a static
block: each group's `ul` becomes a two-column grid
(`repeat(2, minmax(0, 1fr))`, 12 px gap), `li` loses its 4 px margin, and each
link is `display: flex; align-items: center; min-height: 44px` with
`line-height: 1.25` so two-line titles still fit. Measured by injection: links
44 px, the /docs TOC **1004 px** (was 1048 — shorter, not longer; a single
44 px column would be 1620 px), /architecture 607 px (was 565), no horizontal
overflow. Desktop untouched (the sticky sidebar from #397).

**#354 — filter bars.** In the existing `@media (max-width: 600px)` block that
already holds `.goals-filters { flex-wrap: wrap; }`:
`.goals-filters select, .projects-filters select { min-height: 44px; }`. Both
bars are one rule, so they cannot drift apart. Desktop untouched.

No new breakpoint: each rule goes into the block that already styles that
surface on mobile, so #382 (44 px rules spread over 600/700/767 px) gets no
worse. Between 601 and 768 px the filter selects stay at their current size —
that band is #382's.

## 3. Tests (`tests/e2e/mobile_tap_targets.spec.js`, mobile only; skipped ≥ 700 px)

- **/docs and /architecture: every TOC link is at least 44 px tall** and the
  page has no horizontal overflow.
- **/goals and /projects: every filter select is at least 44 px tall** and the
  page has no horizontal overflow.

Red before (20 / 31 / 32 px).

## 4. Phase 6

/docs, /architecture, /goals, /projects at 375×812 and 1280×800: sizes above,
the filter selects still filter (pick a value, the list changes), TOC links
still jump to their section, no overflow, 0 console errors. Desktop unchanged.

## 5. Out of scope — filed as #399

Other selects under 44 px on mobile, found in the same sweep: the capture
bar's Work/Personal select (`#captureType`, 33 px, every page), the board's
weekly-focus slot selects (34 px) and three `.pg-row` selects on `/utilities`
(21 px).
