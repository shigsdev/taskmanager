# ADR-018: Parent-task link on subtask detail panel

Date: 2026-04-20
Status: ACCEPTED

## Context

Backlog #30 — the task detail panel already hid the entire Subtasks
section when the currently-open task has a `parent_id` (subtasks
can't have subtasks; one level deep). But there was nothing replacing
it. A user viewing a subtask had no way to jump back to the parent
without closing the panel, finding the parent on the board, and
clicking it.

## Decisions

### 1. New `parent-link-section` in the shared detail partial

One new block in `templates/_task_detail_panel.html`, rendered inside
the form between `.checklist-section` and `.subtask-section`. Hidden
by default (`style="display:none"`); app.js toggles it on when
`task.parent_id` is set. Inverse of the existing subtask-section
toggle — the two swap depending on whether the task is a parent or a
subtask.

Placement rationale: the parent link is metadata about the task's
hierarchy, same conceptual group as "Subtasks." Keeping both
sections adjacent (one visible at a time) preserves the mental model.

### 2. Client-side cache lookup first, API fallback second

`taskDetailPopulateParentLink(parentId)`:

1. Looks up parent in `allTasks` (the board's active-only cache).
2. If not found (usually because the parent is archived / cancelled /
   deleted), does a single `GET /api/tasks/<parent_id>` fallback.
3. Renders a clickable `<a>` with title + click handler
   `taskDetailOpen(parent)`.

The fallback is important because the most common "where's my
parent?" scenario is "I just completed the parent and now I'm
cleaning up its leftover subtasks" — the parent is archived and no
longer in `allTasks`.

### 3. Status badge for non-active parents

If `parent.status !== "active"`, render a small colored badge after
the link: `completed` / `cancelled` / `deleted`. Visual hint that
clicking opens a task the user has since marked done or dropped —
prevents the "wait, why is this open?" moment.

Colors match the existing status conventions:
- `archived` (completed) → green background
- `cancelled` → orange background
- `deleted` → red background

### 4. Click handler opens the parent's detail panel directly

Uses the existing `taskDetailOpen(parent)` — same code path as clicking
any task card. So the parent's detail panel fully renders (including
its Subtasks section, now visible because the parent IS a parent).
Re-entrant: the user can bounce between parent and subtasks freely.

## Consequences

**Easy:**
- One template block, one small JS function (~40 lines), CSS is
  mostly mirroring subtask-section styling.
- Works on every page that loads the detail panel (board, `/tier/<name>`,
  `/completed`, etc.) because the partial is shared.
- No backend change. `GET /api/tasks/<id>` already returns the full
  task regardless of status (the route has no status filter).

**Hard / accepted trade-offs:**
- For a subtask whose parent has been hard-deleted (`status=deleted`,
  which we currently only use for bulk-import undo — regular delete
  is hard-delete), the fallback `GET /api/tasks/<parent_id>`
  returns 404. The UI shows "Parent task not found." Acceptable
  degraded state; shouldn't happen in practice under normal use.
- One extra API call when viewing a subtask whose parent isn't
  cached. Milliseconds on a warm pool. No perceivable UX impact.

## Alternatives considered

- **Breadcrumb-style path at the top of the panel** (`Parent Project
  / First step`): richer but redundant given the title is right
  there. Saved for if we ever do deeper hierarchies (currently capped
  at one level).
- **Dedicated "Up" button in the detail-actions row**: less
  discoverable and less informative (no title, just an arrow).
  Rejected.
- **Inline subtask view inside the parent's panel** (no navigation
  needed): rejected — the current "click subtask → open subtask's
  own panel" flow is already good; adding inline editing of subtasks
  in the parent panel is a separate feature.

## Verification

- **Unit**: 1 new `test_contains_parent_link_section` markup assertion.
- **Phase 6** desktop + mobile:
  - Subtask click → parent link renders with correct title
  - Parent-link click → parent's detail panel opens, subtask section
    visible (parent has subtasks)
  - Archive the parent, reopen subtask → link still renders, badge
    shows "completed" with the archived-green styling
  - Mobile (375x812): section fits at 334px, no overflow, 0
    console errors
