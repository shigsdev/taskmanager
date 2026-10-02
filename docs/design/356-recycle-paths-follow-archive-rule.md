# Spec #356 — The recycle bin follows the archive rule

**Filed:** 2026-10-01 (found during #353's asymmetry sweep)
**Status:** specced, not yet built
**Builds on:** #353 / ADR-038 (shipped 2026-10-01, `40451d0`)
**Backend changes:** `recycle_service.py` only. No migration, no new
route, no schema change. Prod exposure today: **0 batches in the bin**,
so there's nothing to backfill.

---

## 1. Problem

#353 made one function, `project_service._set_project_active`, the place
a project's `is_active` changes. Archiving through it keeps task links,
pauses the project's running repeating templates and flags them, and
unarchiving resumes only the flagged ones.

The recycle bin's three paths still write `is_active` directly, each by
its own rule:

| Path | Projects in the batch | Task links | Templates |
|---|---|---|---|
| `undo_batch` (`recycle_service.py:245`) | `is_active = False`, direct write | **nulls `Task.project_id`** on every task pointing at them, including tasks the user linked by hand outside the batch | untouched: they **keep firing** into a project that's in the bin |
| `restore_batch` (`:293`) | `is_active = True`, direct write | doesn't re-link (the undo nulled them) | untouched: templates a `/projects` archive had flagged **stay paused and hidden** (#353's final review) |
| `purge_batch` (`:341`) | hard delete | nulls `Task.project_id` / `goal_id` (needed: `Task` FKs lack `ondelete`) | `project_id` is SET NULL by the DB, but `paused_by_project_archive` **stays True** on a template whose project no longer exists. It is paused forever, and nothing will ever resume it |

So an import's undo/restore round trip loses every task's project link,
and leaves templates firing (after undo) or stuck (after restore),
depending on which path touched them last.

**Goals are already consistent.** Undo/restore flip `Goal.is_active` and
leave every `goal_id` link alone, which is ADR-038's "archive keeps
links" rule. Goal archiving has no template cascade, by #349's decision
(links stay intact so unarchive works). Purge's `Task.goal_id` null-out
is required for the hard delete. No goal change is in scope.

## 2. Goal

Undo and restore treat an imported project exactly as the Archive and
Unarchive buttons do. Purge leaves no template carrying a flag for a
project that no longer exists.

## 3. Affected surfaces (the complete list)

| # | Surface | Change |
|---|---|---|
| R1 | `undo_batch` project block (`:262-283`) | call `_set_project_active(project, False)` per batch project; **remove** the `Task.project_id` null-out |
| R2 | `restore_batch` project block (`:316-324`) | call `_set_project_active(project, True)` per inactive batch project; the restored-count logic is unchanged |
| R3 | `purge_batch` (`:341`) | before deleting the batch's projects, clear `paused_by_project_archive` on templates pointing at them. They become ordinary paused templates; the DB then SET NULLs their `project_id`. Task null-outs unchanged |
| R4 | Comments and docstrings | module docstring, the stale #356 comment at `:262-271`, `restore_batch`'s "we do NOT re-link" note |

**Verified to need no change:**

- `empty_bin` (`:401`) loops `purge_batch`, so it inherits R3.
- `undo_batch` / `restore_batch` task and goal handling: see §1.
- Readers of an archived project's id, for tasks that now keep the link
  after an undo: the same set ADR-038 verified (active-only badge
  lookup, `_sweepStaleFilterIds`, #355 pickers, active-only server name
  lookups).

## 4. Design

### 4.1 Undo and restore go through the shared function

```python
from project_service import _set_project_active
...
for project in projects:           # undo
    _set_project_active(project, False)
...
for project in projects:           # restore
    if not project.is_active:
        _set_project_active(project, True)
        restored_projects += 1
```

`_set_project_active` is transition-guarded and doesn't commit; both
functions already commit once at the end, so the whole batch stays one
transaction.

**Importing a private name across modules** is deliberate. Renaming it
public would touch #353's ADR, spec and docstrings for no behavioral
gain. A one-line comment at the import names the reason.

### 4.2 Undo stops detaching tasks

That is ADR-038's rule applied to the last path that still broke it.
The original rationale (PR66 #131: phantom labels on still-active tasks)
is covered by the same read-side guards ADR-038 lists. The new behavior
is also strictly better for restore: an undo/restore round trip now
brings tasks back **with** their project link.

Batches undone **before** this ship already lost their links, and that
can't be reconstructed (nothing recorded which task pointed where).
Prod's bin is empty, so the gap is theoretical. The `restore_batch`
docstring will say so.

### 4.3 Purge clears the flag on templates of purged projects

```python
if project_ids:
    db.session.execute(
        update(RecurringTask)
        .where(RecurringTask.project_id.in_(project_ids))
        .values(paused_by_project_archive=False)
    )
```

Placed before the deletes. The template keeps whatever `is_active` it
has (paused templates stay paused), and loses only a promise that can
no longer be kept. **Not resumed**, because a template whose project the
user permanently deleted shouldn't suddenly start firing into no
project.

## 5. Testing plan (all written RED first)

**Flip the #353 pin.** `test_undo_batch_does_not_pause_templates_356`
in `tests/test_project_archive_templates.py` pins today's bypass, so it
becomes `test_undo_batch_pauses_templates`, asserting `(False, True)`.

**New, in `tests/test_project_archive_templates.py`:**

1. `test_undo_batch_pauses_templates`: as above.
2. `test_undo_batch_keeps_task_project_links`: a batch task AND a
   non-batch task linked to the imported project both keep
   `project_id`.
3. `test_restore_batch_resumes_templates_undo_paused`: undo then
   restore leaves the template `(True, False)` and the tasks still
   linked.
4. `test_restore_batch_resumes_templates_a_projects_archive_flagged`:
   the #353-review stuck state. Archive via `PATCH /api/projects/<id>`
   (template flagged), undo the batch, restore it, and the template is
   active again.
5. `test_restore_batch_leaves_user_paused_template_paused`: a template
   paused by hand before undo is not resumed by restore.
6. `test_purge_batch_clears_flag_on_templates_of_purged_projects`: undo
   (flags) then purge. With `PRAGMA foreign_keys=ON` (the pattern at
   `tests/test_recycle_bin.py:552`), the template survives with
   `project_id is None`, `paused_by_project_archive False`, and
   `is_active False`.
7. `test_undo_restore_leave_goal_links_alone`: pins §1's "goals are
   already consistent", so a future change has to be deliberate.

**Updated:** any `tests/test_recycle_bin.py` assertion that undo nulls
`Task.project_id` (the PR66 #131 `LinkedProj` case, around `:180`) is
rewritten to assert the link is kept.

**No UI tests.** The `/recycle-bin` page's markup and JS don't change.

## 6. Cascade touch-points

| CLAUDE.md row | Action |
|---|---|
| User-visible behavior | `templates/docs.html` Recycle bin section: one sentence saying undo pauses an imported project's repeating tasks and restore resumes them. Fact-check table at review; Phase 6 of `/docs` at both viewports (a template change) |
| Reversed / extended decision | ADR-038: the "#356 still owes the recycle paths" consequence becomes resolved; no new ADR (same decision, last path) |
| Architecture | ARCHITECTURE.md #353 bullet: drop "`recycle_service` still writes `is_active` directly (#356)" |
| Comments carrying the old claim | R4 |

## 7. Out of scope (filed, not absorbed)

- **#367 (new): restore doesn't remember what state a row was in before
  the undo.** `undo_batch` turns ACTIVE **and ARCHIVED** (completed)
  tasks into DELETED; `restore_batch` turns every DELETED task back into
  **ACTIVE**. So undo-then-restore resurrects completed imported tasks
  onto the board. Likewise, a project or goal the user had already
  archived before the undo comes back active on restore. Pre-existing
  since the bin shipped. It needs a pre-undo state record, which is
  bigger than this row.
- **#368 (new): templates on an archived GOAL keep firing.** That's
  consistent with #349's decision (goal archive keeps links and has no
  template cascade). The user decided on 2026-10-02 that goals should
  get #353's treatment. Filed as its own row because it needs its own
  decisions: a second flag versus a both-parents-active resume check,
  the `/goals` confirm, and a backfill. Not absorbed here.

## 8. Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Undo/restore call `_set_project_active` | one rule for every archive path (ADR-038) |
| 2 | Undo stops nulling `Task.project_id`, including on non-batch tasks | ADR-038; makes the round trip lossless |
| 3 | Purge clears the flag but doesn't resume | the promise ("resume on unarchive") can't be kept; resuming would fire into no project |
| 4 | Goals unchanged | already follow the keep-links rule; goal template cascade is #349's call |
| 5 | Import the private `_set_project_active` | avoids renaming #353's documented name; same behavior |
| 6 | No backfill | prod bin is empty |
