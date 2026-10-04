# Spec #383 (+ #348 part) — dragging into This Week / Next Week, and the two flaky tests

**Filed:** 2026-10-04 (user: "Fix the test after this ship", after two
unrelated gate failures in the #376–#380 run)
**Status:** approved 2026-10-04 ("Approved")
**Backend change:** yes, one route hardening (`/api/tasks/reorder`).

---

## 1. What the "flaky" board test was actually catching

`pages.spec.js:858` ("dragging a dated task to This Week LEAVES the date
alone") failed 2 of 4 full gate runs on 2026-10-03/04. The gate server's
log for a run where it **passed** shows that the test doesn't check the
reorder status, so it passed despite the bug:

```
PATCH /api/tasks/<id>          200
[logging_service] DBLogHandler insert failed (consecutive=1)
[logging_service] DBLogHandler insert failed (consecutive=2)
POST  /api/tasks/reorder       500   (11 s after the PATCH)
```

The dev DB's `app_logs` holds the two client errors behind it:

1. `app.js:891`: `NotFoundError: Failed to execute 'insertBefore' on
   'Node'`.
   - This Week and Next Week group their cards under weekday headings
     (#23, `day_group.js`), so a card is a **grandchild** of
     `.task-list`, not a child.
   - The `dragover` handler calls `list.insertBefore(card, afterEl)`,
     and `afterEl` comes from `getDragAfterElement` (`app.js:1180`),
     which returns a nested card. The call throws, and the dragged card
     never moves in the DOM.
2. `saveReorder → Server error: one of the hex, bytes, bytes_le, fields,
   or int arguments must be given`.
   - `finishDrop` (`app.js:1101`) builds `cardIds` from **every**
     `.task-card` in the list. That includes recurring **preview cards**
     (`_previewCardEl`, `app.js:477`: class `task-card preview-card`,
     with no `data-id`), so the payload carries `null`.
   - `/api/tasks/reorder` (`tasks_api.py:300`) calls `uuid.UUID(None)`,
     which raises `TypeError`. The route only catches `ValueError` and
     `AttributeError`, so it returns a 500.
   - The 500 is slow because the error log is written while the
     request's own write transaction still holds the SQLite lock. Each
     DBLogHandler insert waits out its 5 s timeout twice, which is the
     #225 cascade. That's how the test's 15 s window got blown.

**This is a real, user-facing bug.** Prod `app_logs` holds the same
`insertBefore` client error from the user's own browser twice, on
2026-09-24 (`app.js` line 859 at that version). Postgres returns the 500
quickly, so prod sees an error and an unsaved order rather than a
timeout.

What the user sees today when dragging a card into This Week or Next
Week:
- The tier change saves, through the PATCH.
- The card doesn't follow the pointer while dragging.
- The within-week order isn't saved. A null id turns the whole reorder
  call into a 500, so none of the order is written.
- A client error is logged every time.

## 2. The second flake: service-worker test navigation race

`tests/e2e-sw/service_worker.spec.js:143` failed once with `page.goto:
Navigation to "/" is interrupted by another navigation to "/"`.

`primeSw` waits for `navigator.serviceWorker.controller !== null`, then
calls `page.goto("/")`. But base.html's `controllerchange` listener
(`base.html:216-219`) calls `location.reload()` right as the controller
appears. If that reload is still in flight, the test's own `goto`
collides with it. This is test-side only; the app's reload is correct.

## 3. This ship

**Client (`static/app.js`):** both insert sites and both id collectors
share the bug, so all four change:
- Mouse `dragover` (`:891`) and touch move (`:1010`): insert relative
  to the anchor's actual parent, `afterEl.parentNode.insertBefore(c,
  afterEl)`. With no anchor, keep `list.appendChild(c)`. In a
  day-grouped tier, the card then drops into the group under the
  pointer.
- `finishDrop` (`:1107`) and bulk move up/down (`:3430`): collect ids
  from `.task-card[data-id]` only, so preview cards never reach the
  payload.

**Server (`tasks_api.py` `reorder`):**
- Catch `TypeError` alongside `ValueError` and `AttributeError`, so a
  non-string id is skipped like a malformed one instead of crashing the
  request. That matches the route's existing skip-bad-ids behaviour.
- pytest: `task_ids` containing `null` (and an int) → 200, with the
  valid ids still reordered.

**Tests:**
- The two tier-drag tests (Tomorrow and This Week) assert
  `reorderResp.ok()`. Today they await the response and never check it,
  which is #347's exact anti-pattern.
- New Playwright test: dragging a card into This Week, where weekday
  groups and a recurring preview are present, leaves no page error, the
  reorder returns 200, and the card sits inside a day group of This
  Week's list.
- `primeSw` (SW spec): after the controller appears, retry `page.goto`
  once if it fails with "interrupted by another navigation". Then wait
  for `load`.

**Cache / docs:**
- `CACHE_VERSION` +1.
- No user-facing copy changes, because the documented drag behaviour
  is unchanged.
- Phase 6 on the board at both viewports: drag into This Week and Next
  Week, the card moves and the order persists on reload, 0 console
  errors.

## 4. Out of scope (filed)

- **#384:** dev-bypass writes one `LOCAL_DEV_BYPASS_AUTH served …`
  WARNING row to SQLite per request: 9,899 of the dev DB's 10,017
  `app_logs` rows. That write load is what makes lock waits likely
  under the gate's request bursts. Fix: log once per process, or at
  DEBUG level and not to the DB handler. Dev-only; no prod impact.
- **#348 stays open** for its other recorded flakes: the reflection
  `ERR_NETWORK_CHANGED` and autosave waits, and the 0xC0000409 worker
  crash. Today's two failures are resolved by this ship and get noted
  on the row.
