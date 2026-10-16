# #465 — Import Undo takes the subtasks you added

Filed 2026-10-12 while scoping #433. Checked 2026-10-16 against
`recycle_service.undo_batch` / `restore_batch` / `purge_batch` and
`task_service._soft_delete`.

## What was wrong

`undo_batch` set the batch's own tasks DELETED (by `batch_id`). A subtask
you added to an imported task after the import has no `batch_id`, so it
stayed ACTIVE under a deleted parent — on the board, with a parent link
that says "deleted" — and `restore_batch` knew nothing about it. Every
other delete takes open subtasks along since #433 (`_soft_delete`,
`deleted_with_parent`). Purge had a second hole: deleting the parent
nulls the child's `parent_id` (ORM / `ON DELETE SET NULL`).

## The rule (no new decision — #433's)

Open (ACTIVE) subtasks go to the bin with their parent, marked
`deleted_with_parent`; done / cancelled ones stay where they are. A
subtask imported in the same batch is a batch row already.

## This ship (`recycle_service.py`)

- `undo_batch`: `_open_added_subtasks` lists the ACTIVE subtasks of each
  top-level batch task the undo deletes (not in this batch); they go
  DELETED + `deleted_with_parent`, and the snapshot records them under
  `"subtasks"`. Result: `subtasks_removed`.
- `restore_batch` (snapshot path): `_restore_taken_subtasks` brings each
  back to ACTIVE if it is still DELETED + `deleted_with_parent` and its
  parent is out of the bin. One restored / changed meanwhile, or whose
  parent stays in the bin (a bad snapshot entry), is left. Result:
  `subtasks_restored`. A legacy (no snapshot) batch recorded nothing.
- `purge_batch`: hard-deletes the recorded subtasks still in the bin with
  their parent, before the parents. Result: `subtasks_purged`.
- `static/recycle_bin_helpers.js` `binDeletedTasks`: "is the parent in
  the bin?" now looks at every deleted task, the undone batch's included
  (it only looked at the listed rows, which leave batch rows out), so a
  subtask that went with an undone import's task isn't listed on its own —
  it comes back with the batch's Restore. Found by the Playwright test.
- The snapshot key is optional on read (`.get`), so older snapshots keep
  working; no version bump.
- Help → Recycle bin: undo / Restore / Purge lines.

## Tests

- pytest `tests/test_undo_takes_subtasks.py` (10): taken along + recorded;
  done / cancelled stay; one binned on its own left alone; restore back;
  restored-by-hand left; parent stuck in bin keeps it there; purge removes
  it and keeps a done one; the quiet case; a batch subtask not listed
  twice; not listed on its own in the bin.
- `test_recycle_restore_snapshot.py`: the exact-snapshot test gains
  `"subtasks": []`.
- Jest `recycle_bin_helpers.test.js`: such a subtask isn't listed; one
  deleted on its own still is, flagged parentDeleted.
- Playwright `tests/e2e/undo_takes_subtasks.spec.js`: import a task, add a
  subtask, Settings → Import History → Undo — the subtask is deleted and
  off the board; Recycle Bin → Restore — both back.

## Not in this ship

- **#494** (filed): the Undo confirm and the bin's batch row count only the
  batch's own tasks; they could say "+N subtasks you added go with it" like
  #433's Deleted-tasks row.
