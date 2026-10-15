# #456 — Panel Tab trap breaks on a "Completed (N)" summary

Deep review §D3 (2026-10-11). Checked 2026-10-15.

## What was wrong

`static/panel_keys.js` `FOCUSABLE` (the list the #381 Tab trap walks) had
no `summary`. The project and goal panels' "Completed (N)" section (#375) is
a `<details>`, and its `<summary>` is a Tab stop. With the summary missing
from the list, Tab on it looked like "focus is outside the panel", so the
trap sent focus to the first control, ✕ — skipping the completed rows,
Save and Archive. `[contenteditable]` was missing the same way (none in the
panels today).

## This ship

- `FOCUSABLE` gains `summary` and `[contenteditable]:not([contenteditable="false"])`.
- `isShown` treats anything inside a CLOSED `<details>`, other than its own
  summary, as hidden: those rows aren't rendered, so the trap must not aim
  Tab at them (they carry `tabindex=0` from #372).

## Tests

- Jest (`panel_keys.test.js`): collapsed section → summary in the list, rows
  not; open → summary and rows; Tab and Shift+Tab on the summary are normal
  steps (not trapped back to ✕). Red on old ×4.
- Playwright (`keyboard_open.spec.js`, both widths): seeds a goal and a
  project with one completed task each, focuses "Completed (1)", Tab →
  focus stays in the panel and is not ✕. Red on old ×4.
