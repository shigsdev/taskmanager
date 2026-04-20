# ADR-015: Recurring-template previews in This Week / Next Week

Date: 2026-04-20
Status: ACCEPTED

## Context

Backlog #32. Before this change, This Week and Next Week showed only
real Task rows. Recurring templates (e.g. a Friday "Weekly review")
were invisible until their spawn day — meaning a user opening the app
on Monday couldn't see "the weekly review is coming Friday" without
going to a separate page and eyeballing each template's schedule.

The 2026-04-20 conversation produced a two-option fork:

- **Option A**: render read-only "preview" cards for recurring
  templates inside This Week / Next Week day-groups, driven by an
  on-the-fly compute.
- **Option B**: spawn recurring instances a week ahead of time,
  flagged as `scheduled`, so they're real Task rows.

A was chosen — preserves the existing "template is the source of
truth, Task is materialised only on spawn" model and avoids the
state-ambiguity problem ("did I complete this future-dated Task or
the current cycle's?").

An interactive mockup was built at
`docs/mockups/32-recurring-preview.html` showing three visual
treatments (dashed border, ghost-blue tint + badge, muted opacity).
User picked dashed border + answered six open design questions in
one pass.

## Decisions

### 1. New `GET /api/recurring/previews?start=&end=` endpoint

Returns a list of `{template_id, title, type, frequency, project_id,
goal_id, fire_date, notes, url}` items for every active template that
fires in the inclusive `[start, end]` date range. Server-side
computes the fire days (reusing `_template_fires_on` from
`spawn_today_tasks`) and pre-filters two things:

- Inactive templates (`is_active = False`) — never previewed.
- **Same-day spawn collisions** — if a real Task already exists with
  `recurring_task_id == template.id` AND its `created_at.date()`
  falls in the range, the preview for that specific day is dropped.
  Otherwise the user would see a phantom preview card next to the
  real Task it just spawned.

Range is capped at 31 days server-side — prevents accidental
year-long sweeps. Client uses a 14-day window (today through
today+13) which covers both This Week and Next Week.

### 2. Client fetches previews in parallel with tasks/goals/projects

`loadRecurringPreviews()` runs inside the same `Promise.all` as the
existing load functions in `init()`. Initial `renderBoard` happens
after all four resolve so previews are available on first paint.

Failure is non-fatal: a network error logs a warning and leaves
`allPreviews` empty — the board still renders real tasks.

### 3. Previews merge into the existing day-group structure

`renderTierGroupedByDay` was extended to:

1. Call `_previewsForTier(tier)` which filters `allPreviews` to the
   tier's inclusive date range (This Week = this Monday–Sunday, Next
   Week = next Monday–Sunday, computed from JS local time).
2. Also apply the same `currentView` / `projectFilter` the real tasks
   obey. A Work view hides Personal-type previews and vice versa.
3. Bucket each preview into the day-group its fire_date falls in,
   appending to existing groups (so Tuesday's real task and Tuesday's
   preview render next to each other) and creating new groups for
   preview-only days.
4. Preserve the Monday-first ordering established by ADR-010.

### 4. Counts in day-group headings exclude previews

`Tuesday (3)` means three real tasks. Any preview cards visible below
that heading are "coming up, not on your plate yet." Rationale: the
count is a workload indicator — including previews would overstate
actionable load. Matches the honest-stats spirit of #25 (cancelled
excluded from goal progress).

The user picked this explicitly in the 2026-04-20 chat with "Option 1
and I can revert to something later if need be after I exercise it."

### 5. Empty-state bypass for preview-only weeks

`renderBoard` previously early-returned with an empty-state message
when `tasks.length === 0`. That broke the "Next Week has no real
tasks but 14 recurring previews" case — the previews would never
render. Fixed by also computing preview count for day-grouped tiers
before deciding whether to empty-state.

### 6. Visual treatment: dashed border (Treatment A from mockup)

`.preview-card` class: `2px dashed #9ca3af`, `#fafafa` background,
slightly muted text color. Hover darkens the border. Cursor is
pointer (clickable). Explicitly `draggable=false` so browsers don't
inherit `.task-card`'s draggable behaviour. A, B, and C treatments
are all viewable in the committed mockup file for future reference.

### 7. Click behaviour: open the most-recent spawned Task's detail panel

Rationale: we don't have (yet) a dedicated recurring-template editor
page. The existing Task detail panel has a "Repeat" dropdown that
already edits the linked template. So clicking a preview:

1. Fetches `/api/tasks?status=all`.
2. Finds the most-recently-updated Task whose
   `repeat.template_id` matches the preview's `template_id` (needed
   a one-line addition to `tasks_api._serialize_repeat` to include
   `template_id`).
3. Opens that Task's detail panel via `taskDetailOpen(task)`.
4. Fallback: no past spawn exists (brand-new template) → friendly
   `alert()` telling the user when it'll first appear and that they
   can create a manual task + set Repeat if they want to edit the
   template sooner.

Scope guard: a dedicated `/recurring` editor page is future work
(probably its own backlog item when it bites) — the click fallback is
good enough for now.

### 8. No drag, no bulk-select, no tier buttons

Preview cards are read-only UI. Drag is disabled via
`draggable=false`. Bulk-select checkboxes aren't rendered because
`_previewCardEl` doesn't include the `.bulk-select-check` the normal
`taskCardEl` does. Tier buttons aren't included. Click goes straight
to the template-edit flow above.

## Consequences

**Easy:**
- Zero schema change.
- Compute is O(days_in_range × active_templates) — on the order of
  14 × 10 = 140 calls to `_template_fires_on` per board load. Trivial.
- Spawn logic is unchanged; previews are a rendering layer on top.

**Hard / accepted trade-offs:**
- Click → open-most-recent-spawn → edit Repeat settings is a
  three-step mental model. If a user hasn't used Repeat before, the
  fallback alert's instructions ("create a manual task + set Repeat")
  are clunky. Acceptable until someone hits it enough to warrant a
  standalone editor page.
- Preview count could be large with many templates + long frequencies.
  14 × 10 = 140 cards on the board if everything is daily. Day-grouped
  rendering keeps it legible; if a user complains we can add a
  collapse-per-day UX.
- The preview merge uses JS local-time to bucket fire_dates by
  weekday, matching the existing day-group pattern (ADR-010). Users
  near UTC day boundaries still get correct bucketing.

## Alternatives considered

- **Option B (spawn a week ahead)**: rejected — state ambiguity.
- **Dedicated `/recurring` editor page + click-opens-editor**:
  scope expansion; deferred to a future backlog item.
- **Counts include previews**: rejected per user choice (workload
  honesty wins over visible-rows parity).
- **Preview cards on the Today tier too**: rejected — Today is a
  single-day surface; a "preview" for today is just "about to spawn,"
  and spawning should be user-triggered or via a future auto-spawn
  cron, not materialised as a preview.

## Verification

- **Unit**: 7 new `TestPreviewsEndpoint` tests in `tests/test_recurring.py`
  covering 400s, daily/weekly expansion, inactive exclusion, spawn
  collision suppression, range cap.
- **Phase 6**: manual regression with seeded data confirmed:
  - 11 previews + 4 real tasks in This Week, 14 previews in Next Week
  - Day-heading counts exclude previews (`Tuesday (0)` on a
    preview-only day)
  - Click on a preview with past spawn opens detail panel with
    matching title
  - Click on a brand-new template (no past spawn) fires the
    first-preview alert with the correct next fire_date
  - Mobile (375x812): preview cards fit at 341px, 2px dashed border
    renders correctly, 70px tap target meets the 44px floor
  - Zero console errors
- **Full suite**: 974 passed, 3 skipped.
