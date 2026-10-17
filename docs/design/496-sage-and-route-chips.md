# #496 — Text on sage, and the voice PROJECT chip

Found 2026-10-16 by #485's sweep — the same class of miss as #451, other
fills.

## What was wrong

| Control | Fill | Text | Ratio |
|---|---|---|---|
| /voice-memo GOAL route chip | sage `#94a48b` | white | 2.64 |
| /reflection CREATE badge | sage | white | 2.64 |
| day strip cell under a dragged card (`.day-cell-hover`) | sage | white | 2.64 |
| /voice-memo PROJECT route chip | light-theme pink `#ec4899` | white | 3.53 |

## This ship (`static/style.css`)

- The three sage fills carry the dark page colour `--on-fill`: 7.12:1 —
  as #451 did for Complete / Keep.
- PROJECT becomes `--amber` with `--on-fill`: 7.46:1; TASK (copper, #485),
  GOAL (sage) and PROJECT (amber) stay three distinct chips.
- White on rust (DELETE badges, `.btn-danger`) measures 4.76:1 — passes, so
  it stays (the quiet case).
- CACHE_VERSION v350.

## Tests

`tests/e2e/sage_contrast.spec.js`: each control built with the app's
classes measures ≥ 4.5:1, PROJECT is no longer pink (red before on all
four); DELETE keeps white; every visible sage fill with text on 19 pages
measures ≥ 4.5:1 (the guard for one nobody listed).
