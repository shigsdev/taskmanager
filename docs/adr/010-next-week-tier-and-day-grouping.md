# ADR-010: Next Week tier + day-of-week grouping

Date: 2026-04-19
Status: ACCEPTED

## Context

Backlog #23 asked for two tightly-linked features:

1. **A "Next Week" tier.** Today only has Today / This Week / Backlog /
   Freezer / Inbox. There's no forward-looking surface for tasks
   scheduled in the 8–14 day window — those either cram into This Week
   (making it crowded) or sit in Backlog (losing the "next up" context).
2. **Day-of-week grouping.** When This Week or Next Week have multiple
   tasks, grouping them under Monday / Tuesday / … headings turns a
   flat list into a visual calendar. Undated tasks still need a home.

## Decisions

### 1. Tier order

Board order is now: **Inbox → Today → This Week → Next Week → Backlog →
Freezer**. Next Week sits between This Week and Backlog so it reads
chronologically.

`models.Tier` is a `StrEnum`; enum members are conventionally
unordered. The display order lives in `static/app.js TIER_ORDER`. The
new `NEXT_WEEK = "next_week"` member was appended in `models.py` with
a comment pointing at the JS array for the canonical order.

### 2. Postgres migration

Adding an enum value to a Postgres ENUM type requires
`ALTER TYPE … ADD VALUE …`. We use `IF NOT EXISTS` for idempotency
and guard on `bind.dialect.name == 'postgresql'` so SQLite test
environments (which store enums as strings) skip the DDL. Downgrade
is a no-op — dropping enum values in Postgres requires recreating the
type and migrating every column, which is not worth automating for a
single-user app.

### 3. Day-grouping applies on BOTH the board AND the tier-detail page

We debated keeping the grouping only on the dedicated
`/tier/this_week` / `/tier/next_week` pages — the board panels are
narrow and the chrome could crowd them.

Decided to include grouping on the board too. Rationale: if the user
can see day-of-week labels only on the dedicated page, the board view
loses a cue that's useful at a glance. Consistency wins over marginal
density savings. CSS keeps the board headings compact (0.85rem,
uppercase, tight margins) and the detail-page headings spacious
(1rem, normal case, more margin).

### 4. Monday-first ordering, not today-first

A "today-first" order (e.g. if today is Thursday, show Thu / Fri / Sat
/ Sun / Mon / Tue / Wed) was considered. Rejected because the week
shape would visually shift every day, breaking muscle memory.
Monday-first keeps the structure stable regardless of when the user
opens the page. "No date" tasks go at the bottom.

### 5. Pure function in its own module (`static/day_group.js`)

`groupTasksByWeekday()` takes a task list and returns a list of
`{label, tasks}` groups. Extracted to its own file — loaded via a
`<script>` tag before `app.js` in both `templates/index.html` and
`templates/tier.html`, and required via `require()` in Jest tests
(`tests/js/unit/day_group.test.js`, 9 tests covering empty input,
all-undated, day ordering, Sunday-last invariant, mixed, malformed
date, local-time parsing).

Parses `YYYY-MM-DD` strings as local-time (`new Date(y, m-1, d)`)
instead of UTC (`new Date("YYYY-MM-DD")` auto-parses as UTC). A task
due 2026-04-20 is Monday on every viewer's wall clock — not Sunday
for PT users.

Malformed date strings fall into the "No date" bucket instead of
crashing, so a corrupt or client-side-bad due_date value still gets
the card rendered.

## Consequences

**Easy:**
- New tier slot is fully integrated everywhere (capture bar accepts
  `#next_week` via existing `parseCapture`, tier-detail page works via
  the `/tier/<name>` route from ADR-009, bulk-select toolbar includes
  Next Week in the tier dropdown)
- Board and tier pages use the same `renderTierGroupedByDay` function
  via the shared `renderBoard` dispatch — zero duplication
- Jest unit tests catch grouping bugs in <1 second without a DOM

**Hard / accepted trade-offs:**
- The board is now 1 column taller on the task side. Fine at scale
  (~dozen tasks per tier) but worth revisiting if a future user has
  a screen too short to see Backlog + Freezer without scrolling.
- Grouping applies even when This Week is tiny (2-3 tasks). A
  3-task week with 1 heading per task looks heading-heavy. We keep
  it for consistency — the alternative "only group when ≥N tasks"
  rule was judged too clever to justify.

## Alternatives considered

- **Separate ordering for tier-detail pages** (e.g. today-first on the
  dedicated view). Rejected — inconsistency between board and detail
  page is worse than either alone.
- **Grouping in task_service** (server-side). The group structure is
  presentation, not data — it's cheaper and more testable to group
  client-side.
- **Showing the actual date next to the day name** ("Monday 2026-04-20").
  Adds clutter; the day name alone is enough context when the tier
  itself bounds the week. Could be added as a tooltip later.
