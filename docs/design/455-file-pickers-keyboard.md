# #455 — File pickers on /import and /scan can't be reached by keyboard

Deep review §D2 (2026-10-11). Checked in code and on the dev server
2026-10-15.

## What was wrong

- All six file inputs — /import's tasks Excel, projects Excel, OneNote
  .docx, goals Excel and transcript file, and /scan's image — were
  `style="display:none"` behind a `<label for=…>`. A label is not a Tab
  stop and a `display:none` input can't take focus, so none of those flows
  could be started from the keyboard (measured: Tab never lands on them).
- `import.js` also called `input.click()` from each label's click handler,
  on top of the label's native `for=`. A mouse click asked for TWO pickers
  (Playwright counts 2 `filechooser` events) — the double trigger
  `scan.js` already documents as cancelling iOS Safari's picker.

## This ship

- The inputs get `class="file-input-clipped"`: clipped to 1px, still
  focusable, the same technique /reflection's "+ Add file" uses
  (`.reflection-context-input`). Enter / Space on the focused input opens
  the picker.
- The label shows the copper focus ring while its input has keyboard focus
  (`:has(.file-input-clipped:focus-visible)`), so you can see where you are.
- The five redundant label click handlers (and their now-unused label
  variables) are gone; the label's `for=` alone opens the picker, once.

## Tests

`tests/e2e/file_pickers.spec.js` (both widths): for each of the six
pickers, Tab from the control before it lands on the input, the label's
outline is on, and Enter opens a file chooser; a click on an /import label
opens exactly one chooser. Red on the old code ×7.
