# Spec #399 — the remaining mobile selects under 44 px (capture bar, weekly focus, /utilities)

**Filed:** 2026-10-08 (found in #398/#354's sweep of every page's `<select>`)
**UI change** (`static/style.css`) → Phase 6 at both viewports,
`CACHE_VERSION` bump (v275 → v276), deploy.

## 1. Measured at 375×812 (2026-10-09)

| Surface | Control | Before |
|---|---|---|
| Capture bar (every page) | `#captureType` select | 33 px |
| | text input beside it | 34 px |
| Weekly focus (board, 3 slots) | goal select | 34 px |
| | text input | 34 px |
| | Plan / Clear buttons | 40 px (an explicit `min-height: 40px`) |
| /utilities project↔goal rows | `.pg-goal-select` | 21 px |

The capture bar's icon buttons (44–48 px) and the /utilities Clear button
(44 px) already passed.

**Scope:** the row names selects; the fix covers every control in those three
rows. Lifting only the select would leave each row half at 44 px and half not,
and CLAUDE.md's floor applies to inputs and buttons as well.

## 2. Fix — each rule in the mobile block that already styles that surface

- `@media (max-width: 600px)` (main mobile block, next to `.capture-bar`):
  `.capture-bar select, .capture-bar input[type="text"] { min-height: 44px; }`.
  Height only — the row's width (the 2026-04-18 capture-bar overflow incident)
  is unchanged: the bar still ends at 350 px of 375.
- `@media (max-width: 700px)` (weekly-focus block): Plan / Clear
  `min-height` 40 → 44 px; `.weekly-focus-slot-goal, .weekly-focus-slot-input
  { min-height: 44px; }`.
- New `@media (max-width: 600px)` after the `.pg-*` rules (they had none):
  `.pg-goal-select { min-height: 44px; }`.

## 3. Test

`tests/e2e/mobile_tap_targets.spec.js` gains three surfaces (capture-bar
select + input; weekly-focus selects, inputs, buttons; `.pg-goal-select`).
Red before at 33 / 34 / 21 px; green after. Mobile only.

## 4. Phase 6

375×812: all capture-bar, weekly-focus and /utilities controls ≥ 44 px;
capture bar still creates a task with the chosen type; no horizontal overflow;
0 console errors. 1280×800: sizes unchanged (desktop rules untouched).
