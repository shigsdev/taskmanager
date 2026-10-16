# #460 — Repeat labels show raw values or nothing

Found 2026-10-11 by the deep review (cross-surface #21) and in #425's
Phase 6. Checked 2026-10-15.

## What was wrong

Four places named a repeat rule, each with its own map:

| Where | Before |
|---|---|
| Board card badge (`app.js` `freqLabels`) | no `day_of_week` / `multi_day_of_week` → "↻ Repeat" |
| Recurring previews (`app.js` `_frequencyLabel`) | `multi_day_of_week` printed raw |
| /recurring list (`recurring.js` `_freqSummary`) | "day of_week — Mon", "multi day — …", "monthly — wk 2 day 1" (raw weekday number) |
| Voice memo row (`voice_memo.js`) | "↻ Recurring (monthly_nth_weekday)" — the raw value |

## This ship

`recurring_helpers.js` gains `repeatLabel(repeat, {short})` (dual export,
Jest), named after the Repeat dropdown:

- Daily · Weekdays · Weekly on Mon · Weekly on Mon, Wed, Fri · Monthly on
  the 15th · Monthly on the 2nd Tue.
- Without the day fields (previews carry only the frequency): Weekly ·
  Specific weekdays · Monthly (same date) · Monthly (nth weekday).
- `{short: true}` for the card badge: Daily / Weekdays / Weekly / Specific
  weekdays / Monthly — so card layout doesn't change.
- Unknown frequency → "Repeats"; out-of-range day numbers are dropped, never
  printed.

All four places use it. `recurring_helpers.js` moves from `recurring.html` to
`base.html` (the board and /voice-memo need it; loading it twice would throw
on its top-level `const`).

## Tests

- Jest `repeat_label.test.js`: every server frequency gets a name with no
  `_`; details; ordinals (1st … 11th–13th … 21st–23rd, 31st); preview
  fallbacks; short; bad input.
- Playwright: multi-weekday and monthly-Nth tasks — card badges, /recurring
  summaries, and no raw frequency value anywhere on the board or /recurring;
  the voice memo test now expects "↻ Recurring (Weekly on Mon)". Red on the
  old code.
