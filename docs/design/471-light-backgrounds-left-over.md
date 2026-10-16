# #471 — Light backgrounds left over from before the dark theme

Filed 2026-10-13 in #442's Phase 6. Checked 2026-10-16 by grepping
`static/style.css` (and `static/*.js` / `templates/*.html` for inline
styles) for light hex backgrounds, and for `var(--x, #fff…)` fallbacks
whose variable is never defined.

## What was wrong

#224 (2026-05-24) moved the app to a dark theme, and #224 / #442 fixed the
reflection and voice-memo error boxes. Four rules from before that still
paint a light background on the dark page:

| Rule | Was | Where you see it |
|---|---|---|
| `.scan-error` | `#fff0f0` behind `--danger` text (~2.6:1) | /scan when a scan fails |
| `.progress-bar` | `#e5e7eb` track | /goals card progress bars — a bright grey strip |
| `.voice-btn.voice-listening` | `#fee2e2` pink square | the 🎤 beside a panel field while listening |
| `.parent-link-status-{archived,cancelled,deleted}` | pastel pills, dark text | the task panel's Parent task line |

Everything else the grep found is deliberate and stays: the update
banner's white button (a call to action on the blue strip), the print
sheets (paper), the Strength Forge print card, and the Mermaid
`classDef` fills on /architecture (their own light diagram boxes). Every
`var(--x, #fff)` fallback names a variable that is defined, so none of
them actually paints white.

## This ship

- `.scan-error`: the #442 box — `rgba(198, 74, 42, 0.12)` with
  `var(--cream)` text, a rust left border.
- `.progress-bar` track: `rgba(255, 247, 232, 0.09)`, the Today ring's
  unfilled track, so the copper / sage fill still reads against it.
- `.voice-btn.voice-listening`: the capture bar's listening state
  (`#captureVoice.voice-listening` — red `#dc2626`, white), so both
  microphones say "listening" the same way.
- `.parent-link-status-*`: the theme's badge pattern (a 16% tint with a
  bright text colour) — archived sage, cancelled amber, deleted the
  light rust `#e0876e`, the same colours as `.badge-status-*` /
  `.badge-priority-must` (plain `--rust` text on a dark tint is ~3.4:1).

Test: `tests/e2e/dark_contrast.spec.js` builds each element with the
app's classes and measures it — text ≥ 4.5:1, background dark (relative
luminance < 0.1), and the goal progress fill ≥ 3:1 against its track.

## Out of scope

Nothing new to file.
