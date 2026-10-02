# Spec #367 — Restore returns every row to its state before the undo

**Filed:** 2026-10-02 (found during #356's spec sweep, §7)
**Status:** specced, not yet built
**Approach:** A — a snapshot of what the undo changed, stored on the
batch's `ImportLog` row (user-approved 2026-10-02)
**Backend changes:** one new column on `import_log` + migration,
`recycle_service.py` (`undo_batch`, `restore_batch`, `purge_batch`).
**Frontend:** none. Help copy only (`templates/docs.html`).
**Prod exposure today (read-only check 2026-10-02):** recycle bin empty
(`/api/recycle-bin/summary` → 0 batches). Nothing to backfill.

---

## 1. Problem

`undo_batch` (`recycle_service.py:255`) soft-deletes a batch; `restore_batch`
(`:292`) brings it back. Restore has no record of each row's state before
the undo, so it guesses "make everything live":

| Row before undo | Undo does | Restore does today | Should |
|---|---|---|---|
| Task ACTIVE | → DELETED | → ACTIVE | ACTIVE ✓ |
| Task ARCHIVED (completed) | → DELETED | → **ACTIVE** | ARCHIVED |
| Task CANCELLED | nothing | nothing | nothing ✓ |
| Goal / project active | archive (`_set_*_active(False)`) | unarchive | unarchive ✓ |
| Goal / project **already archived** by the user | nothing (guard) | **unarchive**, and since #353/#368 its repeating tasks resume | stay archived |

`restore_batch`'s own docstring promises "we leave it alone to avoid
clobbering user intent"; the two bold rows break that.

Which archived rows are still in a batch: `delete_goal` clears
`batch_id` (`goal_service.py:159`), so a goal archived with the Archive
button is safe. A goal archived through `PATCH is_active:false` (the
reflection apply path) keeps `batch_id`, and so does every project
archive path (`project_service` never clears it). User-deleted tasks are
safe: `delete_task` (`task_service.py:881-882`) and Review's Delete
(`review_service.py:71-74`) clear `batch_id`.

## 2. Goal

Restore returns every row the undo changed to exactly the state it had
before the undo, and touches nothing the undo didn't change.

## 3. Design

### 3.1 The snapshot

New column `ImportLog.undo_snapshot` (`JSONType`, nullable). Shape:

```json
{"v": 1,
 "tasks": {"<task id>": "active" | "archived"},
 "goals": ["<goal id>", ...],
 "projects": ["<project id>", ...]}
```

- `tasks`: every batch task the undo turned DELETED, with its status
  before (`TaskStatus` value).
- `goals` / `projects`: the ones the undo actually archived, i.e. that
  were active when the undo ran. One the user had already archived is not
  listed.

### 3.2 `undo_batch`

Builds the snapshot while it changes rows (record before writing), stores
it on `log.undo_snapshot` in the same transaction as `undone_at`. Row
changes are unchanged from today (#356 / #368 paths kept).

### 3.3 `restore_batch`

With a snapshot:

- each task in `tasks` whose status is still DELETED → its recorded
  status; anything else is left alone (counts only what changed)
- each goal / project in its list that is still inactive →
  `_set_goal_active(goal, True)` / `_set_project_active(project, True)`
  (so #353 / #368 resume their templates exactly as Unarchive does)
- batch rows not in the snapshot are never touched
- `log.undo_snapshot = None`, `log.undone_at = None`

Without a snapshot (`NULL` — a batch undone before this ships): today's
behavior, unchanged, with a comment saying why. Prod has none; this is a
safety net, not a supported path.

Return shape unchanged: `{batch_id, tasks_restored, goals_restored,
projects_restored}`.

### 3.4 `purge_batch` / `empty_bin`

`purge_batch` sets `log.undo_snapshot = None` alongside `log.batch_id =
None` (`:416`), so the audit row doesn't keep ids of rows that no longer
exist. `empty_bin` goes through `purge_batch`, so it follows.

### 3.5 Robustness

- Ids in the snapshot whose row is gone or no longer in the batch are
  skipped silently (restore queries the batch's rows and looks them up
  in the snapshot, never the other way round).
- An unknown status string in the snapshot → that task is left DELETED
  and the rest of the restore proceeds (logged at WARNING, no task
  title in the log).

## 4. Testing plan (all written RED first)

`tests/test_recycle_restore_snapshot.py`:

- completed task: undo → DELETED; restore → ARCHIVED (not ACTIVE)
- active task round trip → ACTIVE; cancelled task untouched both ways
- project the user archived before the undo (via PATCH) stays archived
  after restore, and its paused templates stay paused
- goal archived via `PATCH is_active:false` before the undo stays
  archived after restore; its templates stay paused
- an active project / goal in the batch is unarchived by restore and its
  templates resume (the #356 / #368 behavior still holds)
- restore clears `undo_snapshot`; purge clears it; empty_bin clears it
- snapshot content after undo: exactly the changed rows, with prior
  statuses
- a NULL snapshot (legacy batch) restores with today's behavior
- a snapshot holding an unknown status leaves that task DELETED and
  restores the rest
- existing `tests/test_recycle_bin.py`, `tests/test_project_archive_templates.py`,
  `tests/test_goal_archive_templates.py` stay green

## 5. Cascade touch-points

- New column → `architecture_schemas.py` `_SCHEMA_DESCRIPTIONS["import_log"]`;
  `ARCHITECTURE.md` PostgreSQL box.
- Migration: add nullable column, no backfill (bin is empty; legacy NULL
  is handled).
- User-visible behavior → `templates/docs.html` `#recycle-bin` Restore
  bullet: "put every row back exactly as it was before the undo:
  completed tasks stay completed, and a project or goal you had already
  archived stays archived." Fact-checked against code.
- No static asset change → no `CACHE_VERSION` bump. Phase 6 on `/docs`
  and `/recycle-bin` (render only).

## 6. Out of scope

- **#369** (the undo confirm doesn't warn that repeating tasks pause):
  unchanged.
- Edits made while a batch is in the bin (e.g. unarchiving one of its
  goals by hand): restore already skips rows that are no longer
  inactive / DELETED, and keeps doing so.

## 7. Decisions

1. Snapshot on `ImportLog`, not per-row columns (approach A, user
   2026-10-02).
2. Restore is driven by the snapshot; batch rows outside it are never
   touched.
3. Legacy NULL snapshots keep today's behavior rather than refusing to
   restore.
4. Purge clears the snapshot.
