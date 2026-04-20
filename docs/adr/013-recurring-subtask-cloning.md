# ADR-013: Recurring subtask cloning via JSON snapshot

Date: 2026-04-20
Status: ACCEPTED

## Context

Backlog #26 — when a parent task has a recurring template, its subtasks
should respawn alongside the parent each cycle. The canonical use case
is a weekly review: the parent "Weekly review" recurs every Monday, and
each cycle should come back with its own fresh copy of subtasks like
"Check Today", "Review Goals", "Plan next week" — the same checklist
every week, not one-shots that disappear after the first cycle.

Before this change, `recurring_service.spawn_today_tasks` only cloned
parent-level metadata (title, notes, checklist, url, project_id,
goal_id). The spawned Task had no subtasks. Subtasks from the previous
cycle's parent stayed archived from that completion; new cycles got
empty parents. This broke the weekly-review pattern.

## Decisions

### 1. Snapshot pattern, not live lookup

Three options were considered:

- **(a)** Add a `subtasks_snapshot: JSON` column to `RecurringTask`,
  populated at template creation/update, consumed at spawn.
- **(b)** At spawn time, look up the most-recently-archived Task with
  this template's `recurring_task_id` and copy ITS current subtasks.
- **(c)** Hybrid: snapshot at template creation, but also refresh the
  snapshot automatically each time the parent is completed.

Chose **(a)**. Rationale:

- Matches the existing pattern on `RecurringTask`, where `notes`,
  `checklist`, and `url` are all snapshotted at template-creation
  time. Subtasks are metadata of the same kind — captured once,
  reused forever (until the user explicitly re-saves the repeat).
- No spawn-time query overhead. Spawn is already
  O(N_templates × N_tier_today_tasks); adding a lookup for every
  previous-cycle parent would multiply that.
- (b) couples spawn to the completion path: if the user deletes
  subtasks individually, or never actually "completed" the parent
  (e.g. the cycle auto-rolled), the source is gone. The snapshot
  survives independently.
- (c) is cleverer but over-automates. The user editing a subtask
  probably doesn't mean "update the recurring template" — that
  should be explicit (re-saving "Repeat" on the parent).

### 2. Minimal snapshot shape: `[{"title": str}, ...]`

Each entry is a dict with just `title`. Rationale:

- Forward-compatible — we can add `project_id`, `due_offset`,
  `sort_order` etc. later without breaking old rows.
- Matches what the existing `checklist` column does (list of
  dicts), so tooling is consistent.
- Avoids premature design: the only thing we're certain we want
  per-subtask right now is the title. Everything else (project,
  goal, due date) inherits from the parent at spawn time.

Spawned subtasks inherit `type`, `tier`, `project_id`, and `goal_id`
from the parent that was just spawned (not from the template
directly — the parent may have been edited). They do NOT inherit
`notes`, `checklist`, or `url` — those are parent-level
metadata and would clutter every subtask.

### 3. Only ACTIVE subtasks are snapshotted

`_snapshot_subtasks(parent)` filters by `status == TaskStatus.ACTIVE`.
If a subtask was completed / cancelled / deleted at the time the user
turned on "Repeat," that's a signal they don't want it in the cycle.
Archived subtasks from prior completions, transient experiments, and
cancelled tasks all get dropped.

### 4. Defensive parsing in both directions

- `recurring_service._clean_subtasks_snapshot` normalises any
  payload to `[{"title": str}]` — strips non-dict entries, missing
  titles, empty/whitespace titles, unknown keys. Called by
  `create_recurring` and `update_recurring` so the column always
  holds well-formed data.
- The spawn loop also defensively skips malformed entries, so rows
  that somehow got bad data from a direct DB write or a future
  schema change don't crash spawn.

### 5. Migration is trivial and backward-compatible

`b4c5d6e7f8a9_add_subtasks_snapshot` adds one nullable JSON column.
Existing RecurringTask rows get NULL, which the spawn loop treats as
"no subtasks to clone" — identical to pre-#26 behavior. No data
backfill, no downtime, no downgrade complexity.

### 6. SQLAlchemy relationship lazy-loading is fine here

`_snapshot_subtasks(task)` reads `task.subtasks`, a lazy-loaded
back_populated relationship. When called from `update_task` immediately
after PATCHing the parent, the subtasks already exist in the DB (they
were created via earlier POST requests, each committed) and the lazy
load returns them correctly. Verified via `test_repeat_snapshots_
active_subtasks` end-to-end and via Phase 6 manual regression.

## Consequences

**Easy:**

- Zero UI changes. The existing "Repeat" control in the task detail
  panel already drives `_apply_repeat`; that function now captures
  subtasks transparently.
- Opt-out for users who don't want subtasks to repeat is the
  existing workflow: remove subtasks from the parent BEFORE turning
  on Repeat, or remove and re-add Repeat to re-capture the current
  set.

**Hard / accepted trade-offs:**

- Stale snapshots: if a user adds a new subtask to the parent after
  turning on Repeat, the new subtask only applies to THIS cycle;
  the next cycle spawns from the (now-stale) snapshot. Fix: re-save
  the Repeat control on the parent to refresh the snapshot. Surface
  this in docs / tooltip if users hit it.
- No UI indication of what's in the snapshot. A future nice-to-have
  would be a "Subtasks that recur" preview in the detail panel when
  Repeat is active.

## Alternatives considered

- **Live lookup at spawn time**: rejected (see decision 1).
- **Auto-refresh snapshot on every parent mutation**: rejected as
  over-clever. The explicit "save Repeat" gesture is the right
  commitment point.
- **Nested RecurringSubtask table**: rejected as overkill for
  subtask titles. JSON snapshot is simpler and matches existing
  patterns.
- **Copy subtasks via the Task `checklist` JSON instead**: rejected
  because checklist items aren't full Tasks and can't be checked off
  independently with tier/due_date/status semantics. Subtasks are
  the right abstraction for an actual weekly-review workflow.

## Verification

- **Unit**: 6 new tests in `tests/test_recurring.py`
  (`TestSpawnWithSubtasks`) + 1 in `tests/test_tasks_api.py`
  (`test_repeat_snapshots_active_subtasks`). Cover empty snapshot,
  NULL legacy row, malformed entries, multi-cycle spawn, ID
  uniqueness across cycles.
- **Integration**: Phase 6 regression — Weekly Review pattern
  verified end-to-end: create parent with 3 subtasks, flip to
  daily repeat, archive the cycle, spawn, verify 3 fresh subtasks
  with new IDs and same titles. Repeated for a third cycle to
  confirm idempotency.
- **Full suite**: 963 passed, 3 skipped (0 new failures).
