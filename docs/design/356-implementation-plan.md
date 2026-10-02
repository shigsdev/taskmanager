# #356 Recycle Paths Follow the Archive Rule — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The recycle bin's undo and restore archive and unarchive an imported project exactly as the Archive and Unarchive buttons do. Purge leaves no template flagged for a project that no longer exists.

**Architecture:** `recycle_service.undo_batch` / `restore_batch` call #353's `project_service._set_project_active` instead of writing `is_active`, and undo stops nulling `Task.project_id`. `purge_batch` clears `paused_by_project_archive` on templates of the projects it hard-deletes. Goals are untouched.

**Tech Stack:** Flask + SQLAlchemy 2.0, pytest.

**Spec:** `docs/design/356-recycle-paths-follow-archive-rule.md` (approved 2026-10-02).

## Global Constraints

- Branch `fix/recycle-paths-follow-archive-rule`. One gated commit at the end; no per-task commits (CLAUDE.md gates every commit, ~35 min).
- Stage files explicitly; `SESSION_HANDOFF.md` stays out.
- Import as `from project_service import _set_project_active` with a one-line comment giving the reason (spec decision 5). Don't rename it.
- Purge clears the flag but **never** changes `is_active` (spec decision 3).
- No goal behavior changes (spec decision 4).
- Windows: `PYTEST_ADDOPTS='--basetemp=<scratchpad>/pytest-basetemp'` (forward slashes); `python -m ruff`.

## Review Focus

1. **Undo of a batch whose project the user already archived on `/projects`** (templates already flagged). Undo is then a no-op transition, and restore must still resume those templates. This is spec test 4, in Task 1.
2. **A template the user resumed by hand while its project sat in the bin.** Its flag was cleared, so purge leaves it active and the DB nulls its project link. Pin it in Task 2 as `test_purge_leaves_a_user_resumed_template_running`.
3. **`empty_bin` with two batches in the bin.** Both batches' flagged templates get the flag cleared. Pin in Task 2 as `test_empty_bin_clears_flags_across_batches`.
4. **A template whose project is in the batch but whose goal is outside it.** Undo, restore and purge must never touch `goal_id`, which spec test 7 covers in Task 1. On purge, only `project_id` is DB-nulled.
5. **Restore's returned count.** `projects_restored` still counts only the projects restore actually reactivated. Assert it in spec test 3, in Task 1.

---

### Task 1: Undo and restore through `_set_project_active`

**Files:**
- Modify: `recycle_service.py:1-36` (module docstring + import), `:245-290` (`undo_batch`), `:293-338` (`restore_batch`)
- Modify: `tests/test_project_archive_templates.py` (flip the #356 pin, add tests)
- Modify: `tests/test_recycle_bin.py:~172-196` (the PR66 `LinkedProj` test)

**Interfaces:**
- Consumes: `project_service._set_project_active(project: Project, active: bool) -> None` (doesn't commit; transition-guarded).

- [ ] **Step 1: Write the failing tests** in `tests/test_project_archive_templates.py`. Build batches with a local helper `_batch_with_project(name) -> (batch_id, project)`: a `Project(batch_id=...)` plus an `ImportLog(source="t", task_count=1, batch_id=...)`, which is the shape of the existing #356 pin.
  - Rename `test_undo_batch_does_not_pause_templates_356` to `test_undo_batch_pauses_templates`, asserting the project is inactive and `_state(rt) == (False, True)`.
  - `test_undo_batch_keeps_task_project_links`: a batch task (`batch_id` set) and a non-batch task, both with `project_id` = the imported project. After `undo_batch`, both keep `project_id`; the non-batch one is still `TaskStatus.ACTIVE`.
  - `test_restore_batch_resumes_templates_undo_paused`: undo, then restore. Assert `_state == (True, False)`, the task is still linked, and the result has `projects_restored == 1`.
  - `test_restore_batch_resumes_templates_a_projects_archive_flagged`: `PATCH /api/projects/<id> {"is_active": false}` first, then undo, then restore. Assert `_state == (True, False)` and the project is active.
  - `test_restore_batch_leaves_user_paused_template_paused`: a template created with `is_active=False` before undo. After undo+restore it is `(False, False)`.
  - `test_undo_restore_leave_goal_links_alone`: a batch `Goal` plus a non-batch `Goal` G2. A task and a template on the imported project carry `goal_id=G2.id`, and a second task carries the batch goal's id. After undo and again after restore, every `goal_id` is unchanged.
- [ ] **Step 2: Update `tests/test_recycle_bin.py`'s `LinkedProj` test.** Rename it to say "keeps", rewrite its docstring to cite #356 / ADR-038, and assert `refreshed.project_id == proj.id` (the status assertion is unchanged).
- [ ] **Step 3: Run** `python -m pytest tests/test_project_archive_templates.py tests/test_recycle_bin.py --no-cov -q`. Expected: the new/renamed tests FAIL. `test_undo_restore_leave_goal_links_alone` and `..._user_paused_template_paused` may already pass (they pin unchanged behavior).
- [ ] **Step 4: Implement.** In `undo_batch`, replace the project loop plus the `update(Task)...project_id=None` block with `_set_project_active(project, False)` per project. In `restore_batch`, replace the direct `project.is_active = True` with `_set_project_active(project, True)` inside the existing `if not project.is_active` (count unchanged). Rewrite the R4 comments:
  - the module docstring gets one sentence saying projects follow ADR-038's rule;
  - the stale comment at the old `:262-271` is replaced;
  - `restore_batch`'s "we do NOT re-link" note is rewritten: links are kept now, and batches undone before #356 lost theirs, which can't be reconstructed.
- [ ] **Step 5: Run** the same command, plus `tests/test_projects_api.py tests/test_project_goal_cascade.py`. Expected: all PASS. `python -m ruff check recycle_service.py tests/` is clean.

---

### Task 2: Purge clears the flag on templates of purged projects

**Files:**
- Modify: `recycle_service.py` (`purge_batch`, before the deletes; add `RecurringTask` to the models import)
- Test: `tests/test_project_archive_templates.py`

**Interfaces:**
- Consumes: Task 1's undo behavior (it produces the flagged state).

- [ ] **Step 1: Write the failing tests.** Each runs `db.session.execute(sa.text("PRAGMA foreign_keys=ON"))` first (the `tests/test_recycle_bin.py:552` pattern), so the DB-level SET NULL fires as it does on Postgres.
  - `test_purge_batch_clears_flag_on_templates_of_purged_projects`: undo (the template becomes `(False, True)`), then `purge_batch(bid, "DELETE")`. The template still exists with `project_id is None`, `is_active False` and `paused_by_project_archive False`.
  - `test_purge_leaves_a_user_resumed_template_running` (Review Focus 2): undo, then `PATCH /api/recurring/<id> {"is_active": true}`, then purge. The template is `is_active True`, flag False, `project_id is None`.
  - `test_empty_bin_clears_flags_across_batches` (Review Focus 3): two batches, each with a project + template, both undone. `empty_bin("DELETE")` leaves both templates with flag False and `is_active` False.
- [ ] **Step 2: Run** `python -m pytest tests/test_project_archive_templates.py -k "purge or empty_bin" --no-cov -q`. Expected: the first and third FAIL on the flag; the second may already pass.
- [ ] **Step 3: Implement** the spec §4.3 `update(RecurringTask)...values(paused_by_project_archive=False)` for the batch's `project_ids`. Place it before the deletes, and leave `is_active` alone.
- [ ] **Step 4: Run** `python -m pytest tests/test_project_archive_templates.py tests/test_recycle_bin.py --no-cov -q`. Expected: all PASS.

---

### Task 3: Docs, ADR, ARCHITECTURE, Phase 6 of `/docs`

**Files:**
- Modify: `templates/docs.html` (`#recycle-bin` section, "Actions on a batch in the bin")
- Modify: `docs/adr/038-project-archive-preserves-task-links.md` (Consequences: the `recycle_service` bullet; Regression tests: the pin's new name)
- Modify: `ARCHITECTURE.md` (the #353 bullet: drop "`recycle_service` still writes `is_active` directly (#356)"; add one clause saying undo/restore use it too)

- [ ] **Step 1: Help copy.** After the Restore / Purge list, add one paragraph: undoing an import that created projects archives them the same way the Archive button does, so their tasks keep their project, their running repeating tasks pause, and Restore resumes them. Purge permanently deletes the projects; any repeating task still pointing at one stays paused and is no longer tied to a project.
- [ ] **Step 2: Fact-check table**, one row per claim, cited `file:line` against Tasks 1–2. It goes in the ship report.
- [ ] **Step 3: ADR-038 + ARCHITECTURE edits** as listed under Files. Then `python scripts/arch_sync_check.py` → OK.
- [ ] **Step 4: Phase 6, `/docs` only**, at 1280×800 and 375×812 via the dev bypass (`?nosw=1`). The new paragraph renders, parity holds (`scrollWidth <= innerWidth`), and the console has 0 errors. The recycle-bin page markup is unchanged, so skip it. Teardown: `python scripts/stop_dev_bypass.py`, and the `.env.dev-bypass` marker is absent.

---

### Task 4: Gate, ship, validate

- [ ] **Step 1:** Run `bash scripts/run_all_gates.sh > <scratchpad>/gates_356.log 2>&1` with the basetemp. Expected: `ALL GATES GREEN`. Drop any #362 noise hunk from BACKLOG.md.
- [ ] **Step 2: Commit**, staging explicitly: `fix(#356): the recycle bin follows the archive rule`. Include the spec link, the Gates trailer and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- [ ] **Step 3: Fresh prod backup before the push** (the standing user request since #353). `gh workflow run daily-backup.yml --ref main`, then `gh run watch <id> --exit-status`. Expected: success, plus a `pushed` line in the log. No backup, no push.
- [ ] **Step 4: Fast-forward `main`, then push.** No `CACHE_VERSION` bump (no static change), so open tabs don't reload. Say so.
- [ ] **Step 5:** `python scripts/validate_deploy.py --monitor-minutes 5` (full log, no `tail`), then `npm run test:e2e:prod` with the cookie env.
- [ ] **Step 6:** Flip BACKLOG #356 to ✅ with the deploy SHA, then gates, commit, push. Print the SOP report and delete the branch.
