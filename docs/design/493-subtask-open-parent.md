# #493 — A subtask goes only under an open task

Found 2026-10-15 in #463's Phase 6. **User decision 2026-10-16: active
parents only.**

## What was wrong

`task_service.create_task` and `update_task` checked that the parent
exists and isn't itself a subtask, not its status:
`POST /api/tasks {parent_id: <task in the Recycle Bin>}` made an ACTIVE
subtask (in the Inbox) whose parent was in the bin. Reachable from the
panel: a deleted / completed task opened from /completed or a parent link
still had the Subtasks "+ Add" box, and a /completed card's Move ▾ / quick
row still offered "+ Subtask".

## Why active only

The panel's Parent-task picker already lists only active tasks (it searches
`allTasks`); #433 closes a parent's open subtasks with it; and the board's
"↳ parent" badge only finds active parents. An open subtask under a closed
parent is a state the app otherwise avoids — except a repeating task's
subtasks, which stay open when it closes (Help → Subtasks).

## This ship

- `_refuse_closed_parent` (`task_service.py`): a completed, cancelled or
  deleted parent → 422 on `parent_id` — "That task is completed / cancelled
  — re-open it first.", "That task is in the Recycle Bin — restore it there
  first." (#474's wording). On create always; on update only when the
  parent CHANGES — the panel re-sends `parent_id` on every Save, and a
  repeating task's open subtasks under its closed parent must keep saving.
  Clearing a parent is always fine.
- Panel: on a task that isn't active the "+ Add" row hides and
  `#subtaskClosedNote` says "Re-open this task to add a subtask." ("Restore
  …" for a deleted one); the list still shows. Cards: "+ Subtask" only on
  an active task (a /completed card offered it).
- A stale panel (parent completed elsewhere) gets the server's reason in
  the existing alert and keeps the typed text.
- Help → Subtasks: a rule line. CACHE_VERSION v347.

## Tests

`tests/test_subtask_parent_active.py` (create / reparent under each closed
status refused with its reason — red before; active parent, unchanged
parent of a closed task, and clearing still work);
`tests/e2e/subtask_parent_active.spec.js` (completed task: no + Add, the
note, no + Subtask on its card; open task adds one; stale tab is told why).
