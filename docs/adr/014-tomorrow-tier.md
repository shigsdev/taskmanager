# ADR-014: Tomorrow tier + midnight auto-roll

Date: 2026-04-20
Status: ACCEPTED

## Context

Backlog #27 — the board has Today and This Week, but nothing in
between. "Tomorrow" as an explicit planning surface was missing. Users
who'd decided "I'll do this tomorrow specifically" had to either cram
it into Today (wrong — pollutes the do-now list) or into This Week
(wrong — loses the specificity). Pairs naturally with #23's
day-of-week grouping: a Tuesday task today and the Tomorrow tier for
a Wednesday plan live side by side.

## Decisions

### 1. Insert `TOMORROW` into `Tier` between `TODAY` and `THIS_WEEK`

Board display order becomes: `INBOX → TODAY → TOMORROW → THIS_WEEK →
NEXT_WEEK → BACKLOG → FREEZER`. Display order is carried by
`TIER_ORDER` in `static/app.js`, not the enum itself (Python enums
are unordered by convention).

### 2. Migration + enum repair reuses the ADR-010 playbook

`ALTER TYPE tier ADD VALUE IF NOT EXISTS 'TOMORROW'` (UPPERCASE —
SQLAlchemy stores Python enum NAMES in Postgres, not lowercase
`.value` strings — learning from the #23/#25 post-mortem). Runs in
`autocommit_block()` at migration time **and** on every app boot via
`_ensure_postgres_enum_values()`. Idempotent via `IF NOT EXISTS`.
SQLite skipped.

### 3. Midnight auto-roll instead of "sit in Tomorrow until manually moved"

When tomorrow arrives, the user's intent "I'll do this tomorrow" is
now "I'll do this today." A scheduled APScheduler cron at **00:01
local time** (DIGEST_TZ) moves every ACTIVE Tomorrow task to Today.

Reason for 00:01 instead of 00:00: cron jobs scheduled at the boundary
are fiddly (DST transitions, scheduler tick alignment). One minute
past is unambiguous and makes it easier to reason about "did it
run?"

Archived / cancelled / deleted Tomorrow tasks stay put — rolling them
would resurrect end-states, which is surprising and has no user
benefit.

### 4. The roll function uses an isolated `Session(db.engine)`

Same pattern as `DBLogHandler._insert_record` (ADR-referenced in that
commit) and `_ensure_postgres_enum_values`. Called from the APScheduler
thread which has no request context — using the Flask-SQLAlchemy
shared `db.session` would invite cross-thread / cross-context
weirdness. A fresh session bound to the engine gives us our own
transaction, our own connection checkout, and transparent
`pool_pre_ping` recycling (#31).

### 5. Capture-bar shortcut: `#tomorrow`

Added to `parse_capture.js` `tierMap`. While there, also added
`#next_week` and `#nextweek` (the #23 backlog row claimed these
existed but they'd never been wired — found while auditing).

Scan order changed from declaration-order to **longest-first** with
**first-hit-wins**. Previously the loop walked all tier tags and the
last match overwrote earlier ones. That accidentally worked as long
as no pair of tags shared a prefix. `#week` is a substring of
`#next_week`, so a declaration-order-with-last-wins walk could
match `#week` then `#next_week` and land on `this_week` depending on
order in the object literal (JS objects are insertion-ordered but
brittle to rely on). Longest-first removes the ambiguity: the longest
matching tag is always the intended one.

Guarded by a regression test:
`test("multiple tier tags — longest tag wins …")` in
`tests/js/unit/parse_capture.test.js`.

### 6. Not day-grouped on the board

Tomorrow is a single-day surface like Today. `DAY_GROUPED_TIERS` in
`static/app.js` stays `{this_week, next_week}` only. Grouping a
single-day tier by weekday would produce exactly one group — wasted
chrome.

### 7. Digest gains a "TOMORROW: N tasks" line

Placed between "Goals with active tasks today" and "THIS WEEK
REMAINING." Mirrors the existing pattern: one-line count, no
per-task enumeration. If the user cares about the titles, they open
the app.

### 8. No UI treatment for "future-dated task in Tomorrow"

If a user puts a task in Tomorrow with a `due_date` five days out
(using Tomorrow as a "plan to tackle it tomorrow" signal), the
midnight roll still moves it to Today. The `due_date` stays what it
was. This is the simplest behaviour and matches the user intent
captured by the tier choice; the `due_date` is orthogonal metadata.

## Consequences

**Easy:**
- Additive. No existing code paths change shape.
- `/tier/<name>` already handles arbitrary `Tier` values via the
  abort(404)-on-invalid pattern, so `/tier/tomorrow` works without
  any route change (labels dict gets one new entry).
- `_ensure_postgres_enum_values` belt-and-braces gate already handles
  the PG enum class of bugs (ADR-011's post-mortem coverage).

**Hard / accepted trade-offs:**
- The midnight scheduler runs in APScheduler, which runs in gunicorn
  worker 1 (not all workers — intentional via `post_worker_init`).
  If worker 1 restarts exactly across midnight, one cycle's roll
  could be skipped. Low-probability, low-cost: the worst case is the
  user wakes up to tasks still in Tomorrow and has to move them
  manually once. If observed in practice, revisit with an
  at-request-time fallback.
- Timezone is user-configured via `DIGEST_TZ` (default
  America/New_York). If a user moves to a different timezone without
  updating the env var, the roll happens at the old local midnight.
  Same limitation as the digest today; not worth fixing until it
  actually bites.

## Alternatives considered

- **No auto-roll, manual move only.** Rejected — defeats the point
  of Tomorrow as a planning surface.
- **Roll "tomorrow" relative to due_date instead of tier.** Rejected
  — introduces semantic conflict between due_date (a hard deadline)
  and tier (a planning bucket). Keep them orthogonal.
- **Preview Tomorrow tasks in Today's panel the day before.**
  Considered; rejected as clutter. The Tomorrow panel already IS
  the preview — it's right above This Week on the same page.
- **Group Tomorrow by time-of-day (morning / afternoon / evening).**
  Over-designed for a MVP. Can add later if the user starts using
  Tomorrow heavily.

## Verification

- **Unit (Python)**: 3 new `TestRollTomorrowToToday` tests in
  `tests/test_tasks_api.py` — rolls active, skips archived, no-op
  when empty.
- **Unit (JS)**: 4 new parser tests in
  `tests/js/unit/parse_capture.test.js` — `#tomorrow`, no prefix
  collision with `#today`, `#next_week` + `#nextweek` alias,
  longest-wins regression guard.
- **Route**: existing `/tier/<name>` test parametrized to include
  `"tomorrow"` (6 → 7 params).
- **Template**: existing `test_contains_tier_sections` parametrized
  to include `"tomorrow"` and `"next_week"` (which was also
  missing — minor drive-by fix).
- **Integration**: Phase 6 manual regression — board renders 7 tier
  panels in order, `#tomorrow` capture routes a new task to the
  Tomorrow panel, `/tier/tomorrow` full-page view loads, the roll
  function moves 1 task end-to-end, digest preview shows
  "TOMORROW: 2 tasks". Mobile (375x812) clean, no overflow, no
  console errors.
