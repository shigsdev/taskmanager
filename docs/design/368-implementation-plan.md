# #368 Goal Archive Pauses Templates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Archiving a goal pauses its running repeating templates and unarchiving resumes exactly those, with a second marker so a template on an archived project AND an archived goal resumes only when both are back.

**Architecture:** New column `RecurringTask.paused_by_goal_archive`. One shared helper `recurring_service.cascade_parent_archive` does the pause/resume for either parent; `project_service._set_project_active` and a new `goal_service._set_goal_active` call it and are the only writers of their parent's `is_active`. Marker hygiene mirrors #353 per parent. `/goals`' Archive confirm names the templates.

**Tech Stack:** Flask, SQLAlchemy 2.0, Alembic, vanilla JS (classic scripts, dual-export helpers), pytest, Jest, Playwright.

**Spec:** `docs/design/368-goal-archive-pauses-templates.md`

## Global Constraints

- Branch `feature/goal-archive-pauses-templates`, created from `main` AFTER #370 ships. Never commit to `main` directly.
- Windows: `source .superpowers/env.sh` before pytest (exports `PYTEST_ADDOPTS=--basetemp=...` with forward slashes). Use `python -m ruff`.
- Single-test runs: `python -m pytest <file>::<test> --no-cov -q -p no:cacheprovider`.
- Classic scripts share ONE global lexical scope: every new top-level name in `static/goal_archive_helpers.js` must be unique across `static/*.js` (grep before adding). No `innerHTML`.
- The marker never resumes anything on its own: clearing a marker leaves `is_active` alone (spec §4.3).
- Transition guard: `_set_goal_active` / `_set_project_active` do nothing when `is_active` already equals the target.
- Neither `_set_*_active` nor `cascade_parent_archive` commits; callers commit.
- Confirm copy, exact: `This will pause <n> repeating task(s): "<t1>", … [and <k> more]. They resume when you unarchive the goal.` — at most 5 named, `repeating task` singular for 1.
- `CACHE_VERSION` in `static/sw.js`: `v259` → `v260`.
- Before the push: `gh workflow run daily-backup.yml --ref main`, wait for success and a `[backup] pushed` log line. No green backup, no push.
- Stage files explicitly. Never stage `SESSION_HANDOFF.md`. Revert #362 audit-row noise in `BACKLOG.md` before staging.

## Review Focus

1. A template with a goal but **no project** (`project_id IS NULL`) must resume when its goal is unarchived — the "other marker" check must not treat a missing parent as archived. → Task 2 test `test_goal_only_template_resumes_on_unarchive`.
2. The `/recurring` **bulk** PATCH (`/api/recurring/bulk`, per-row `update_recurring`) toggling `is_active` must clear BOTH markers, or a later unarchive resurrects a template the user stopped. → Task 3 test `test_bulk_recurring_patch_clears_both_markers`.
3. A re-sent `DELETE /api/goals/<id>` on an already-archived goal must not re-pause a template the user resumed by hand (and must still clear `batch_id`). → Task 2 test `test_redelete_archived_goal_does_not_repause`.
4. If the `/api/recurring` lookup fails, the goal still archives, with no dialog — never block an archive on its confirm (#353 ruling: simulate with a 500, not `route.abort`, which triggers apiFetch's reload prompt). → Task 4 Playwright test `lookup failure archives without a dialog`.
5. The recurring editor re-sends an unchanged `goal_id` on every Save; that must keep the goal marker. → Task 3 test `test_resending_same_goal_id_keeps_goal_marker`.

---

### Task 1: Column, migration and backfill

**Files:**
- Modify: `models.py:350-360` (after `paused_by_project_archive`)
- Create: `migrations/versions/s8a9b0c1d2e3_recurring_paused_by_goal_archive.py`
- Modify: `architecture_schemas.py:117` (add sibling entry)
- Test: `tests/test_goal_archive_templates.py` (new)

**Interfaces:**
- Produces: `RecurringTask.paused_by_goal_archive: Mapped[bool]` (not null, default False, `server_default=sql_false()`); migration module constant `BACKFILL_SQL: tuple[str, str]`; revision `s8a9b0c1d2e3`, `down_revision = "r7f8a9b0c1d2"`.

- [ ] **Step 1: Write the failing test** — new file with helpers `_goal(title, *, active=True) -> Goal` (category `GoalCategory.WORK`, priority `GoalPriority.MUST`), `_project(...)`, `_recurring(title, *, project=None, goal=None, **kw)`, `_state(rt_id) -> tuple[bool, bool, bool]` returning `(is_active, paused_by_project_archive, paused_by_goal_archive)`, and `_load_migration()` loading the new revision file.

```python
def test_backfill_pauses_active_templates_on_archived_goals(app):
    with app.app_context():
        g_off = _goal("Old goal", active=False)
        g_on = _goal("Live goal")
        p_off = _project("Old project", active=False)
        a = _recurring("a", goal=g_off)                       # active → paused + goal marker
        b = _recurring("b", goal=g_off, is_active=False)      # user-paused → untouched
        c = _recurring("c", goal=g_off, project=p_off, is_active=False,
                       paused_by_project_archive=True)        # project-paused → + goal marker
        d = _recurring("d", goal=g_on)                        # untouched
        ids = a.id, b.id, c.id, d.id
        for stmt in _load_migration().BACKFILL_SQL:
            db.session.execute(sa.text(stmt))
        db.session.commit()
        assert _state(ids[0]) == (False, False, True)
        assert _state(ids[1]) == (False, False, False)
        assert _state(ids[2]) == (False, True, True)
        assert _state(ids[3]) == (True, False, False)
```

- [ ] **Step 2: Run it** — `python -m pytest tests/test_goal_archive_templates.py --no-cov -q -p no:cacheprovider`. Expected: FAIL (`paused_by_goal_archive` unknown / migration file missing).
- [ ] **Step 3: Implement** the column (comment mirroring the project marker's, citing #368 and spec §4.1), the migration (add column with `server_default=sa.false()`, then run both `BACKFILL_SQL` statements; downgrade drops the column and resumes nothing; docstring states expected prod effect 0 rows), and the `architecture_schemas.py` description: `{"desc": "Paused only because its goal was archived", "notes": "Unarchiving the goal resumes it once its project isn't archived either; a manual pause/resume, a goal change, a delete, or a recycle-bin purge of its goal clears it (#368)"}`. Backfill statement 1: `UPDATE recurring_tasks SET is_active = false, paused_by_goal_archive = true WHERE is_active = true AND goal_id IN (SELECT id FROM goals WHERE is_active = false)`; statement 2: `UPDATE recurring_tasks SET paused_by_goal_archive = true WHERE paused_by_project_archive = true AND goal_id IN (SELECT id FROM goals WHERE is_active = false)`.
- [ ] **Step 4: Run it** — same command. Expected: PASS. Also `FLASK_ENV=development python -m flask db upgrade` on the dev DB; expected: upgrades to `s8a9b0c1d2e3`.
- [ ] **Step 5: Commit** — `git add models.py migrations/versions/s8a9b0c1d2e3_recurring_paused_by_goal_archive.py architecture_schemas.py tests/test_goal_archive_templates.py && git commit -m "feat(#368): paused_by_goal_archive column + backfill"`

### Task 2: Shared cascade, `_set_goal_active`, every goal archive path

**Files:**
- Modify: `recurring_service.py` (new function near `delete_recurring`)
- Modify: `project_service.py:300-337` (`_set_project_active` body)
- Modify: `goal_service.py:133-160` (`update_goal` is_active branch, `delete_goal`)
- Modify: `recycle_service.py:266-268, 311-315` (goal loops), module docstring
- Test: `tests/test_goal_archive_templates.py`

**Interfaces:**
- Consumes: Task 1's column.
- Produces: `recurring_service.cascade_parent_archive(parent: str, parent_id: uuid.UUID, archived: bool) -> None` (`parent` in `{"project", "goal"}`, else `ValueError`); `goal_service._set_goal_active(goal: Goal, active: bool) -> None`.

- [ ] **Step 1: Write the failing tests** (HTTP through `authed_client` where a route exists; `_archive_goal(client, gid)` = `DELETE /api/goals/<gid>`, `_unarchive_goal` = `PATCH {"is_active": True}`, plus the project helpers from #353's test file re-declared locally):
  - `test_archive_goal_pauses_active_template_and_marks_it` → `(False, False, True)`; unarchive → `(True, False, False)`.
  - `test_patch_and_delete_archive_goal_identical` (parametrize PATCH `is_active: false` vs DELETE).
  - `test_user_paused_template_untouched_by_goal_archive_and_unarchive` → stays `(False, False, False)` throughout.
  - `test_redelete_archived_goal_does_not_repause` — archive, resume template by PATCH `is_active: true`, DELETE goal again → template `(True, False, False)`.
  - `test_goal_only_template_resumes_on_unarchive` — template with goal, `project_id` None → resumes.
  - `test_overlap_unarchive_project_first` — template on project P + goal G; archive P then G → `(False, True, True)`; unarchive P → `(False, False, True)`; unarchive G → `(True, False, False)`.
  - `test_overlap_unarchive_goal_first` — same, unarchive G first → `(False, True, False)`; then P → `(True, False, False)`.
  - `test_overlap_goal_archived_first_then_project` — archive G → `(False, False, True)`; archive P → `(False, True, True)`.
  - `test_reflection_apply_goal_update_and_delete_pause_templates` — mirror #353's `test_reflection_apply_update_and_delete_pause_templates` with goal `update` / `delete` actions.
  - `test_undo_batch_pauses_goal_templates` / `test_restore_batch_resumes_goal_templates` — an import batch holding one goal (`Goal(batch_id=...)` + `ImportLog`) with an active template; undo → `(False, False, True)`; restore → `(True, False, False)`.
  - `test_cascade_parent_archive_rejects_unknown_parent` → `pytest.raises(ValueError)`.
- [ ] **Step 2: Run them** — Expected: FAIL (template stays active on goal archive; `cascade_parent_archive` missing).
- [ ] **Step 3: Implement** `cascade_parent_archive` per spec §4.2 (two bulk `.update(..., synchronize_session=False)` calls per direction, in the spec's order — on unarchive, the "resume" update must run BEFORE the "clear only" update). Replace `_set_project_active`'s inline updates with `cascade_parent_archive("project", project.id, not active)`, keeping its guard and docstring (add the goal-marker interaction). Add `_set_goal_active` in `goal_service.py` (guard, set `is_active`, call `cascade_parent_archive("goal", goal.id, not active)`); `update_goal` and `delete_goal` call it (`delete_goal` still clears `batch_id`). `recycle_service` goal loops call `_set_goal_active(goal, False)` / `if not goal.is_active: _set_goal_active(goal, True); restored_goals += 1`.
- [ ] **Step 4: Run** the new file plus `tests/test_project_archive_templates.py tests/test_recycle_bin.py tests/test_goals*.py` — Expected: all PASS (#353/#356 behavior unchanged).
- [ ] **Step 5: Commit** — `feat(#368): archiving a goal pauses its repeating tasks`

### Task 3: Marker hygiene

**Files:**
- Modify: `recurring_service.py:339-370, 407-418` (`update_recurring` goal_id + is_active branches, `delete_recurring`)
- Modify: `project_service.py:271-277` (#352 goal re-point cascade)
- Modify: `recycle_service.py` `purge_batch` (beside #356's project-marker update)
- Modify: `models.py` / `architecture_schemas.py` flag comments if Task 1's wording needs the full list
- Test: `tests/test_goal_archive_templates.py`

**Interfaces:**
- Consumes: Task 2's `_set_goal_active` (via the API) and fixtures.

- [ ] **Step 1: Write the failing tests:**
  - `test_manual_resume_clears_both_markers` — overlap state `(False, True, True)`; PATCH template `is_active: true` → `(True, False, False)`; unarchive both parents → still `(True, False, False)`.
  - `test_bulk_recurring_patch_clears_both_markers` — overlap state; `PATCH /api/recurring/bulk` `{"template_ids": [id], "updates": {"is_active": true}}` → `(True, False, False)` (keys verified at `recurring_api.py:138-139`).
  - `test_delete_template_clears_both_markers` → `(False, False, False)`; unarchiving both leaves it.
  - `test_goal_change_clears_only_goal_marker` — overlap; PATCH `goal_id` to another live goal → `(False, True, False)`.
  - `test_resending_same_goal_id_keeps_goal_marker` → unchanged.
  - `test_project_move_to_new_goal_clears_goal_marker` — project on archived goal G1 with a goal-paused template; PATCH project `goal_id` → live G2 → template `(False, False, False)`, `goal_id == G2`.
  - `test_purge_goal_clears_only_goal_marker_and_resumes_nothing` — undo a batch holding goal G; template also on an archived project → `(False, True, True)`; purge (with `_fk_on()`) → `(False, True, False)`, `goal_id is None`; unarchive the project → `(True, False, False)`.
- [ ] **Step 2: Run them** — Expected: FAIL on every marker assertion.
- [ ] **Step 3: Implement** per spec §4.3: `is_active` actual change and `delete_recurring` clear both; `goal_id` actual change clears the goal marker; #352 cascade sets `paused_by_goal_archive=False` in the RecurringTask update only (Task rows have no marker — split the loop); `purge_batch` adds `update(RecurringTask).where(RecurringTask.goal_id.in_(goal_ids)).values(paused_by_goal_archive=False)` before the deletes, with a #368 comment.
- [ ] **Step 4: Run** the new file + #353/#356 test files — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(#368): goal-archive marker hygiene`

### Task 4: `/goals` Archive confirm

**Files:**
- Modify: `static/goal_archive_helpers.js` (two functions + both export blocks)
- Modify: `static/goals.js:448-466` (`goalDetailToggleArchive` archive branch)
- Modify: `static/sw.js:8` (`v260`)
- Test: `tests/js/unit/goal_archive_helpers.test.js`, `tests/e2e/pages.spec.js` (new describe after #353's at `:5515`)

**Interfaces:**
- Produces: `templatesPausedByGoal(templates: Array, goalIds: Array<string>) -> Array` (active templates whose `goal_id` is in `goalIds`; `[]` for non-array input); `goalArchivePauseMessage(paused: Array) -> string` (`""` for none).

- [ ] **Step 1: Write the failing Jest tests:** filters to active + matching goal; ignores inactive and other goals; `null` / `{error}` / `undefined` / empty ids → `[]`; message for 1 (`This will pause 1 repeating task: "A". They resume when you unarchive the goal.`), for 2 (plural), for 7 (5 named + ` and 2 more`), for `[]` → `""`.
- [ ] **Step 2: Run** `npx jest tests/js/unit/goal_archive_helpers.test.js` — Expected: FAIL (not exported).
- [ ] **Step 3: Implement** the two helpers (grep `static/` first: no existing top-level `templatesPausedByGoal`, `goalArchivePauseMessage`, or the max-named constant name you pick), export them, wire `goalDetailToggleArchive`: archive branch fetches `/api/recurring` in a try/catch (on error `console.warn`, message `""`), `if (msg && !confirm(msg)) return;` before the DELETE. Unarchive branch unchanged. Bump `CACHE_VERSION`.
- [ ] **Step 4: Run** Jest — Expected: PASS. Then write the Playwright describe `"Archiving a goal pauses its repeating tasks (#368) @noviewport"`, reusing the #349 describe's patterns (`makeGoal`, card click to open the panel, `#goalDelete`): (a) goal with one active template → dialog text contains the title and `They resume when you unarchive the goal.`, accept → `GET /api/recurring/<id>` `is_active` false; unarchive → no dialog, `is_active` true; (b) goal with no templates → no dialog fires, goal archived; (c) `lookup failure archives without a dialog` — `page.route("**/api/recurring", r => r.fulfill({status: 500, body: "{}"}))`, click Archive → no dialog, goal archived. Clean up: detach + delete templates, then `DELETE /api/goals/<id>/permanent`. Run: `npx playwright test tests/e2e/pages.spec.js -g "#368"` — Expected: 3 passed.
- [ ] **Step 5: Commit** — `feat(#368): /goals archive confirm names the repeating tasks it pauses`

### Task 5: Docs, BACKLOG, Phase 6

**Files:**
- Modify: `templates/docs.html` (~`:1501` "When its project is archived" → covers goals too; ~`:2245` "Archiving a goal" gains a paragraph)
- Modify: `docs/adr/038-project-archive-preserves-task-links.md` (consequences: second parent, two markers)
- Modify: `ARCHITECTURE.md` (PostgreSQL box column list + the #353 bullet)
- Modify: `CLAUDE.md` Phase 6 step 7 + Regression Report rows `Goals: archive pauses tmpl` / `Goals: no-tmpl archive quiet`
- Modify: `BACKLOG.md` (#368 → 🔄 IN PROGRESS; notes on #364 and #369 that goal archives apply too)

- [ ] **Step 1:** Draft the Help copy; build the fact-check table (claim → `file:line`) for the review message. Claims to cite at minimum: what pauses (active only), when it resumes (neither parent archived), what the confirm says, that a user-paused template stays paused, that clearing never resumes.
- [ ] **Step 2:** Update ADR / ARCHITECTURE / CLAUDE.md / BACKLOG as listed. Run `python scripts/arch_sync_check.py` and `python scripts/docs_sync_check.py` — Expected: both pass.
- [ ] **Step 3: Phase 6** — seed, `.env.dev-bypass`, `preview_start taskmanager-dev-bypass` (restart after any template edit). At 1280×800 and 375×812: `/goals?nosw=1` archive a goal with a template → confirm names it → `/recurring` no longer lists it → unarchive restores it; archive a goal with none → no dialog; `/docs` new copy renders; `scrollWidth <= innerWidth`; console 0. Tear down with `python scripts/stop_dev_bypass.py`; `ls .env.dev-bypass` → no such file.
- [ ] **Step 4: Commit** — `docs(#368): help, ADR-038, architecture, SOP rows`

### Task 6: Gate, ship, validate

- [ ] **Step 1:** Final whole-branch review (fresh reviewer, most capable model); fix pass per executing-plans.
- [ ] **Step 2:** `bash scripts/run_all_gates.sh > <scratchpad>/gates_368.log 2>&1` (PYTEST_ADDOPTS exported). Expected: `ALL GATES GREEN`, `[100%]`, no `=== FAILURES ===`.
- [ ] **Step 3:** Squash to one gated commit `fix(#368): archiving a goal pauses its repeating tasks` with spec link, Gates trailer, `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Revert audit-row noise first.
- [ ] **Step 4:** DB backup (Global Constraints), then fast-forward `main`, push. Tell the user the `CACHE_VERSION` bump reloads open tabs within ~60s.
- [ ] **Step 5:** `python scripts/validate_deploy.py --monitor-minutes 5` (no `tail`); prod smoke with the cookie env. Expected: DEPLOY GREEN, MONITOR GREEN, all smoke pass. Confirm prod backfill touched 0 rows (read-only: no active template on an archived goal).
- [ ] **Step 6:** Flip #368 ✅ with SHA, commit + push; SOP report with Rulings / Deferred minors; delete branch + workspace; update `SESSION_HANDOFF.md`.
