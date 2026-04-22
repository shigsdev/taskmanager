# ADR-026: Recurring spawn — set due_date + cross-tier dedup

Date: 2026-04-22
Status: ACCEPTED

## Context

Backlog #38. Two latent issues in `recurring_service.spawn_today_tasks`
surfaced on 2026-04-22 while diagnosing why a "Meds" task with a
weekly-Friday repeat showed `due 2026-04-24` in the This Week panel
while other weekly previews didn't:

**Gap A — missing due_date on spawned tasks.**
ADR-016 (#28) introduced `_auto_fill_tier_due_date` so that
manually-created TODAY tasks get `due_date=today` automatically
(and TOMORROW tasks get `due_date=tomorrow`). The fill applies in
`task_service.create_task` and `task_service.update_task`. But
`spawn_today_tasks` constructs Tasks DIRECTLY via the SQLAlchemy
constructor — bypassing `create_task` — so cron-spawned tasks
landed with `due_date=None`. Result: a TODAY-tier board mixed two
classes of task (manually created with due_date set, cron-spawned
with due_date null). Visible inconsistency, harder to reason about
the "tasks for this date" question.

**Gap B — title-only dedup misses cross-tier duplicates.**
The old idempotence check was:

```python
existing_titles = {t.title for t in active TODAY tasks}
if rt.title in existing_titles: skip
```

Two failure modes:
1. **Cross-tier**: a task with the same `recurring_task_id` parked
   in `this_week` (the planned-ahead "Meds due Friday" case) was
   invisible to the dedup. On Friday, the cron spawned a TODAY
   duplicate next to the existing this_week task.
2. **Title fragility**: a user editing the spawned task's title or
   the template's title between cycles broke the dedup. Title
   isn't the right key for "is this template's instance already
   present"; the (template_id, fire_date) pair is.

The preview-collision filter from #34 in `compute_previews_in_range`
already used `(recurring_task_id, due_date)` as one of its keys —
the spawn dedup is now consistent with that semantic.

## Decisions

### 1. Spawn sets `due_date=target_date` on parent + subtasks

The new Task constructor call passes `due_date=target_date`. Subtask
spawn (#26) mirrors the parent's date for the same consistency
reason — a subtask of "Weekly review" landing in TODAY without a
date but its parent having one would be jarring.

The fill is unconditional, not "fill-if-null" like #28 — there's no
existing user-set value to preserve because the Task didn't exist
five lines earlier.

### 2. Default `target_date = _local_today_date()`

The function already accepted `target_date` as a kwarg but defaulted
to `None`, with `tasks_due_today` falling back to `date.today()`
(server UTC). Both production callers (the cron in `app.py:589` and
the manual API endpoint `recurring_api.py:129`) pass no args.

For the OLD code path this didn't matter much because `due_date`
wasn't being set. For the NEW code path, due_date IS being set, so
TZ correctness matters: a 10pm-ET cron run with `date.today()` =
UTC-tomorrow would create tasks dated tomorrow.

Switched the default to `task_service._local_today_date()` (the same
helper used by #28 and the Tomorrow auto-roll cron). Three TZ paths
now stay self-consistent.

### 3. Dedup keyed on `(recurring_task_id, due_date)` across all tiers

```python
existing_keys = {
    (t.recurring_task_id, t.due_date)
    for t in active tasks WHERE
        recurring_task_id IN templates_firing_today
        AND due_date == target_date
}
if (rt.id, target_date) in existing_keys: skip
```

The query filters on `status == ACTIVE` so completed/cancelled tasks
don't block new spawns (a completed weekly-review on Friday
shouldn't suppress next Friday's spawn — different fire_date — and
shouldn't suppress today's spawn either if today happens to share a
date by some edge case).

Pre-fetching one set of keys before the per-template loop is O(N+M)
instead of O(N*M); for typical user scale (tens of templates, single-
digit active spawns per day) this is moot, but it sets the right
shape for any future scale.

### 4. Subtask spawn pass also gets `due_date=target_date`

The subtask spawn block (added in #26) has its own Task constructor.
Updated to mirror the parent's `due_date`. Without this update,
weekly-review subtasks would land in TODAY with `due_date=None` while
their parent has it set — same Gap A inconsistency at the subtask
level.

## Consequences

**Easy:**
- Spawned tasks now visually match manually-created TODAY tasks
  (both have due_date set) — no more two-class TODAY board.
- The "Meds case" (planned-ahead in this_week + cron fires same
  date) no longer duplicates.
- Behavior aligns with `compute_previews_in_range` (#34) which
  already used the same dedup key.
- The legacy idempotent-spawn test (`test_spawn_idempotent_no_duplicates`)
  continues to pass — the SECOND spawn now hits the new dedup key
  on the first spawn's (rt_id, today) tuple, same outcome.

**Accepted trade-offs:**
- The dedup query is per-spawn-call (one SELECT) instead of one
  SELECT per template. Net better; trade-off is null.
- A task whose `recurring_task_id` was unset by hand (rare — there's
  no UI to do it, only a direct DB write) would no longer dedup.
  Acceptable — that's a deliberate user override of the template
  link.
- Tasks created without `due_date` (e.g. manually-created in INBOX
  via a recurring template — no UI for this either) wouldn't be
  caught by the dedup. Same answer: the relevant production paths
  all set `due_date` per #28's auto-fill.

## Alternatives considered

- **Route spawn through `create_task` instead of bare constructor**:
  rejected. `create_task` runs auth, validation, request-context
  side effects (logging, request-id). The cron has no request
  context. Refactoring `create_task` to be context-agnostic is a
  much larger change for a 2-line bug fix.
- **Title-and-tier dedup (TITLE in TODAY ∪ THIS_WEEK ∪ TOMORROW)**:
  rejected. Still title-fragile, and "active in any tier" was
  already the desired semantic — the right key is template_id +
  due_date, not the user-mutable title.
- **Move dedup to a DB UNIQUE constraint on (recurring_task_id,
  due_date) WHERE status = 'active'**: considered. Postgres partial
  unique indexes work but add a migration, fail loudly on legitimate
  edge cases (user forks a template into two manual tasks for the
  same date), and the application-layer dedup is sufficient at
  single-user scale.
- **Skip-if-completed-today instead of dedup-by-key**: rejected.
  Doesn't address Gap B at all.

## Verification

- 4 new tests in `tests/test_recurring.py::TestSpawnDueDateAndCrossTierDedup`:
  - `test_spawned_task_has_due_date_set` — Gap A
  - `test_spawn_skipped_when_planned_ahead_in_this_week` — Gap B,
    the literal "Meds" reproducer
  - `test_spawn_dedup_keys_on_due_date_not_just_title` — confirms
    yesterday's leftover doesn't block today's spawn
  - `test_spawn_dedup_ignores_completed_tasks` — confirms
    yesterday's COMPLETED task doesn't block today's spawn
- All 65 existing recurring tests still pass.
- All 88 spawn/recurring/preview/scheduler tests still pass.
- `compute_previews_in_range` (#32/#34) is untouched and still
  uses `(recurring_task_id, due_date)` as one of its collision
  keys — semantics now match end-to-end.
