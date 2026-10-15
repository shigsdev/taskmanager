# #474 — Completing or cancelling a deleted task brings it back

Split from #447 (deep review §B10).

## What happens

A task in the Recycle Bin is `status = deleted`. Three paths set a task's status
to completed (`archived`) or `cancelled` without looking at where it is now:

| Path | Used by |
|---|---|
| `task_service.complete_parent_task` | `POST /api/tasks/<id>/complete` (board), `POST /api/voice-review/<id>/complete` (Shortcut) |
| `task_service.cancel_parent_task` | `POST /api/tasks/<id>/cancel`, `POST /api/voice-review/<id>/cancel` |
| `task_service.update_task` with `status` | `PATCH /api/tasks/<id>`, `PATCH /api/tasks/bulk`, reflection / plan applies |

So a stale tab (or the Shortcut's queue read a minute ago) that completes a task
you deleted elsewhere pulls it out of the bin as a completed task — and, for a
parent, the subtasks that went to the bin with it stay there, orphaned.

## Change

Refuse it: a task whose status is `deleted` can't go to `archived` or
`cancelled`. All three paths raise
`ValidationError("This task is in the Recycle Bin — restore it there first.", "status")`
→ 422, before anything changes. The board's #430 handling says
"… didn't save: This task is in the Recycle Bin — restore it there first. The
page now shows what's saved." and redraws without the card; the Shortcut gets
the 422 like any other refusal.

Unchanged: Restore (`deleted → active`), deleting, completing an already
completed task, cancelling a completed one (re-open flows), and every other
field edit.

## Not changed (noted)

- The Shortcut's **move** can change a deleted task's section; it stays
  deleted, so nothing comes back. Left alone.

## Tests

pytest: complete / cancel / PATCH archived / PATCH cancelled / bulk on a
deleted task → 422 (bulk: an error row) and it stays deleted, its
deleted-with-parent subtasks too; voice-review complete / cancel → 422;
Restore still works; completing an active and an already-completed task still
works (the quiet cases).
