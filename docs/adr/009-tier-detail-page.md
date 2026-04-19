# ADR-009: Tier detail page — `/tier/<name>` with shared render path

Date: 2026-04-19
Status: ACCEPTED

## Context

Backlog #22 asked for a dedicated full-page view of a single tier,
for when Today / This Week / Backlog grow too long to read in the
constrained board panels. Three design questions:

1. **One handler or five?** `/tier/<name>` with enum validation, or
   `/tier/today`, `/tier/this_week`, etc. as separate routes.
2. **New render path or shared?** Build `renderTierDetail()` as a
   parallel function to `renderBoard()`, or teach the existing
   `renderBoard()` to handle both layouts.
3. **Entry point?** Add a dedicated "↗ full view" icon per tier, or
   make the tier heading itself clickable.

## Decision

1. **One handler**, parameterized: `@app.route("/tier/<name>")`. The
   handler validates `name` against the `Tier` enum and 404s on
   unknown slugs. Single place to maintain if a new tier is added.
2. **Shared render path.** `renderBoard()` already queries
   `.task-list[data-tier="<tier>"]` and skips missing ones — on the
   tier-detail page there's only ONE matching list, so the same
   function populates it correctly. Added an else-branch to update
   `#tierDetailCount` when the list isn't inside a `.tier` section.
   This means the entire feature set (bulk select, filter, detail
   panel, project grouping via Work view, drag-to-reorder) works on
   both pages without any new code.
3. **Click the tier heading text.** The 5 tier headings on the board
   (Inbox / Today / This Week / Backlog / Freezer) are now anchor
   tags linking to `/tier/<slug>`. Chosen over a separate icon
   because it's a larger tap target and the affordance is obvious
   once you discover it. `title` attribute provides the explicit
   "Open X as full page" hint.

Also: the capture bar on `/tier/<name>` carries
`data-default-tier="<name>"`. `capture.js` checks for that attribute
and defaults new tasks to that tier (unless the user wrote an
explicit `#tier` tag). So typing "Buy milk" on `/tier/today` creates
a task in Today.

## Consequences

**Easy:**
- All 5 tiers get a dedicated page from one route
- Zero duplication of rendering logic — `taskCardEl`, `renderBoard`,
  bulk select, detail panel, filters, drag-reorder all work as-is
- Extracted `_task_detail_panel.html` Jinja partial so the 153-line
  modal is defined once and included on both `index.html` and
  `tier.html`
- Adding pagination later (deferred; see backlog #22 discussion)
  only needs changes in `renderBoard` and the template

**Hard / accepted trade-offs:**
- The tier page loads ALL tasks via `loadTasks()` and renders just
  the matching one, instead of making a more efficient
  `?tier=today` request. Fine at current scale; revisit if the
  single-request payload grows large enough to slow perceived
  render time.
- The tier page shows nav tabs at the top (back link, All/Work/
  Personal, Select) which on mobile is a bit crowded. Works today;
  if it becomes a problem, the mobile layout can be adjusted in CSS
  without changing the route structure.

## Alternatives considered

- **Five separate routes** (`/today`, `/inbox`, etc.): more
  conventional REST, but needlessly multiplies code for no benefit.
- **`renderTierDetail()` as a parallel function**: would have
  duplicated all the per-card rendering and mutation wiring. Shared
  function is strictly better.
- **Dedicated "↗" icon in each tier header**: smaller tap target,
  less obvious to discover. Whole-heading link is the stronger
  affordance.
- **Sub-route like `/` with `?tier=today`**: URL-bookmarkable but
  makes the page structure dependent on a query string — worse DX
  for the "jump to this tier" mental model.
