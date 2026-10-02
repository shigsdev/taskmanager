# #367 Restore Returns Rows to Their Pre-Undo State — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recycle-bin Restore puts every row the undo changed back exactly as it was before the undo, and touches nothing else.

**Architecture:** `undo_batch` records what it changes in a JSON snapshot on the batch's `ImportLog` row (`undo_snapshot`); `restore_batch` reverses only the rows in that snapshot; `purge_batch` clears it. A NULL snapshot (a batch undone before this ships) keeps today's behavior.

**Tech Stack:** Flask, SQLAlchemy 2.0 (`JSONType` = JSON / JSONB on Postgres), Alembic, pytest.

**Spec:** `docs/design/367-restore-returns-rows-to-pre-undo-state.md`

## Global Constraints

- Branch `fix/restore-pre-undo-state` from `main`. Never commit to `main` directly.
- Windows: `source .superpowers/env.sh` before pytest; `python -m ruff`. Single runs: `python -m pytest <file>::<test> --no-cov -q -p no:cacheprovider`.
- Snapshot shape, exact: `{"v": 1, "tasks": {"<task id str>": "active"|"archived"}, "goals": ["<goal id str>"], "projects": ["<project id str>"]}`.
- Goals/projects go through `_set_goal_active` / `_set_project_active` on both undo and restore (#356 / #368); never write `is_active` directly.
- Restore never touches a batch row that isn't in the snapshot.
- Log lines never include task titles (single-user app, but titles are user content).
- No static asset change → no `CACHE_VERSION` bump.
- Before the push: `gh workflow run daily-backup.yml --ref main`, wait for success + `[backup] pushed`. No green backup, no push.
- Stage files explicitly; never `SESSION_HANDOFF.md`; revert #362 audit-row noise in `BACKLOG.md` before staging.

## Review Focus

1. **Two round trips:** undo → restore → complete a task → undo → restore must end ARCHIVED; the second undo builds a fresh snapshot, never reuses the first. → Task 2 `test_second_round_trip_uses_a_fresh_snapshot`.
2. **A goal unarchived by hand while its batch is in the bin:** restore leaves it alone and does not re-run the unarchive cascade (its templates were already resumed by the manual unarchive). → Task 2 `test_restore_skips_goal_unarchived_by_hand_in_the_bin`.
3. **Id types:** snapshot keys are strings; batch rows' ids are UUIDs. Comparison must use `str(row.id)`, or nothing restores. Pinned by every round-trip test running against the real model.
4. **Legacy NULL snapshot** restores with today's behavior instead of crashing. → Task 2 `test_null_snapshot_restores_like_before`.
5. **Corrupt snapshot entry** (unknown status) leaves that task DELETED, restores the rest, and logs a WARNING without the title. → Task 2 `test_unknown_status_in_snapshot_is_skipped`.

---

### Task 1: `ImportLog.undo_snapshot` column + migration

**Files:**
- Modify: `models.py:433-449` (`ImportLog`, after `undone_at`)
- Create: `migrations/versions/t9b0c1d2e3f4_import_log_undo_snapshot.py` (`down_revision = "s8a9b0c1d2e3"`)
- Modify: `architecture_schemas.py` `_SCHEMA_DESCRIPTIONS["import_log"]["columns"]`
- Modify: `ARCHITECTURE.md` (PostgreSQL box: import log gains `undo_snapshot`)
- Test: `tests/test_recycle_restore_snapshot.py` (new)

**Interfaces:**
- Produces: `ImportLog.undo_snapshot: Mapped[dict | None]` (`JSONType`, nullable, no default).

- [ ] **Step 1: Write the failing test** — file docstring cites #367 + spec; helpers used by Task 2 go here too: `_batch() -> (batch_id, ImportLog)`, `_task(batch_id, status=TaskStatus.ACTIVE) -> Task` (type WORK, tier INBOX), `_goal(batch_id, *, active=True)`, `_project(batch_id, *, active=True)`, `_log(batch_id) -> ImportLog` (refreshed).

```python
def test_import_log_has_nullable_undo_snapshot(app):
    with app.app_context():
        bid, log = _batch()
        assert _log(bid).undo_snapshot is None
        log.undo_snapshot = {"v": 1, "tasks": {}, "goals": [], "projects": []}
        db.session.commit()
        assert _log(bid).undo_snapshot["v"] == 1
```

- [ ] **Step 2: Run it** — Expected: FAIL (`undo_snapshot` unknown attribute).
- [ ] **Step 3: Implement** the column (comment: #367, what it holds, cleared on restore/purge, NULL = live batch or legacy undo), the migration (`batch_alter_table("import_log")` add nullable `JSON()` column — use `sa.JSON().with_variant(postgresql.JSONB(), "postgresql")`; downgrade drops it; docstring: no backfill, bin empty on prod 2026-10-02), the schema description `{"desc": "What the last undo changed, so Restore can put it back", "notes": "JSON: each task's prior status plus the goals/projects the undo archived; cleared on restore and purge (#367)"}`, and the ARCHITECTURE box entry.
- [ ] **Step 4: Run it** + `tests/test_architecture.py` — Expected: PASS. Then `FLASK_ENV=development python -m flask db upgrade` → upgrades to `t9b0c1d2e3f4`.
- [ ] **Step 5: Commit** — `feat(#367): ImportLog.undo_snapshot column`

### Task 2: Undo records, restore reverses, purge clears

**Files:**
- Modify: `recycle_service.py:255-340` (`undo_batch`, `restore_batch`), `:416` (`purge_batch`), module docstring
- Test: `tests/test_recycle_restore_snapshot.py`

**Interfaces:**
- Consumes: Task 1's column; `_set_goal_active(goal, active)`, `_set_project_active(project, active)`.
- Produces: no new public names. Private helper `_restore_from_snapshot(snapshot: dict, tasks, goals, projects) -> tuple[int, int, int]` and `_restore_legacy(tasks, goals, projects) -> tuple[int, int, int]` (today's loop bodies, moved verbatim).

- [ ] **Step 1: Write the failing tests:**
  - `test_completed_task_comes_back_completed` — ARCHIVED task; undo → DELETED; restore → ARCHIVED; `tasks_restored == 1`.
  - `test_active_task_round_trip_and_cancelled_untouched` — ACTIVE → ACTIVE; CANCELLED stays CANCELLED through both, not counted.
  - `test_snapshot_records_exactly_what_undo_changed` — batch with ACTIVE, ARCHIVED, CANCELLED tasks, one active + one archived goal, one active + one archived project; after undo `undo_snapshot == {"v": 1, "tasks": {str(a): "active", str(b): "archived"}, "goals": [str(active_goal)], "projects": [str(active_project)]}`.
  - `test_project_archived_before_undo_stays_archived` — project archived via `update_project(id, {"is_active": False})` with an active template (paused by that archive); undo; restore → project still inactive, template still `(False, True)` on `(is_active, paused_by_project_archive)`; `projects_restored == 0`.
  - `test_goal_archived_by_patch_before_undo_stays_archived` — same with `update_goal(id, {"is_active": False})` and `paused_by_goal_archive`.
  - `test_active_project_and_goal_restore_and_resume_templates` — both active with a template each; undo pauses; restore → both active, templates active, markers cleared.
  - `test_restore_and_purge_clear_the_snapshot` — after restore `undo_snapshot is None`; undo again, purge → `undo_snapshot is None` (and `empty_bin("DELETE")` on a third batch → None).
  - `test_second_round_trip_uses_a_fresh_snapshot` (Review Focus 1).
  - `test_restore_skips_goal_unarchived_by_hand_in_the_bin` (Review Focus 2) — undo; `update_goal(id, {"is_active": True})`; restore → `goals_restored == 0`, goal active, its template active.
  - `test_null_snapshot_restores_like_before` (Review Focus 4) — undo, then set `undo_snapshot = None`; restore → ARCHIVED task comes back ACTIVE (documents the legacy path).
  - `test_unknown_status_in_snapshot_is_skipped` (Review Focus 5) — undo; overwrite one task's entry with `"bogus"` (reassign the whole dict so the JSON column change is detected); restore → that task DELETED, the other restored; `caplog` has a WARNING and does not contain the task's title.
- [ ] **Step 2: Run** — Expected: FAIL on the snapshot / completed / pre-archived tests (snapshot None, ARCHIVED→ACTIVE, archived project resurrected); the legacy test PASSES already (it pins today's behavior).
- [ ] **Step 3: Implement** per spec §3: in `undo_batch` capture each task's status and each goal/project's `is_active` BEFORE changing it, build the snapshot dict, assign `log.undo_snapshot` before the commit. In `restore_batch` branch on `log.undo_snapshot`: snapshot → `_restore_from_snapshot` (iterate the batch's rows; look each up by `str(row.id)`; task restored only if currently DELETED and the recorded value is a valid non-DELETED `TaskStatus`; goal/project only if listed and currently inactive), else `_restore_legacy`. Then `log.undo_snapshot = None`. In `purge_batch` set `log.undo_snapshot = None` next to `log.batch_id = None`. Update the `restore_batch` docstring and the module docstring (#367).
- [ ] **Step 4: Run** the new file + `tests/test_recycle_bin.py tests/test_project_archive_templates.py tests/test_goal_archive_templates.py` — Expected: all PASS.
- [ ] **Step 5: Commit** — `fix(#367): restore returns rows to their pre-undo state`

### Task 3: Help copy, BACKLOG, Phase 6

**Files:**
- Modify: `templates/docs.html` (`#recycle-bin`, the Restore bullet)
- Modify: `BACKLOG.md` (#367 → 🔄 IN PROGRESS)

- [ ] **Step 1:** Restore bullet becomes: `<li><strong>Restore</strong> — put every row back exactly as it was before the undo: completed tasks stay completed, and a project or goal you had already archived stays archived.</li>`. Fact-check table rows: completed stays completed → `recycle_service._restore_from_snapshot` + `undo_batch` snapshot lines; pre-archived stays archived → snapshot lists only goals/projects active at undo.
- [ ] **Step 2:** `python scripts/arch_sync_check.py`, `python scripts/docs_sync_check.py` → both OK.
- [ ] **Step 3: Phase 6** — seed, `.env.dev-bypass`, `preview_start taskmanager-dev-bypass`. At 1280×800 and 375×812 (emulated): `/docs#recycle-bin` shows the new bullet; `/recycle-bin?nosw=1` renders the seeded batches and Empty Bin button; restore one seeded batch from the UI and confirm its rows return (any completed rows stay completed); `scrollWidth <= innerWidth`; console 0. Tear down with `python scripts/stop_dev_bypass.py`; `ls .env.dev-bypass` → no such file.
- [ ] **Step 4: Commit** — `docs(#367): help copy + backlog`

### Task 4: Review, gate, ship

- [ ] **Step 1:** Final whole-branch review (fresh reviewer, most capable model); fix pass per executing-plans.
- [ ] **Step 2:** `bash scripts/run_all_gates.sh > <scratchpad>/gates_367.log 2>&1` → `ALL GATES GREEN`, `[100%]`, no `=== FAILURES ===`.
- [ ] **Step 3:** Squash to one commit `fix(#367): recycle-bin restore returns rows to their pre-undo state` with spec link, Gates trailer, `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- [ ] **Step 4:** DB backup, fast-forward `main` (merge commit if a bot commit landed), push. No tab reload.
- [ ] **Step 5:** `validate_deploy.py --monitor-minutes 5` (no `tail`), prod smoke with the cookie env; confirm migration applied (`migrations ok`).
- [ ] **Step 6:** Flip #367 ✅ with SHA; SOP report with Rulings / Deferred minors; delete branch + workspace; update `SESSION_HANDOFF.md`.
