# #494 — Undo and the Recycle Bin count the subtasks you added

Found 2026-10-16 in #465.

## What was wrong

Since #465 an import Undo takes the open subtasks you added to its tasks,
Restore brings them back and Purge removes them — but every word around it
counted only the batch's own rows: Settings → Import History's Undo
confirm, the Recycle Bin batch row ("1 task") and its Restore / Purge
dialogs. Cosmetic: the rows themselves were handled.

## This ship

- `recycle_service.undo_impact` → `subtasks`: how many open subtasks the
  Undo would take (#465's `_open_added_subtasks`, same rule).
- `recycle_service.list_bin` → `subtask_count`: the snapshot's subtasks
  still DELETED with `deleted_with_parent` — exactly the set Restore brings
  back and Purge deletes (one restored on its own no longer counts). One
  extra query for all batches.
- `recycleBinHelpers.addedSubtasksPhrase(n, when)` — "" for none;
  undo "2 subtasks you added go with it.", row "+2 subtasks you added",
  restore "… come back with it.", purge "… are deleted with it."
- Settings loads `recycle_bin_helpers.js` for the Undo confirm. Help →
  Recycle bin and undo. CACHE_VERSION v348.

Out of scope: the bin's summary line ("8 tasks across 7 batches") and the
Settings "Recycle Bin (N)" count stay counts of batch rows.

## Tests

`tests/test_bin_counts_added_subtasks.py` (red before),
`tests/js/unit/added_subtasks_phrase.test.js`,
`tests/e2e/bin_added_subtasks.spec.js` (Settings confirm, bin row,
Restore, Purge; the quiet case — red before on the first two).
