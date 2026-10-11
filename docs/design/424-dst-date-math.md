# #424 — Daylight saving breaks the board's date math

Filed 2026-10-11 by the deep review (§A2). Deadline: the clocks go back on
**2026-11-01** (and forward on 2027-03-14).

Adding `n × 86400000` ms to a local midnight is not "n days later" when a
clock change falls in between: on the 25-hour day, midnight + 24 h is 23:00
the same date; on the 23-hour day, midnight + 7 × 24 h is 01:00, past the
next midnight. `calendar.js` hit this in #345 and fixed it with calendar-day
arithmetic (`new Date(y, m, d + n)`); the rest of the client never was.

## 1. Surface

Every ms-per-day computation in `static/` (grep for `86400000`,
`_MS_PER_DAY`, `24 * 60 * 60 * 1000`):

| Site | What it decides | Wrong when (Eastern) |
|---|---|---|
| `tier_helpers.js` `tierForDueDate` — tomorrow, this/next Monday, Sunday | Which section a date belongs to (panel Section sync, drag, filing, review rows) | Oct 26–Nov 1: a date of Nov 8 → backlog; Nov 1: tomorrow (Nov 2) → this_week/next_week mismatch. Mar 8–14 2027: Mar 15 → backlog |
| `tier_helpers.js` `dueDateForTier("tomorrow")` | Due date stamped by Tomorrow button / drag / Section change | Nov 1: stamps 2026-11-01 (today) |
| `app.js` `_tierDateRange` | This/Next Week header dates and which recurring previews show | Week of Oct 26: "Nov 1 — Nov 7"; Nov 8 previews dropped; spring: Monday previews dropped |
| `app.js` `_tierHeaderDate("tomorrow")` | Tomorrow header | Nov 1: reads "Sun, Nov 1" |
| `app.js` `renderDayStrip` | 14 day cells; a drop sets that date | Week of Oct 26: Nov 1 appears twice, Nov 8 never; the Monday cell sets the wrong date |
| `app.js` `loadRecurringPreviews` | 14-day preview window end | First hour after midnight on Nov 1 only (end one day short) |
| `app.js` bulk "Due date ▾" Tomorrow / In 1 week | Staged due date | First hour after midnight on change days |

Not affected: `calendar.js` (fixed in #345), `calendar_bucket_helpers.js`
(`calendarRangeEndIso` works in UTC, which has no DST), and every other week
computation (`plan.js`, `weekly_focus.js`, `recurring_helpers.js` use
`setDate`). The server uses `date` objects throughout — no DST exposure.

## 2. This ship

1. `date_helpers.js`: new `addDays(date, n)` — `new Date(y, m, d + n)`, the
   #345 operation — exported on `window.dateHelpers` / `module.exports`.
2. `tier_helpers.js`: drop `_MS_PER_DAY`; compute tomorrow and the week
   bounds with calendar-day arithmetic (private `_tierHelpersAddDays` — the
   file is non-IIFE, so a bare `_addDays` would be a cross-file global), and
   export a `weekBounds(today)` → `{thisMonday, thisSunday, nextMonday,
   nextSunday}` so the board uses the same bounds instead of a second copy.
3. `app.js`: `_tierDateRange` uses `tierHelpers.weekBounds`;
   `_tierHeaderDate`, `renderDayStrip`, `loadRecurringPreviews` and the bulk
   due-date menu use `dateHelpers.addDays`. No ms-per-day arithmetic left in
   `static/` except duration maths (`audio_buffer.js` retention).
4. Gate: `tests/test_repo_hygiene.py`-style check that fails on
   `86400000` / `24 * 60 * 60 * 1000` day arithmetic in `static/*.js`
   outside an allow-list (UTC-anchored `calendar_bucket_helpers.js`,
   duration-only `audio_buffer.js`), so the bug can't be written again (#459).
5. Tests, red on the old code:
   - Jest, a new file that pins `process.env.TZ = "America/New_York"`:
     `dueDateForTier("tomorrow")` on 2026-11-01 → 2026-11-02;
     `tierForDueDate` on 2026-10-28 for 11-08 → next_week, 11-01 →
     this_week; on 2026-11-01 for 11-02 → tomorrow; on 2027-03-10 for
     03-15 → next_week; on 2027-03-14 for 03-15 → tomorrow; `weekBounds`
     contiguity across both changes; `addDays` across both changes.
   - Playwright (desktop + mobile), context `timezoneId: America/New_York`
     and a fixed clock: on 2026-10-28 the day strip has 14 distinct dates
     ending 2026-11-08 and the Next Week header reads "Nov 2 — Nov 8"; on
     2026-11-01 the Tomorrow header reads Mon, Nov 2.
6. CACHE_VERSION bump. No Help copy change (behaviour is now what Help
   already says).

## 3. Out of scope

Everything else from the deep review stays in its own row (#425–#459).
