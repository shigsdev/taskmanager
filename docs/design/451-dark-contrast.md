# #451 — Dark-theme contrast

Deep review §C3. The app has one, dark theme (slate canvas, cream text).

## What happens (measured, WCAG contrast)

| Element | Before |
|---|---|
| Selected task card (`.task-card.bulk-selected`) | `#e8f0fe` under cream text — 1.1:1 |
| White on sage (Keep, quick ✓ hover, task-panel ✓ Complete) / amber (Snooze, import "duplicate" badge) | 2.6:1 / 2.5:1 |
| Task-panel ✓ Complete | `.btn-complete` sat before `.btn` with the same weight, so `.btn` won: copper with white, 3.8:1 — never the intended sage |
| Recurring preview cards | title `#4b5563` 2.5:1, meta `#6b7280` 3.9:1; hover flips to near-white `#f4f4f5` |
| Failed / applied row tints (✨ Plan, Auto-categorize, /plan, Focus plan, reflection Apply) | 0.08 alpha — near-invisible against the panel |
| Voice-memo error box | already fixed by #442 |

## Change (`style.css`)

- Tokens: `--tint-failed` (rust 0.24), `--tint-applied` (sage 0.18),
  `--on-fill` (slate-0, text on sage / amber fills).
- Selected card → `#2e2418` copper-tinted slate (cream 12:1).
- Sage / amber fills → `--on-fill` text (7.1:1 / 7.5:1). `.btn.btn-complete`
  so the panel button is the intended sage; hover `#a7b59f` (8.7:1).
- Preview cards → title `--cream-dim` (7.1:1), meta `--cream-faint` (5.2:1),
  hover `--slate-300`.
- Tints → the two tokens; failed rows also get an inset 3 px rust edge (not on
  the Auto-categorize table row, where row box-shadows are unreliable).
- `CACHE_VERSION` bump.

## Out of scope → new row

- **#485** White on copper (the primary `.btn`, Freeze, Save, Copy to
  tomorrow, …) is 3.8:1 — under 4.5:1 for this text size. App-wide button
  look; not in the review's list.

## Tests

Playwright `tests/e2e/dark_contrast.spec.js` (both viewports): builds each
case with the app's classes on a real page and measures rendered colors —
text ≥ 4.5:1 (hover states via real hover), tints ≥ 1.25:1 against their
panel, preview hover background not near-white. Red on old CSS (all four).
