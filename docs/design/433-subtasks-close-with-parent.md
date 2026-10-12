# #433 — Closing or deleting a parent no longer strands its open subtasks

Filed 2026-10-11 by the deep review (§A10). Delete behaviour decided by the
user 2026-10-12: **the open subtasks go to the Recycle Bin with their parent
and come back with it** (over "refuse until closed" and "parent goes,
subtasks stay").

## 1. Surface

Only `POST /api/tasks/<id>/complete` and `/cancel`
(`complete_parent_task` / `cancel_parent_task`) handle open subtasks. Every
other path that closes or deletes a task leaves them ACTIVE under a closed
or deleted parent. They then show on the board as plain cards with no
parent badge (`app.js:1463` finds no parent).

| # | Path | Code | Today |
|---|---|---|---|
| 1 | Bulk toolbar → Mark complete | `app.js` status menu → `bulkPatch({status:"archived"})` → `bulk_update_tasks` → `update_task` | strands |
| 2 | Bulk toolbar → Mark cancelled | same, `status:"cancelled"` | strands |
| 3 | Multi-drag onto Completed (mouse) | `app.js` Completed drop → `/api/tasks/bulk` | strands, no confirm |
| 4 | Multi-drag onto Completed (touch) | `onTouchEnd` → `/api/tasks/bulk` | strands, no confirm |
| 5 | Goals → linked task tick box | `goals.js:420` PATCH `status:archived` | strands |
| 6 | Board complete when the cached counts are stale | `taskComplete` falls back to PATCH | strands |
| 7 | Reflection: an approved "update task status" proposal | `reflection_service` → `update_task` | strands |
| 8 | Panel Delete / swipe Delete | `taskDelete` → `DELETE /api/tasks/<id>` → `delete_task` | strands, no confirm |
| 9 | Bulk toolbar → Delete | `bulkDelete` → N × DELETE | strands |
| 10 | ✨ Plan "delete" row / review-triage "delete" | DELETE → `delete_task` | strands |
| 11 | Reflection: approved "delete task" proposal | `delete_task` | strands |
| 12 | /review Delete | `review_service.apply_review_action` sets DELETED itself | strands |

The single-task Complete and Cancel buttons (`taskComplete` / `taskCancel`)
already ask "Complete all subtasks too?" and close them together. A task
spawned by a repeating template keeps its subtasks open when it closes
(#230, `recurring_task_id` set). That rule stays.

## 2. This ship

### Server (`task_service.py`)
1. **Complete / cancel guard in `update_task`.** A status change to
   ARCHIVED or CANCELLED on a top-level, non-repeating task that has ACTIVE
   subtasks is refused (422, field `subtasks`, "N open subtask(s) —
   complete them too or close them individually first") unless the
   request carries `close_subtasks: true`. With it, those subtasks get the
   same status. `close_subtasks` is a request flag, not a column; it's taken
   out of the payload before the unknown-field check. This closes paths
   5–7 with a readable refusal and gives 1–4 an explicit opt-in.
2. **Delete takes the open subtasks along.** New `_soft_delete(task)` (no
   commit) is used by `delete_task` (paths 8–11), by `review_service`'s
   Delete (12), and by `update_task` when a PATCH sets `status:"deleted"`.
   It sets the task DELETED and clears `batch_id` (as before). Each ACTIVE
   subtask also becomes DELETED, gets its `batch_id` cleared, and gets
   `deleted_with_parent = True`. Done / cancelled subtasks are left alone.
   Repeating parents too: #230 is about weekly close-out, not delete.
3. **Restore brings them back.** When `update_task` moves a top-level task
   from DELETED to ACTIVE (the Recycle Bin's Restore), its subtasks that
   are DELETED with `deleted_with_parent` become ACTIVE again. A subtask
   deleted on its own before the parent stays deleted. Any task leaving
   DELETED gets `deleted_with_parent = False`.
4. **New column** `tasks.deleted_with_parent` (bool, NOT NULL, default
   false). Migration `w2e3f4a5b6c7`, no backfill (no existing row can be
   told apart; existing deleted subtasks stay individually restorable, as
   today).
5. Serializer (full view): `deleted_with_parent`, `recurring_task_id`. The
   page needs the second to tell which parents keep their subtasks open.
6. `recycle_service.bin_summary`'s `deleted_task_count` leaves out
   `deleted_with_parent` rows, so the Settings count matches the bin's rows.

### Page
7. New `static/subtask_helpers.js` (dual export, Jest):
   `openSubtaskSummary(tasks, {includeRepeating})` → `{parents, open}`;
   `subtaskCloseNote(action, summary)` → the sentence added to a confirm
   ("2 of them have 3 open subtasks, which will be completed too.") or "".
8. Bulk Mark complete / Mark cancelled (1, 2): the confirm / reason prompt
   adds the note. When `open > 0` the request sends `close_subtasks: true`.
   It never closes subtasks the confirm didn't mention: if the cached
   counts are stale, the server refuses that task and the alert says why.
9. Multi-drag onto Completed (3, 4): no subtasks means no confirm (the
   quiet case). Otherwise a confirm with the note. Cancel puts the cards
   back (reload).
10. `taskDelete` (8): a parent with open subtasks gets a confirm ("Delete
    this task? Its 3 open subtasks go to the Recycle Bin with it and come
    back when you restore it."). No subtasks, no confirm, as today.
    `bulkDelete` (9) adds the note to its existing confirm.
11. Goals tick box (5): a parent with open subtasks asks the board's
    question and uses `/complete` with `complete_subtasks`. No untick
    means nothing happens.
12. Recycle Bin: a subtask that went with its parent isn't listed on its
    own. The parent's row says "+3 subtasks come back with it", and Restore
    reads "Restored to Today with its 3 subtasks."
    (`recycle_bin_helpers.binDeletedTasks`).
12b. The panel's Complete / Cancel no longer ask "…all subtasks too?" for a
    repeating task, whose subtasks stay open anyway (#230). Found while
    writing the Help text: the question promised something the server
    doesn't do.
12c. A refused task in a bulk result now shows the server's reason, in
    `bulkPatch`'s alert and in `apiHelpers.actionFailureMessage`. Before,
    it only gave a count ("1 validation error(s)").
13. Help: the subtasks section, the bulk toolbar list (its "Complete"
    bullet named a button that is really Status ▾) and the Recycle Bin
    section. The old "There's no archive parent and leave orphans path" was
    false until now.
14. Playwright × 2 viewports (red on the old code): bulk Mark complete
    closes a parent's subtasks after naming them; panel Delete of a parent
    → subtasks leave the board → the bin shows one row "+2 subtasks" →
    Restore → both back; a parent-less delete asks nothing; the Goals tick
    on a parent asks, and declining leaves it open.
15. Cascade: new column → ARCHITECTURE.md PostgreSQL box,
    `_SCHEMA_DESCRIPTIONS`; new asset → `sw.js` APP_SHELL, `health.py`,
    CACHE_VERSION, `base.html`; CLAUDE.md Phase 6 line + rows.

## 3. Out of scope (filed)

- **Import Undo** (`recycle_service.undo_batch`) deletes an imported task
  without touching the subtasks the user added to it later; its restore
  doesn't know about them either. Different mechanism (batch snapshot):
  filed as #465.
- #463 (Complete on a deleted parent) stays separate. This ship restores
  subtasks only on DELETED → ACTIVE, so that path brings nothing back.
