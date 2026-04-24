# ADR-029: Promote planning-tier tasks to TODAY when due_date arrives

Date: 2026-04-24
Status: ACCEPTED

## Context

Bug #46 — reported during the #44 ship on Friday 2026-04-24:
"friday task for Meds shows due today in this week panel but not in
today."

Reproducer:
- Meds task has a recurring template (weekly Friday)
- User manually moved the spawned task to `this_week` tier with
  `due_date = 2026-04-24` (Friday) for planning purposes
- Friday morning at 00:05, the recurring-spawn cron correctly
  skipped creating a TODAY duplicate (per ADR-026's cross-tier
  dedup on `(recurring_task_id, due_date)`)
- Result: This Week panel shows the task labeled "due today"; Today
  panel is empty for Meds

ADR-026 was right not to spawn a duplicate. But the user's expectation
was reasonable: "if a task is due today, it should be in Today." The
gap is that #38's fix prevents duplicates without doing the
reverse — promoting the existing planning-tier task to TODAY when
its date arrives.

The ADR-014 (#27) `tomorrow-roll` cron already does this exact pattern
for the TOMORROW tier: when the date a tomorrow-tagged task is committed
to arrives, the task moves to TODAY. This ADR extends the same logic
to the planning tiers (this_week / next_week / backlog).

## Decisions

### 1. New cron `promote_due_today` at 00:02

Sandwiched between the existing 00:01 `tomorrow_roll` and the 00:05
`recurring_spawn`:

- **00:01 — tomorrow-roll** (ADR-014): Tomorrow → Today (date-tagged tier promotes)
- **00:02 — promote-due-today** (this ADR): {this_week, next_week, backlog} where due_date=today → Today
- **00:05 — recurring-spawn** (ADR-026): templates firing today → new tasks in Today (skipping any already there)

Order matters: by the time `recurring_spawn` runs at 00:05, any
planning-tier task that became due today has already been promoted to
TODAY. The cross-tier dedup in #38 then sees it in TODAY (not its
former tier) and still correctly skips spawning a duplicate.

### 2. Exclude INBOX and FREEZER from promotion

Tier inclusions: `THIS_WEEK`, `NEXT_WEEK`, `BACKLOG`. These are all
"planning shelf" tiers — the user has assigned them work but parked
the actual scheduling decision.

Excluded:

- **TODAY** — already there (no-op).
- **TOMORROW** — covered by the 00:01 cron.
- **INBOX** — represents "needs triage." Auto-promoting bypasses the
  user's chance to decide whether the task even belongs on the board
  for today, which is the whole point of the inbox.
- **FREEZER** — represents "explicitly parked, don't bug me." The
  user's freeze decision outranks a date that may have been left over
  from before they froze it.

### 3. ACTIVE-only

Only `status == ACTIVE` tasks promote. Resurrecting an
archived/cancelled task into TODAY would be surprising and almost
certainly unwanted.

### 4. On-write hook for mid-day edits

The cron only fires once a day. If a user changes a task's `due_date`
to today at 2pm, they shouldn't have to wait until 00:02 the next
morning for the promotion. So `task_service.update_task` and
`task_service.create_task` also call a new helper
`_auto_promote_tier_on_due_today(task, data)` that does the same
promotion synchronously.

The on-write hook has one extra guard the cron doesn't need: **if
the user explicitly set `tier` in the same payload, don't auto-promote.**
That covers the legitimate "I want to plan this for today but track it
in This Week" pattern where the user sets both fields explicitly. The
cron has no such payload context — it just runs over the world; it
will promote everything matching the criteria.

### 5. Symmetric with #28, but inverse direction

ADR-016 (#28) added `_auto_fill_tier_due_date`: setting tier=TODAY
auto-fills due_date=today. This ADR adds the inverse:
`_auto_promote_tier_on_due_today`: setting due_date=today auto-promotes
tier to TODAY (when in a planning tier).

Together they enforce: **"Today panel = today's actual workload."**
Either direction of the binding (tier-first or date-first) ends up at
the same single source of truth.

## Consequences

**Easy:**
- Closes #46 cleanly.
- Single source of truth: Today panel = today's actual work.
- Reuses the proven `roll_tomorrow_to_today` pattern (isolated session,
  ACTIVE-only, returns rowcount).
- Mid-day edits work the same as morning cron — no surprise gap.

**Accepted trade-offs:**
- A user who parks a task in `this_week` with `due_date=today` (not
  via tier change but because they updated the date alone) will see
  the task move to TODAY on next request — possibly unexpected. Guard:
  if they explicitly set tier in the same update, we respect their
  choice; if they only set due_date, we infer the promotion.
- The cron runs unconditionally each night even when there's nothing
  to promote (rowcount=0). Acceptable — single-user app, the SQL is
  one cheap UPDATE with a tier+date+status filter.
- A future fourth promotable tier (if we ever add one) requires
  updating `_PROMOTABLE_TIERS_ON_DUE_TODAY`. The cron uses the same
  set so they stay in sync via the constant.

## Alternatives considered

- **Show other-tier tasks in the Today panel without moving them**:
  rejected. Same task appearing in two places confuses "which is the
  real one" and breaks the mental model of "tier = where this lives."
- **Add a visual cue only** ("3 in Today + 2 due today elsewhere"):
  rejected. Doesn't solve the friction — user still has to look in
  two places.
- **Promote at request time instead of via cron**: rejected. Means
  every page load runs an UPDATE, with no clear win. The cron + on-
  write hook combination covers all cases without per-request cost.
- **Include FREEZER in promotion**: rejected. Freezer means
  "explicitly off the board"; a date there is a soft reminder, not a
  commitment.
- **Run a single combined cron at 00:00 covering tomorrow_roll +
  promote_due_today + recurring_spawn**: rejected. Three separate
  jobs are easier to reason about, easier to disable individually if
  one regresses, and the 00:01/00:02/00:05 spacing leaves DST jitter
  headroom.

## Verification

- New tests in `tests/test_promote_due_today.py`:
  - Cron promotes this_week → today (Meds reproducer)
  - Cron promotes next_week → today
  - Cron promotes backlog → today
  - Cron skips inbox + freezer
  - Cron skips non-active tasks (archived / cancelled)
  - Cron skips tasks with future due_date
  - Cron skips tasks with no due_date
  - Cron is idempotent (running twice does nothing the second time)
  - On-write hook promotes when user PATCHes due_date=today
  - On-write hook respects explicit tier override in same payload
  - On-write hook fires from create_task too
- ARCHITECTURE.md scheduler section lists the new cron with its
  excluded-tiers rationale.
- arch_sync_check passes: `promote_due_today` is the new
  scheduler.add_job id, mentioned in ARCHITECTURE.md verbatim.
