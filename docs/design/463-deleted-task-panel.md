# #463 — A deleted task opened in the task panel

Filed 2026-10-11 while scoping #428. Checked 2026-10-15 against
`static/app.js` (`taskDetailPopulateParentLink`, `taskDetailOpen`,
`setupDetailPanel`) and `task_service.py`.

## What was wrong

A subtask's panel links to its parent, also when the parent is in the
Recycle Bin (the link carries a "deleted" badge). That's reachable: deleting
a parent takes its OPEN subtasks to the bin (#433) but leaves completed /
cancelled ones where they are, so a completed subtask on /completed links to
a deleted parent.

Clicking the link opened the parent with the panel's normal buttons — the
panel never varied them by status. The row's worst case (✓ Complete turning
the deleted task into a completed one) was closed on the server by #474:
complete / cancel of a deleted task is refused with "This task is in the
Recycle Bin — restore it there first." What's left is the panel itself:

- ✓ Complete and ✕ Cancel task can only fail, with that message.
- ⧉ Copy to tomorrow makes an active copy of a binned task.
- Delete on an already-deleted task.
- No way to restore it from here — the message sends you to the bin.

## This ship

For a task whose status is `deleted` the panel:

- hides ✓ Complete, ⧉ Copy to tomorrow, ✕ Cancel task and Delete;
- shows a note "This task is in the Recycle Bin." and a **Restore** button
  — the same `PATCH {status: "active"}` the bin's Restore sends, so a
  parent's subtasks that went to the bin with it come back too (#433);
- on success closes the panel and reloads (as ✓ Complete / Delete do); on
  failure says "Restoring the task didn't save: <reason>. …" (#430's
  message) and stays open.

Save stays: #474 kept edits to a deleted task allowed, and they don't
revive it. Every other status shows the panel exactly as before.

Help → Recycle bin gets one line.

## Tests

Playwright `tests/e2e/deleted_task_panel.spec.js` (both projects):

- a completed subtask on /completed → parent link ("deleted") → the panel
  shows Restore + the note and none of the four buttons; Restore brings the
  parent back active (API) and the panel closes;
- Restore refused (PATCH stubbed 500) → the message, the panel stays open,
  the task stays deleted;
- the quiet case: opening an active task shows the four buttons and no
  Restore / note.

## Not in this ship

- **#493** (filed): the server accepts a new subtask under a deleted parent
  (`create_task` / `update_task` don't check the parent's status), and the
  panel's Subtasks "+ Add" is still there for a deleted task. Server-side
  rule + its panel side go together in that row.
