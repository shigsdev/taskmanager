# ADR-017: Dedicated `/completed` page mirroring the tier-detail pattern

Date: 2026-04-20
Status: ACCEPTED

## Context

Backlog #29 — the Completed section on the board is a collapsed
inline list that grows unbounded over time. As completed-task volume
grows, the board view becomes uncomfortable to navigate (long scroll
on expand, no full-page bulk operations, no way to filter by
view/project at scale). #22 solved the same problem for tiers via
`/tier/<name>`; this ADR does the parallel for completed.

## Decisions

### 1. URL is `/completed`, not `/tier/completed`

Two options were considered:
- **(A)** Overload `/tier/<name>` with `name="completed"` as a special
  case that branches on status instead of tier.
- **(B)** Dedicated `/completed` route + dedicated template.

Picked **(B)**. "Completed" is not a `Tier` enum value — it's a
`TaskStatus`. Overloading a tier URL with a status would invite
future confusion ("`/tier/cancelled` next? `/tier/all`?"). Clean
URL semantics win over near-zero code dedup; the implementation
overlap is small.

### 2. Dedicated `templates/completed.html`, near-copy of `tier.html`

Mirrors `tier.html` for the chrome (back link, view filters, bulk
toolbar, detail panel include) but differs in three meaningful ways:

- **No `data-default-tier` on the capture bar.** Tasks typed here
  belong in Inbox (the server's default), not in archived state.
- **`data-archived-list="true"` on `#tierDetail` and
  `#tierDetailList`.** Marker that the JS init branch uses to
  detect "render archived tasks here" instead of "render tier=X
  tasks." Distinguishes from `tier.html`'s `data-tier="<value>"` so
  the existing `renderBoard()` loop (which iterates `TIER_ORDER`)
  doesn't try to filter `Task.tier == "completed"` (no such value).
- **Heading hint mentions the un-complete workflow** ("use Select to
  bulk-restore (Status → Mark active)") since drag-to-tier doesn't
  apply here as naturally.

### 3. Reuse the existing `taskCardEl` for full-featured cards

The board's inline Completed section uses the compact `completed-card`
treatment (`renderCompletedList`) — appropriate for a collapsed
section. The dedicated page renders full-featured cards via
`taskCardEl` so the user gets the same affordances as on any tier
page: tier buttons, bulk-select checkbox, click-to-open-detail. This
makes the un-complete flow trivial: bulk-select → Status → Mark
active.

### 4. Single `loadCompletedTasks` serves both surfaces

Rather than duplicate the load logic, `loadCompletedTasks()` now:

1. Looks for the board's `#completedList` AND the dedicated page's
   `#tierDetailList[data-archived-list="true"]`.
2. Renders into whichever one(s) exist via a sibling `renderCompletedPage()`
   helper that uses `taskCardEl`.
3. `renderCompletedList()` (the board's compact path) calls
   `renderCompletedPage()` first as a no-op-when-not-present, so
   every existing call site that refreshes the board's list also
   refreshes the dedicated page if both happen to be open.

### 5. Board's "Completed" heading becomes a clickable link

Same pattern as tier headings from #22: the text is a link to
`/completed`, the ▸ caret button still toggles the inline section.
Slight UX trade-off: the inline section becomes harder to discover
(the caret alone is the toggle handle), but the dedicated page IS
the better experience for any non-trivial volume. Acceptable.

### 6. Drive-by null-guard fix on `updateTodayWarning`

Phase 6 caught `TypeError: Cannot read properties of null (reading
'style')` from `updateTodayWarning()` — `#todayWarning` exists only
on the board, not on `/completed` or `/tier/<name>`. The function
ran on init via `renderBoard()` and crashed before
`loadCompletedTasks()` could be called. Fixed with a single
null-guard. Same kind of bug we hit during the `/tier/today`
client-error reports yesterday; this is the second occurrence —
worth keeping in mind for future "shared init function across
pages with different DOM" changes.

## Consequences

**Easy:**
- No schema change.
- No new endpoints — reuses `GET /api/tasks?status=archived`.
- Tier-detail's bulk toolbar carries over with no modification.

**Hard / accepted trade-offs:**
- The inline Completed section on the board still exists. Two
  surfaces showing the same data is mild redundancy, but the inline
  section serves a different use case ("at-a-glance count + quick
  peek") vs. the page ("browse, filter, bulk-restore"). Could be
  removed in a future cleanup if it bites.
- Capture bar on `/completed` defaults to Inbox. If a user types
  there they probably mean "I'm looking at completed and just
  remembered to add this new thing"; defaulting to Inbox is the
  right call but costs one mental context-switch (Inbox isn't
  visible from this page).

## Alternatives considered

- **Overload `/tier/completed`** — rejected (clean URL semantics,
  see decision 1).
- **Use the same compact `completed-card` treatment as the board** —
  rejected. Compact cards make sense in a collapsed section; on a
  full-page they'd be needlessly limited. Full `taskCardEl` makes
  the un-complete flow obvious.
- **Add a `Cancelled` dedicated page in the same commit** — deferred.
  Same overflow risk applies but #29 was scoped to Completed; if
  Cancelled grows enough to need it, it's a tiny mirror commit.

## Verification

- **Unit**: 7 new `TestCompletedPage` tests in `tests/test_views.py`
  (route 200/302/403, heading + label, bulk toolbar markup, no
  default-tier, scripts load, board heading links to `/completed`).
- **Phase 6**: full regression at desktop + mobile —
  - 5 archived tasks render via `taskCardEl`
  - Click opens detail panel with matching title
  - Bulk-select toggle works, toolbar appears, count updates
  - Status dropdown present (the bulk un-complete workflow)
  - Mobile (375x812): 351px card, no overflow, 0 console errors
  - Phase 6 caught + fixed `updateTodayWarning` null-guard
- **Full suite**: 992 passed, 3 skipped.
