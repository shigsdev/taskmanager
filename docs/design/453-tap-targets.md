# #453 — Tap targets under the floor at phone width

Deep review §C5 (2026-10-11), plus the #433 note on the board bulk toolbar.
Measured on the dev server at 375×812 on 2026-10-15 with a survey of every
page and the states the row names (task panel, goal panel, bulk toolbars,
Auto-categorize, calendar).

## The floors (house convention, already in use)

- **44px** tall for buttons, links, selects, text/date inputs and summaries
  (#140, #382, #399: `.btn`, `.icon-btn`, `.nav-tab`, panel fields). A ✕ or
  arrow button that is only a glyph gets 44 wide as well.
- **24px** for a checkbox or radio (WCAG 2.5.8 AA), the size
  `.task-card .bulk-select-check` already gets on mobile. A 44px box would
  swallow the clicks meant for the row around it, which opens a panel.
- **24px** for the "Read ↗" URL badge inside a card's metadata line. At 44px
  every card with a URL would grow 25px for a secondary link.

All of these go in the existing `@media (max-width: 767px)` floor block in
`style.css` (#382's single touch breakpoint). Desktop doesn't change.

## Measured under the floor, and fixed here

| Where | Control | Was (h × w) | Floor |
|---|---|---|---|
| Board, /completed | search box `#taskSearchInput` | 35 | 44 |
| Board | Weekly Focus tabs `.weekly-focus-tab` | 23 | 44 |
| Board | section heading link `.tier-heading-link` | 21 | 44 |
| Board | Inbox triage checkbox `.triage-check` | 20 × 20 | 24 |
| Board, tier pages | "Read ↗" `.badge-url` | 19 | 24 |
| Board bulk toolbar | every button (Status ▾ etc.) | 40 | 44 |
| Board bulk toolbar | ↑ / ↓ | 40 × 25 | 44 × 44 |
| Board bulk menus | `.bulk-dropdown button` (Mark complete …) | 32 | 44 |
| Task panel | subtask checkbox `.subtask-row` | 13 × 13 | 24 |
| Task panel | checklist checkbox | 13 × 13 | 24 |
| Task panel | checklist ✕ `.remove-item` | small | 44 × 44 |
| Goal panel | linked-task checkbox `.linked-task-row` | 13 × 13 | 24 |
| Auto-categorize | ✕ `.auto-categorize-close` | small | 44 × 44 |
| /projects Select | card checkbox `.project-bulk-cb` | 18 × 18 | 24 |
| /projects bulk menus | `.bulk-dropdown-item` | ~30 | 44 |
| /recurring | row checkbox `.recurring-row` | 13 × 13 | 24 |
| /calendar | task line `li.calendar-task-link` | 24 | 44 |
| /scan | Parse as radios | 13 × 13 | 24 |
| /reflection | Show archived checkbox | 13 × 13 | 24 |
| /reflection | history tick box `.reflection-history-select` | 22 × 22 | 24 |
| /reflection | "Recently deleted" summary | 20 | 44 |
| /plan | week-start date `#planStartDate` | 39 | 44 |
| /strength-forge | track ✕ `.sf-track-del` | 21 × 22 | 44 × 44 |
| /strength-forge | exercise ℹ️ `.sf-exrow-info` | 34 × 34 | 44 × 44 |
| /strength-forge | expandable track label `.sf-track-expandable` | 18 | 44 |
| /utilities | "View latest runs ↗" `.utility-runs-link` | 20 | 44 |
| /print | Print button, Back to Tasks link (own `<style>`) | 40, 17 | 44 |

## Not changed

- An inline link inside a paragraph or list item in /docs (WCAG 2.5.8's
  inline exception).
- Calendar preview items: they aren't clickable (the cell is).
- The nav tabs (#140, already 44).

## Tests

Extend `tests/e2e/mobile_tap_targets.spec.js` (mobile only):
- Static surfaces get added to its SURFACES list with the floor and the
  dimension (height, or both for glyph buttons and boxes).
- Stateful surfaces get their own tests: board bulk toolbar + Status menu
  (tick a card), a task panel with a subtask and a checklist row (task
  created via the API, opened with `/?task=<id>`), a goal panel's
  linked-task checkbox, Auto-categorize ✕ (categorize stubbed),
  /projects Select checkboxes + Type menu items.
Each test is red on the old CSS.
