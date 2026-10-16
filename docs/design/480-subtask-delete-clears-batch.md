# #480 — A subtask deleted by status change lands in the Recycle Bin

Filed 2026-10-14 by the #448 Help check. Checked 2026-10-16 against
`task_service.update_task` / `_apply_status_to_subtasks` / `_soft_delete`,
`recycle_service` and `static/recycle_bin_helpers.js`.

## What was wrong

Every task delete is meant to go through `_soft_delete`, which sets
DELETED **and clears `batch_id`** (so a later Restore of the import batch
doesn't resurrect a task you binned yourself, and so the bin lists it under
Deleted tasks — the Deleted list hides rows that still carry a `batch_id`,
because those belong to an undone import shown above).

`update_task`'s status path calls `_apply_status_to_subtasks`, which
returns early for a subtask (`parent_id` set) before its DELETED branch.
So a PATCH `status: "deleted"` on a subtask — the bulk toolbar's Delete
(`bulk_update_tasks` → `update_task`), or a reflection / API update —
only set the status. An imported subtask deleted that way kept its
`batch_id` and was never listed in the bin; restoring its batch later
would also have brought it back.

The only other DELETED writes are `_soft_delete` itself and the import
Undo in `recycle_service` (which keeps `batch_id` on purpose).

Prod check 2026-10-16 (read-only): 105 deleted tasks, none carrying a
`batch_id` outside an undone batch — nothing to repair, forward fix only.

## This ship

- `_apply_status_to_subtasks`: the DELETED branch runs before the
  "a subtask has no subtasks" early return, so every status → deleted goes
  through `_soft_delete` (status, `batch_id` cleared,
  `deleted_with_parent` false; a parent still takes its open subtasks).
- pytest: a bulk delete and a single PATCH of an imported subtask clear
  its `batch_id` and list it in the bin's deleted tasks; a parent's bulk
  delete still takes its subtasks (`deleted_with_parent`).

No page change: the bin already lists any deleted task without a
`batch_id`.
