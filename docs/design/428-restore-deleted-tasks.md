# #428 — Deleted tasks can be restored from the Recycle Bin

Filed 2026-10-11 by the deep review (§A4) as "correct the copy, or give
deleted tasks a restore path". The user said "proceed" without picking;
this ship builds the restore path, because:

- Most delete paths ask nothing first — the task panel's Delete, swipe,
  Review mode, triage and planner suggestions — so one mis-tap loses a task
  with no way back in the app.
- Nothing ever purges a deleted task (`delete_task` only sets
  `status = DELETED`; `purge_batch` only touches import batches). Prod had
  105 deleted tasks on 2026-10-11, all still in the database.
- The server already revives one: `PATCH /api/tasks/<id> {"status":"active"}`,
  and `GET /api/tasks?status=deleted` already lists them. No new route.
- Three places already promise it (the bulk-delete confirm, the reflection
  prompt Claude proposes deletes under, Help's Reflection section); a restore
  makes them true instead of quietly weakening the reflection safety story.

## 1. Surface

| Piece | Code | Today |
|---|---|---|
| Delete paths | panel `app.js:2332`, bulk `app.js:3567`, swipe `swipe.js:129`, review `review.js:143`, triage `review.js:214/265`, planner `plan.js:329/342`, reflection apply `reflection_service.py:1846` | All set `status = DELETED` (`task_service.delete_task`, `review_service.py:72`) |
| Recycle Bin page | `templates/recycle_bin.html`, `static/recycle_bin.js`, `recycle_service.list_bin` | Undone import batches only |
| Settings badge | `settings.js:131-137` ← `recycle_service.bin_summary` | Counts import items only |
| Copy that says deletes are recoverable | `app.js:3570`, `reflection_service.py:240`, `docs.html:855` | False today |
| Copy that says regular deletes bypass the bin | `docs.html:1498, 1617, 2480-2484, 2542-2544`, `recycle_bin.html:12-16`, `recycle_service.py:21-27` | True today, false after this ship |

## 2. This ship

1. **Recycle Bin page, new "Deleted tasks" section** (under the import list):
   newest first by `updated_at` (nothing writes a deleted task, so that is
   when it was deleted); the newest 25, then "Show all N". Each row: title,
   "Deleted <date>", its section, and **Restore**, which PATCHes
   `status: "active"` and turns the row into "Restored to <section>." A
   deleted subtask whose parent is deleted too says so ("its parent task is
   deleted — restore that too to see it"). Empty Bin is unchanged (import
   batches only) and the section says so.
2. Pure helper `static/recycle_bin_helpers.js` (dual export, Jest):
   `binDeletedTasks(tasks, limit)` → sorted rows + hidden count + the
   parent-deleted flag; `binSectionLabel(tier)`.
3. `bin_summary` gains `deleted_task_count`; the Settings badge adds it.
   Undoing an import also marks its tasks DELETED (with `batch_id` kept),
   so the task serializer now exposes `batch_id` and the section leaves
   those to their batch's Restore (found in Phase 6: the list showed 69
   for 67 ordinary deletes).
4. Copy: the bulk-delete confirm names where to restore; Help's Statuses,
   Review, Recycle Bin and bulk sections; the page hint; the
   `recycle_service` docstring.
5. Cascade: new static asset → `sw.js` APP_SHELL + `health.py`
   EXPECTED_STATIC_FILES + CACHE_VERSION; CLAUDE.md Phase 6 step 12.
6. Tests (red on old code): Jest for the helper; pytest for
   `deleted_task_count`; Playwright: delete a task, open the Recycle Bin,
   Restore it, it's back on its tier page.

## 3. Out of scope

- Single delete leaves open subtasks active under a deleted parent (same
  class as #433, which covers the bulk paths) — noted on #433. Restoring the
  parent brings them back into view.
- Opening a deleted parent from a subtask's parent link offers ✓ Complete,
  which turns the deleted task into a completed one — filed #463.
- An undo toast right after a delete — no toast pattern exists yet; the bin
  is the recovery path. Not filed (a new feature, not a defect).
