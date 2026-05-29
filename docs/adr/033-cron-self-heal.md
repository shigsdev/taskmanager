# ADR-033: Scheduler self-heal — replay missed nightly crons at boot

Date: 2026-05-28
Status: ACCEPTED
Supersedes: none (closes the loop on #166's manual replay path)

## Context

The app has four nightly maintenance crons (#27, #46, #108, #35):

  - 00:01 `tomorrow_roll`
  - 00:02 `promote_due_today`
  - 00:03 `realign_tiers_with_due_dates`
  - 00:05 `recurring_spawn`

These reconcile board state every night so the user opens to a
correctly-tiered Today + freshly-materialised recurring tasks.

When Railway has a midnight outage (#204, 2026-05-19) — or any other
event that takes the container down across 00:00-00:05 — the
APScheduler instance is gone during the fire window. Each missed
cron stays missed until the next 24h cycle: tasks in Tomorrow stay
in Tomorrow, today-due items don't promote, recurring tasks don't
spawn, etc. The user sees a "broken" board the next morning with no
indication why.

#166 shipped `scripts/run_missed_crons.py` as a manual replay path
the operator can run from `railway ssh`. It works, but requires the
operator to remember to run it. The 2026-05-20 incident note in #166
proves this is fragile under outage pressure.

We need the same replay to happen automatically — at container boot,
before normal traffic is served — so a missed midnight fire heals
itself the moment the container comes back up.

## Decision

Add a single-row-per-job `cron_audit` table tracking each job's
`(last_fire_at, last_status, last_rowcount, last_elapsed_ms)`. The
scheduler closure in `app.py:_start_digest_scheduler` writes a row
after every fire. At boot, after `scheduler.start()`, run
`cron_audit_service.replay_missed()` which walks the same
`cron_jobs.JOB_ORDER` table the scheduler uses:

```
for (job_id, hour, minute, spec) in JOB_ORDER:
    scheduled_today = today at HH:MM
    if now < scheduled_today:
        skip                   # cron hasn't been due yet today
    elif last_fire_at >= scheduled_today:
        skip                   # already ran today
    else:
        run helper inline + record(last_fire_at=now)
```

Per-job try/except so a failure on (say) `promote_due_today` does
not block `realign_tiers_with_due_dates` and `recurring_spawn` from
running. All WARNING-level logs land in `app_logs` via DBLogHandler,
so `/api/debug/logs` shows the catch-up alongside real fires.

The replay loop runs **only in the scheduler worker** (worker 1 in
gunicorn pre-fork). Other workers never invoke it. The replay
itself is wrapped in `try/except` so even a hard failure in
`replay_missed` cannot stop the scheduler from coming up and serving
normal traffic for the rest of the day.

The shared `cron_jobs.JOB_ORDER` table — moved out of
`app.py` and `scripts/run_missed_crons.py` to a top-level
`cron_jobs.py` module — guarantees the three replay surfaces
(live scheduler / boot-time self-heal / manual operator script) all
iterate identical tuples.

## Risks considered

### R1. Deploy-during-the-fire-window race

If a deploy lands at 00:00:30 and the new container boots at 00:00:45,
`tomorrow_roll` (00:01) has NOT fired yet today — `last_fire_at`
shows yesterday's value. Naively the replay would run `tomorrow_roll`
once at boot, then the real 00:01 cron would run it again 15
seconds later — double-fire.

**Mitigation**: the replay treats "scheduled time is in the future
today" as "do nothing — let the cron fire normally". The check
`if now < scheduled_today: skip` covers this. The 00:01-00:05
window is the entire vulnerable surface; deploys that land outside
it never trigger this race.

Tested by `test_future_today_skipped`.

### R2. Multi-worker race

Gunicorn runs multiple workers (`--workers 2+`) but APScheduler is
only started in worker 1 via `post_worker_init`. The replay must
also only run in worker 1, or two workers race to run the helpers
(both would issue concurrent `UPDATE tasks` statements).

**Mitigation**: `replay_missed()` is invoked from
`_start_digest_scheduler` itself, which is gated to worker 1 by the
existing `post_worker_init` hook. Other workers never enter the
function and never trigger replay.

### R3. Cold-start latency

Four helpers running synchronously before serving traffic adds to
container cold-start time. On Railway, the LB health-check runs
against `/healthz` so the cold-start delay shows up there too.

**Measurement**: each helper individually completes in <500ms on
prod data (per existing `Manual cron run report` observations).
Worst-case all-four = ~2s, which is well inside Railway's
`healthcheckTimeout = 120` budget. Acceptable.

If a future helper becomes slow, the replay could be moved to a
post-`scheduler.start()` background thread instead of the
synchronous path. Not needed today.

### R4. Audit write failure cascading into cron failure

If `cron_audit.record()` raises, the cron work has already happened
— rolling it back via raising would lose the user-visible work.

**Mitigation**: `record()` is wrapped in `try/except` that rolls
back the session on failure but never raises. Audit-write failure
is logged at ERROR and surfaces in `/api/debug/logs`. The cron's
own observable side effects (rows updated) are preserved.

## Consequences

**Positive:**

- A Railway outage at midnight self-heals on the next boot — the
  user never has to remember `scripts/run_missed_crons.py`.
- The shared `cron_jobs.JOB_ORDER` table eliminates the drift
  between live scheduler and manual script that #168/#169
  surfaced (the old script renamed `realign_tiers_with_due_dates`
  to `realign_tiers` locally; the table now uses one ID per job).
- `cron_audit` rows give the operator a forensic trail of "did
  this job actually run today, and how long did it take" without
  digging through APScheduler logs. Useful for future
  performance-drift investigation.
- The manual `scripts/run_missed_crons.py` path remains as a
  fallback for cases the auto-replay misses (e.g. operator wants
  to re-run a specific date for `recurring_spawn` via `--date`).

**Negative:**

- One more table to maintain. Counter: the schema is tiny
  (5 columns, 4 rows total) and changes rarely (only when
  `JOB_ORDER` itself changes).
- Boot-time latency adds 0-2s when the replay actually runs.
  Counter: this only fires on the day of an actual missed cron;
  on every other boot the loop walks 4 rows and skips them all
  in <10ms.
- A future addition to `JOB_ORDER` requires updating
  `_SCHEMA_DESCRIPTIONS` + `_ER_TABLE_GROUPS` + the architecture
  drift tests will catch it. That's a cascade-rule cost — the
  existing CLAUDE.md cascade table already covers
  `models.py` + `architecture_service.py`.

## Related

- #166 (RESOLVED) — the manual `scripts/run_missed_crons.py`
  predecessor.
- #168 + #169 (RESOLVED) — usability polish on the manual script:
  fast-fail DNS pre-flight + executable shebang. The shared
  `cron_jobs.JOB_ORDER` factor-out lives in this ADR; #168/#169
  shipped a few hours earlier on the same day.
- #204 — Railway resilience options. The original incident that
  motivated all three (#166, #167, #168/#169).
- `health.write_scheduler_heartbeat` — the existing 45-second
  liveness probe. `cron_audit` complements it: heartbeat proves
  the scheduler is alive *now*; `cron_audit` proves each nightly
  job has fired today.
