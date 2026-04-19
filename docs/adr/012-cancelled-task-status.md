# ADR-012: Cancelled task status (separate from completed)

Date: 2026-04-19
Status: ACCEPTED

## Context

Backlog #25 — until now, the only end-states for a task were
**ARCHIVED** ("done"), **DELETED** (recycled), and ACTIVE. There was
no honest way to record "I consciously gave up on this." Users either
marked give-ups as ARCHIVED (inflating completion stats — the very
thing this app is meant to track honestly) or DELETED them (losing
the audit trail). Backlog #25 fixes this with a fourth status,
**CANCELLED**, plus an optional reason field.

## Decisions

### 1. New `TaskStatus.CANCELLED = "cancelled"` enum value

Added to `models.TaskStatus` between ARCHIVED and DELETED. Naming
matches the existing lowercase-string convention. Migration follows
the precedent in ADR-010 (`ALTER TYPE … ADD VALUE IF NOT EXISTS` on
Postgres, dialect-guarded for SQLite, downgrade is a no-op).

### 2. New `tasks.cancellation_reason` column (NULL ok, ≤500 chars)

Stored separately from the existing `notes` column. Rationale: `notes`
is documentation about the task itself (rendered in the detail
panel's notes section); `cancellation_reason` is metadata about *why*
the task was dropped. Mixing them would (a) leak cancellation
context into reactivated tasks' notes, and (b) make it impossible to
search/report on cancellation reasons distinctly.

The column is nullable so the migration is non-blocking on a
populated table. Empty strings are normalised to NULL on PATCH.

### 3. Reason auto-clears when transitioning out of CANCELLED

Implemented in `task_service.update_task`: if a task moves from
CANCELLED → anything else AND the caller didn't explicitly set
`cancellation_reason` in the same PATCH, the field is wiped.
Rationale: a stale "Out of scope" explanation surviving on a
reactivated task is more confusing than a missing one. Callers that
want to preserve the reason across status flips can set it
explicitly in the same PATCH (used by the bulk endpoint for the
"Mark active" workflow if we ever want it).

### 4. Goal progress excludes CANCELLED from BOTH numerator and denominator

Updated `goal_service.goal_progress`: cancelled tasks no longer count
toward `total` OR `completed`. The percent calculation pretends they
don't exist. They're surfaced separately via a new `cancelled` field
on the response so the UI can show them.

The alternative — including them in `total` only — was rejected
because it punishes the user for the conscious-drop behaviour we're
trying to encourage. Excluding from both keeps the percent honest and
the user's decision-making visible.

### 5. Digest gains a "PAST 7 DAYS" line counting both completed + cancelled

Added to `digest_service.build_digest`. Single new line:

```
PAST 7 DAYS: <N> completed, <M> cancelled
```

Sourced from `Task.updated_at >= today − 7d` filtered by status. We
intentionally use `updated_at` (not a dedicated `completed_at` /
`cancelled_at` timestamp) — the simplification cost is low for a
single-user app, and adding two more datetime columns would be
overkill. If the user starts back-dating completions in bulk this
will be slightly wrong; revisit then.

### 6. New "Cancelled" board section, mirroring "Completed"

Twin of `tier-completed`: collapsed by default, lazy-loaded when
expanded, count badge in the header always reflects the filtered
view, no drag-and-drop. Restoration happens by opening the card in
the detail panel and PATCHing status back to ACTIVE — the deliberate
extra friction is correct for what is meant to be a reflective
end-state, not a casual gesture.

### 7. Bulk toolbar gets a "Mark cancelled" option (single shared reason)

The bulk Status dropdown now has three options: Mark complete (existing),
**Mark cancelled** (new), Mark active (existing). The cancelled action
shows a single `prompt()` for an optional reason that is applied to
every selected task. Per-task reasons can still be set later by
opening individual cards. We considered per-task reason inputs in the
toolbar but rejected — the bulk workflow's value is speed; nuanced
explanations belong in single-card flows.

## Consequences

**Easy:**
- Status filtering already worked via `?status=<value>` on the list
  endpoint, so no API changes were needed for the new fetch path.
- `cancellation_reason` slots into `_UPDATABLE_FIELDS` and the
  serializer with one line each.
- Existing Goal-progress consumers see the new `cancelled` key
  appear; backwards-compatible because they ignore unknown fields.

**Hard / accepted trade-offs:**
- The reason auto-clear behaviour is a small surprise that needs the
  ADR to find. Mitigated by an explicit unit test
  (`test_patch_uncancel_clears_reason`).
- Using `updated_at` for digest counts is approximate; any non-status
  PATCH on an already-cancelled task will refresh the timestamp and
  push it forward in the 7-day window. Acceptable for a personal
  digest; not for billing.

## Alternatives considered

- **Reuse the `notes` field for the reason.** Rejected — semantic
  pollution, search/reporting confusion, plus the reason should
  vanish on un-cancellation while notes shouldn't.
- **Add a `cancelled_at` timestamp column** alongside the reason.
  Rejected for now — `updated_at` is "good enough" for the digest
  use case and the personal app doesn't have audit-trail needs
  that justify two new datetime columns. Easy to add later if
  needed.
- **Keep CANCELLED hidden by default with a settings toggle to expose
  it.** Rejected — the whole point of the feature is honest tracking
  visible at a glance, not optionally-on telemetry.
- **Treat CANCELLED in goal progress like ARCHIVED.** Rejected — the
  user explicitly wants honest stats; merging the two collapses the
  exact distinction we just introduced.
