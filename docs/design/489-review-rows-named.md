# #489 — Review-screen rows name every control

Split from #458 on 2026-10-15.

## What was wrong

#458 named every control a page has at load and `a11y_gaps.spec.js` guards
that, but the review screens build their rows only after an upload or a
parse, so the guard never saw them. A screen reader heard "checkbox, not
checked" on every row with no item named.

Measured 2026-10-16 (the new spec, before the fix) — the unnamed controls
are each row's head; fields wrapped in a `<label>` (import's Tier, Due
date, Goal, Project, URL, Notes; voice's Project / Goal / Category) were
already named:

| Screen | Unnamed per row |
|---|---|
| /import tasks · goals · projects | tick box, title box, Type / Category |
| /scan tasks · goals · projects | tick box, title box, Type / Category / Priority / Target quarter |
| /voice-memo | tick box, title box, Type, Section, Due date |
| /plan | Section, Due date, Project, Goal |
| 💡 Auto-categorize | Section, Project, Goal, Due date, Type |
| /reflection | each proposal's tick box |
| Strength Forge log form | none (already named) |

## This ship

New `static/row_label_helpers.js` (dual export, `window.rowLabels`):
`labelFor(purpose, title, index)` → `Include “Call the dentist”`,
`Type for “Call the dentist”`, `Title of row 2` (the title box — its own
text changes as you type), `row N` when the title is empty, titles cut at
80 characters; `name(row, title, index, {selector: purpose})` sets the
aria-labels. Each row builder calls it once and again when its title box
changes; 💡 also after a Type change rebuilds its Project / Goal pickers.
Loaded on /import, /scan, /voice-memo, /plan, the board and /reflection;
in `sw.js` APP_SHELL + `health.py`; CACHE_VERSION v345. Nothing visual
changes.

## Tests

- `tests/e2e/a11y_names.js` — #458's `unnamedControls` moved here so both
  specs share one rule.
- `tests/e2e/review_rows_named.spec.js` — each screen above in its stubbed
  review state has no unnamed control, and the row tick box names its
  title (red before on 10 of 11).
- `tests/js/unit/row_label_helpers.test.js`.
