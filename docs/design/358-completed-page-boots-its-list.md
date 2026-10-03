# Spec #358 — `/completed` lists its tasks on load

**Filed:** 2026-10-01 (found during #355)
**Status:** approved 2026-10-03
**Regression from:** #270 (`96b0336`, 2026-05-31)
**Backend changes:** none.
**Frontend:** `static/app.js` `init()`, one condition.
**Severity:** Medium. No data at risk. A whole page looks empty for about
a minute, and its Work/Personal tabs do nothing.

---

## 1. Problem

`init()` (`static/app.js:228`) has three boot modes:

1. no `#detailOverlay` → return (goals, review, …);
2. panel but no task board → "panel-only" (#270, built for `/calendar`):
   preload `allTasks`, goals, projects, wire the panel, **return**;
3. the board → load everything, `setupNavTabs()`, `setupCollapse()`,
   `setupDetailPanel()`, `loadCompletedTasks()`, `loadCancelledTasks()`.

"Is this the board?" is `document.querySelector('.task-list[data-tier]')`
(`app.js:240`). `/completed`'s list is
`<div id="tierDetailList" class="tier-detail-list task-list" data-archived-list="true">`
(`templates/completed.html:51`). It has no `data-tier` (on purpose: the
template comment at `:40-44` says so, so `renderBoard()` never treats
"completed" as a tier). So `/completed` falls into mode 2, and two things
never run:

- **`loadCompletedTasks()`.** The list stays empty and the header count
  keeps the template's literal `0`. The empty-state message is hidden
  too, so the page shows neither tasks nor "No completed tasks yet".
  It fills in only when the ~60s freshness poll (`app.js:~3950`, first
  tick after 55s) or a tab switch (`visibilitychange`) calls
  `loadCompletedTasks()`.
- **`setupNavTabs()`.** The page's All / Work / Personal buttons
  (`completed.html:24-27`, `href="#"`) have no click handler, so they do
  nothing. `templates/docs.html:1939-1942` tells the user these filters
  work on `/completed`.

Before #270, `init()` had only modes 1 and 3, and `/completed` took
mode 3 (verified: `git show 96b0336^:static/app.js`, `init()` at
`:191`). #270 meant to carve out `/calendar` and caught `/completed`
by accident.

## 2. Goal

`/completed` boots the way it did before #270: the list and count
render on load, the empty state shows when there is nothing, and the
view tabs filter.

## 3. Affected surfaces (the complete list)

Pages that include `_task_detail_panel.html` (so reach past mode 1),
by grep 2026-10-03:

| Page | List marker | Mode today | Correct? |
|---|---|---|---|
| `/` (`index.html`) | `.task-list[data-tier]` × 7 | board | yes |
| `/tier/<name>` (`tier.html:47`) | `#tierDetailList[data-tier]` | board | yes, **no hole** |
| `/calendar` | none | panel-only | yes (#270's target) |
| `/completed` | `#tierDetailList[data-archived-list]` | panel-only | **no, this bug** |

So `/completed` is the only page affected; `/tier/<name>` is fine.

## 4. Design

Widen the board test to also recognise the archived list:

```js
const isBoard = !!document.querySelector(
    '.task-list[data-tier], .task-list[data-archived-list]'
);
```

…with the comment updated to name `/completed` and #358. That restores
mode 3 for `/completed`, the path the page was built against
(`renderCompletedPage` #29, the `data-archived-list` marker, bulk
toolbar, view tabs).

What mode 3 then does on `/completed`, checked against today's code:

- `loadTasks()` → `renderBoard()`: no `[data-tier]` lists, so the tier
  loop is a no-op. The tail helpers (`updateInboxBadge`,
  `updateTodayWarning`, `updateTodayHero`, `updateBulkTriageBtn`,
  `updateAutoCategorizeBtn`) are null-guarded per CLAUDE.md's init()
  cascade row. Phase 6 and `ui_audit.spec.js` console checks confirm it.
- `loadRecurringPreviews()`: one extra GET, unused here. Acceptable;
  it's what the page did for its first ~4 months.
- `?task=` / `?new_task_due=` handling: never set on `/completed` links.
- `loadCompletedTasks()` → `renderCompletedPage()`: the fix.
- `setupNavTabs()`: the tabs work.

**Rejected:** a fourth "completed" mode that calls only
`loadCompletedTasks()` + `setupNavTabs()`. Smaller fetch footprint, but
it creates a new boot path that nothing else exercises. Restoring
the pre-#270 path is the least-surprise fix.

**No Jest test for the condition.** It's a single selector, and its
only meaning is "which boot path runs". That can only be shown by
loading the real page, so the tests below do that (anti-pattern #3:
exercise the path, don't string-match it).

## 5. Testing plan (written RED first)

Local Playwright, `tests/e2e/pages.spec.js`, new describe
`"/completed lists completed tasks on load (#358)"`:

1. **Lists on load.** Create two tasks via API, one work and one
   personal, and complete both (`POST /api/tasks/<id>/complete`). Go
   to `/completed?nosw=1`. Both cards appear inside `#tierDetailList`
   within 5s. That is well under the 55s poll, so the poll can't make
   it pass. `#tierDetailCount` equals the rendered card count. RED on
   main.
2. **View tabs filter.** Same fixture. Click `Work`: the work card is
   visible and the personal card is gone. Click `All`: both are back.
   RED on main (no handler).
3. Clean up: `DELETE` both tasks in `finally`.

Prod smoke, `tests/e2e-prod/smoke.spec.js`, new behavioural test
`"/completed boots its list (#358)"`. This one must hold regardless of
prod data. Within 10s, EITHER at least one `.task-card` is in
`#tierDetailList` and `#tierDetailCount` equals the card count, OR
`#tierDetailEmpty` is visible. On main, neither is true (no cards,
empty state hidden), so it fails on main.

Existing: `ui_audit.spec.js` `/completed` row (console errors, overflow,
touch targets) still passes with the page now populated.

## 6. Cascade touch-points

- `static/sw.js` `CACHE_VERSION` v262 → v263 (app.js changed). The
  bump reloads any open tab.
- `tests/e2e/pages.spec.js:5363-5368`: #355's `openCompletedTask`
  comment says `/completed` "currently renders an empty list on main".
  Update it to past tense and cite #358. The test keeps going through the
  board's Completed section; it doesn't need to move.
- `templates/docs.html`: no change. `:1939-1942` already claims the
  filters work on `/completed`, and this makes it true.
- ARCHITECTURE.md: no topology change (no route, job, column, asset).
- CLAUDE.md: none.
- Phase 6 (UI): `/completed` at 1280×800 + 375×812, plus `/calendar`
  (must stay panel-only) and `/tier/today` (unchanged) as neighbours.

## 7. Out of scope (filed, not absorbed)

- The `#110` prod test that string-matches `app.js` for tier names
  (`smoke.spec.js:575`) is anti-pattern #3. It's already tracked by #347;
  not touched here.
- `/completed` does not mark the persisted view tab `active` on load (if
  the board was left on Work, `/completed` filters to Work while `All`
  looks selected). I'll check this during Phase 6 and file it as its
  own row if it reproduces.

## 8. Decisions

1. Restore the pre-#270 board path for `/completed` rather than add a
   fourth mode (§4).
2. Path-level tests (local Playwright + data-independent prod smoke),
   no Jest for a selector (§4).
