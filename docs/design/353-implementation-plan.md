# #353 Project Archive Pauses Templates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Archiving a project, by any path, pauses its active repeating templates and remembers which ones. Unarchiving resumes only those. Archiving stops detaching tasks.

**Architecture:** A new `RecurringTask.paused_by_project_archive` flag. One service function, `project_service._set_project_active`, is the only writer of `Project.is_active` in this module; `update_project`, `delete_project`, the bulk paths and the reflection apply path all reach it. `recurring_service` clears the flag whenever the user overrides it. A new dual-export helper builds the `/projects` confirm text.

**Tech Stack:** Flask + SQLAlchemy 2.0, Alembic, vanilla JS (classic scripts, dual-export helpers), pytest, Jest, Playwright.

**Spec:** `docs/design/353-project-archive-pauses-templates.md` (approved 2026-10-01). Read it alongside this plan; section refs below (§4.1 etc.) point into it.

## Global Constraints

- Branch: `feature/project-archive-pauses-templates`. Never commit to `main` directly.
- **No intermediate commits.** CLAUDE.md requires the full `bash scripts/run_all_gates.sh` before EVERY commit (~35 min). So tasks end with targeted test runs (`--no-cov -q`), and Task 7 makes one gated commit. Per-task "commit" steps are deliberately absent.
- Stage files explicitly. Never `git add -A` / `git add .`; `SESSION_HANDOFF.md` is untracked and must stay out.
- Migration parent: `down_revision = "q6e7f8a9b0c1"`.
- Flag name everywhere: `paused_by_project_archive` (Python, SQL, JSON if serialized).
- Service function name: `_set_project_active(project: Project, active: bool) -> None`. It never commits.
- New static asset: `static/project_archive_helpers.js`, global `window.projectArchiveHelpers`. Its export tail builds the object inline on both branches, with **no top-level binding** (shared classic-script scope; see #359).
- Never `innerHTML` in new code. A PreToolUse hook blocks Edit/Write containing it.
- Confirm copy (spec §4.4, exact): `This will pause N repeating task(s): "A", "B". They resume when you unarchive the project.` Use singular wording when N = 1 (`1 repeating task`). Cap at 5 names, then `and N more`.
- Windows: run pytest with `PYTEST_ADDOPTS='--basetemp=<scratchpad>/pytest-basetemp'` (forward slashes) for the full suite. `python -m ruff` (bare `ruff` is not on PATH).
- Expect gate runs to rewrite the `coverage/overall-coverage-drift/` row in BACKLOG.md (#362). Drop that hunk before staging.

## Review Focus

1. **A `/recurring` editor Save on an archive-paused template.** The editor re-sends `project_id` (unchanged) on every Save and never sends `is_active`, so the flag must survive. Pinned in Task 3 as a route-level test with the real editor payload shape.
2. **Bulk archive where one row fails validation.** `bulk_update_projects` rolls back that row. Its template pause must roll back with it, and earlier rows' pauses must stay. Pinned in Task 2.
3. **The impact fetch fails (offline / 500).** The archive must still go through, with no extra dialog text. Pinned in Task 5 (Playwright route abort) and Task 4 (helper given `null` templates).
4. **Archive twice / archive from two tabs.** The second write is a no-op transition, and a template resumed by hand in between stays resumed. Pinned in Task 2 (spec test 6).
5. **A project archived via the recycle bin's `undo_batch`.** It writes `is_active=False` directly and bypasses the cascade by design (#356), so templates on an undone import's projects keep firing. Pin the *current* behavior in Task 2 with a test named `test_undo_batch_does_not_pause_templates_356`, so #356 has to change it on purpose rather than by accident.

---

### Task 1: Column, migration with backfill, schema docs

**Files:**
- Modify: `models.py` (class `RecurringTask`, after `is_active` at `:349`)
- Create: `migrations/versions/r7f8a9b0c1d2_recurring_paused_by_project_archive.py`
- Modify: `architecture_schemas.py:97-120` (`recurring_tasks.columns`)
- Modify: `ARCHITECTURE.md` (PostgreSQL box, `recurring_tasks` line)
- Test: `tests/test_project_archive_templates.py` (new; this task adds the migration test)

**Interfaces:**
- Produces: `RecurringTask.paused_by_project_archive: Mapped[bool]` (NOT NULL, default False). Migration module constant `BACKFILL_SQL: str`.

- [ ] **Step 1: Write the failing migration test** `test_backfill_pauses_active_templates_on_archived_projects`. Seed: archived project P with active template A and inactive template B; active project Q with active template C. Load the revision with `importlib.util.spec_from_file_location`, then `db.session.execute(sa.text(mod.BACKFILL_SQL))`; commit. Assert A is `is_active False`, flag `True`; B is unchanged (`False`/`False`); C is unchanged (`True`/`False`).
- [ ] **Step 2: Run** `python -m pytest tests/test_project_archive_templates.py --no-cov -q`. Expected: FAIL (attribute / file missing).
- [ ] **Step 3: Implement.** Add the model column (comment cites #353 and spec §4.3). Migration `revision = "r7f8a9b0c1d2"`, `down_revision = "q6e7f8a9b0c1"`. `upgrade()`: `op.add_column(..., sa.Column("paused_by_project_archive", sa.Boolean(), nullable=False, server_default=sa.false()))`, then `op.execute(BACKFILL_SQL)`. `downgrade()` drops the column only (spec decision 9). `BACKFILL_SQL` is the spec §4.5 statement verbatim. Add the `_SCHEMA_DESCRIPTIONS` entry: desc `"Paused only because its project was archived"`, notes `"Unarchiving the project resumes it; any manual pause/resume, move or delete clears it (#353)"`. Add the column to ARCHITECTURE.md's `recurring_tasks` line.
- [ ] **Step 4: Run** the test file, plus `python -m pytest tests/test_architecture*.py --no-cov -q` (the `test_every_column_has_a_description` drift gate). Expected: PASS.
- [ ] **Step 5: Verify** the migration applies to the dev DB: `FLASK_ENV=development python -m flask db upgrade`, then `python -m flask db current` shows `r7f8a9b0c1d2 (head)`.

---

### Task 2: The shared cascade in `project_service` + ADR-038

**Files:**
- Modify: `project_service.py:279-282` (`update_project` `is_active` branch), `:300-325` (`delete_project`)
- Create: `docs/adr/038-project-archive-preserves-task-links.md`
- Modify: `tests/test_projects_api.py:499-509`, `tests/test_project_goal_cascade.py:260-268`
- Test: `tests/test_project_archive_templates.py`

**Interfaces:**
- Consumes: the Task 1 column.
- Produces: `_set_project_active(project: Project, active: bool) -> None` (spec §4.1 body is normative). `delete_project(project_id) -> bool` keeps its signature.

- [ ] **Step 1: Write the failing tests** in `tests/test_project_archive_templates.py`, one per spec test 1–9, named:
  `test_archive_pauses_active_template_and_flags_it`,
  `test_archive_leaves_already_paused_template_unflagged`,
  `test_unarchive_resumes_only_flagged_templates`,
  `test_delete_and_patch_archive_have_identical_template_effect` (parametrized over the two calls),
  `test_bulk_patch_and_bulk_delete_cascade_per_row` (`PATCH /api/projects/bulk` with `{"project_ids": [...], "updates": {"is_active": false}}` and `DELETE /api/projects/bulk` with `{"project_ids": [...]}`),
  `test_noop_archive_does_not_repause_a_manually_resumed_template`,
  `test_templates_on_other_projects_untouched`,
  `test_reflection_apply_update_and_delete_pause_templates` (via `reflection_service.apply_selected_actions(reflection, actions)` with `{"op": "update", "entity": "project", "id": pid, "payload": {"is_active": False}}` and `{"op": "delete", "entity": "project", "id": pid2}`; seed the reflection the way `tests/test_reflection.py:313-325` does),
  `test_archive_preserves_task_project_and_goal_links` (both PATCH and DELETE).
  Plus the Review Focus pins:
  `test_bulk_archive_row_failure_rolls_back_only_that_rows_pause` (one valid id plus one id whose `update_project` raises `ValidationError`; force it with `monkeypatch` on the second call) and
  `test_undo_batch_does_not_pause_templates_356` (build a batch with `tests/test_recycle_bin.py:41`'s `_make_batch(project_names=[...])` pattern, attach an active template to that project, call `recycle_service.undo_batch(batch_id)`, and assert the template is still `is_active True` and unflagged).
  Use the `_project` / template builders from `tests/test_project_goal_cascade.py:50-60` and `:288-296` (copy them; don't import across test modules).
- [ ] **Step 2: Update the two PR63 tests.** In `test_projects_api.py:507-508`, assert `project_id == pid` for both tasks. In `test_project_goal_cascade.py:266`, assert `task.project_id == pid`. Rename both tests to say "preserves". Keep the `goal_id == gid` assertion.
- [ ] **Step 3: Run** `python -m pytest tests/test_project_archive_templates.py tests/test_projects_api.py tests/test_project_goal_cascade.py --no-cov -q`. Expected: the new cascade tests and the two updated tests FAIL. The `undo_batch` pin and `test_templates_on_other_projects_untouched` already pass today; that's expected, since they pin behavior that must NOT change.
- [ ] **Step 4: Implement.** Add `_set_project_active` (spec §4.1). In `update_project`, keep the bool validation, then call `_set_project_active(project, data["is_active"])` instead of assigning. Replace `delete_project`'s body with get, `_set_project_active(project, False)`, commit. Rewrite its docstring to cite #353 and ADR-038, and remove the detach. Import `RecurringTask` in `project_service.py` if it isn't already.
- [ ] **Step 5: Write ADR-038** in the house format (see `docs/adr/037-*.md`): Status ACCEPTED (user-approved 2026-10-01 via the #353 spec). Supersedes: the PR63 #129 task-detach in `delete_project` (an audit fix, not an ADR). Sections: Context (the two paths disagreed; 270 prod tasks already preserved by the button path), Decision, Why the detach is no longer needed (the four read-side guards from spec §3 with file:line), Consequences (Delete-then-unarchive is now lossless; #356 still owes the recycle paths).
- [ ] **Step 6: Run** the same three files. Expected: all PASS.

---

### Task 3: Flag hygiene in `recurring_service`

**Files:**
- Modify: `recurring_service.py:341-342` (`project_id`), `:357-358` (`is_active`), `:395-402` (`delete_recurring`)
- Test: `tests/test_project_archive_templates.py`

**Interfaces:**
- Consumes: the Task 1 column; Task 2's `_set_project_active` (to reach the flagged state in tests via `PATCH /api/projects/<id>`).

- [ ] **Step 1: Write the failing tests** (spec tests 10–13 plus Review Focus 1):
  `test_manual_resume_clears_flag_and_unarchive_leaves_it_alone`,
  `test_moving_paused_template_clears_flag_and_it_stays_paused`,
  `test_deleting_paused_template_clears_flag_so_unarchive_cannot_resurrect_it`,
  `test_resending_same_is_active_or_project_id_keeps_flag` (PATCH `/api/recurring/<id>` with `{"is_active": false}`, then with `{"project_id": <same>}`; flag still True; an unarchive then resumes it),
  `test_recurring_editor_save_payload_keeps_flag`. This one PATCHes `/api/recurring/<id>` with the shape `recurringHelpers.buildRecurringEditPayload` produces. Read `static/recurring_helpers.js` for the exact keys. It includes `project_id` (unchanged) and has no `is_active`. Assert the flag is still True and that unarchiving resumes the template.
- [ ] **Step 2: Run** the file. Expected: the first three and the editor test FAIL.
- [ ] **Step 3: Implement** in `update_recurring`: parse `project_id` first; if the parsed value `!= rt.project_id`, assign it and set the flag False. Same for `is_active`: compare `bool(data["is_active"])` to the current value, and clear the flag only on a change. In `delete_recurring`, set the flag False unconditionally (spec §4.3 table).
- [ ] **Step 4: Run** the file plus `tests/test_recurring*.py`. Expected: all PASS.

---

### Task 4: `project_archive_helpers.js` + Jest + asset cascade

**Files:**
- Create: `static/project_archive_helpers.js`
- Create: `tests/js/unit/project_archive_helpers.test.js`
- Modify: `static/sw.js` (`APP_SHELL` + `CACHE_VERSION` v258 → v259), `health.py` (`EXPECTED_STATIC_FILES`), `templates/projects.html` (`<script>` before `projects.js`, after `archived_option_helpers.js` at `:177`)

**Interfaces:**
- Produces, on `window.projectArchiveHelpers` and `module.exports`:
  - `templatesPausedBy(templates: Array<{id, title, project_id, is_active}> | null, projectIds: string[]) -> Array<{id, title, project_id}>`. It returns only templates that are active and whose `project_id` is in `projectIds`. A `null` / non-array input returns `[]`.
  - `archiveConfirmMessage(paused: Array<{title}>) -> string`. It returns `""` for an empty list, otherwise the exact copy from Global Constraints.
  - `MAX_NAMED: 5`.

- [ ] **Step 1: Write the failing Jest tests:** filtering (other project, null `project_id`, inactive template excluded); `null` input → `[]`; 0 → `""`; 1 → `This will pause 1 repeating task: "A". They resume when you unarchive the project.`; 2 → `This will pause 2 repeating tasks: "A", "B". …`; 7 → five names plus `and 2 more`; titles containing `"` and `<b>` appear verbatim; two project ids aggregate.
- [ ] **Step 2: Run** `npx jest tests/js/unit/project_archive_helpers.test.js`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the module with the dual-export pattern of `static/archived_option_helpers.js`, including its export tail. Wire the asset cascade (files above).
- [ ] **Step 4: Run** the Jest file, plus `python -m pytest tests/test_static_assets*.py tests/test_health*.py --no-cov -q` (APP_SHELL / EXPECTED_STATIC_FILES drift gates; adjust the globs to whatever `ls tests` shows). Expected: PASS.
- [ ] **Step 5: Check for global-scope collisions by hand** (#359 has no gate yet): `grep -nE "^(const|let|var|function|class) " static/project_archive_helpers.js` must show nothing outside the IIFE.

---

### Task 5: Wire the confirms on `/projects` (C1–C3) + Playwright

**Files:**
- Modify: `static/projects.js:789-805` (`projectDetailToggleArchive`), `:937-942` (bulk Archive), `:944-957` (bulk Delete)
- Test: `tests/e2e/pages.spec.js`

**Interfaces:**
- Consumes: `window.projectArchiveHelpers.templatesPausedBy` / `.archiveConfirmMessage` (Task 4); `GET /api/recurring` (active only by default).

- [ ] **Step 1: Write the failing Playwright tests** in a `describe("#353 archive pauses repeating tasks")` block:
  `archive confirm names the template; unarchive resumes it`. Create a project and an attached template via the API, open its detail panel, click `#projectArchiveToggle`, and capture the dialog with `page.once("dialog")`. Assert the message contains the template title and `They resume when you unarchive the project.` Accept. Then `GET /api/recurring?all=1` shows the template `is_active: false`. Click Unarchive (no dialog expected) → template `is_active: true`.
  `archiving a project with no templates shows no dialog`. Fail the test if any dialog fires.
  `bulk archive confirm lists templates across two projects`.
  `impact fetch failure still archives` (Review Focus 3). `page.route("**/api/recurring", r => r.abort())`, then Archive; with no templates named, C1 shows no dialog and the project ends up archived.
  Clean up created rows in `afterEach` using the file's existing teardown pattern.
- [ ] **Step 2: Run** `npx playwright test tests/e2e/pages.spec.js -g "#353"` (the dev bypass must be up; see CLAUDE.md). Expected: FAIL.
- [ ] **Step 3: Implement.** A small async function, `projectsArchiveImpactMessage(ids) -> Promise<string>`, fetches `/api/recurring`, returns `archiveConfirmMessage(templatesPausedBy(rows, ids))`, and returns `""` on any fetch error. C1: only when archiving (`newState === false`), and if the message is non-empty, `confirm(message)`; bail on cancel. C2/C3: append `"\n\n" + message` to the existing confirm text when non-empty.
- [ ] **Step 4: Run** the `-g "#353"` tests. Expected: PASS.

---

### Task 6: User-facing docs, SOP checklist, Phase 6

**Files:**
- Modify: `templates/docs.html` (Projects section around `:2112-2117`; Recurring section `#recurring` around `:1459`)
- Modify: `CLAUDE.md` (Phase 6 step 6 / Projects line, plus the Regression Test Report template: new rows `Projects: archive pauses templates` and `Projects: no-template archive is silent`)
- Modify: `ARCHITECTURE.md` (the Components / Data Flows bullet for project archive)

- [ ] **Step 1: Draft the Help copy.** In Projects, replace "Archiving a project does not: … its tasks keep theirs." with: archiving keeps the tasks' project *and* goal links, pauses the project's repeating tasks after telling you which ones, and unarchiving resumes exactly those. In Recurring, add one sentence: a template paused by archiving resumes on unarchive, and (until #363) paused templates don't appear on `/recurring`.
- [ ] **Step 2: Fact-check table.** One row per claim, cited `file:line` against the code from Tasks 2–5. Present it to the user with the shipping report (review-only; not shipped).
- [ ] **Step 3: Phase 6** at 1280×800 and 375×812 via the dev bypass (`python scripts/seed_dev_data.py`, `preview_start taskmanager-dev-bypass`, `?nosw=1`). Cover: the C1 dialog names the template; Unarchive has no dialog and the template is active again; a no-template archive is silent; the C2 and C3 dialogs; the board still shows no badge for a task on an archived project; console 0 errors; viewport parity `scrollWidth <= innerWidth`; Archive button ≥ 44×44 on mobile. Seed note: the "Community of Practice" fixture (archived, with a template) exists from #355. Its template is already inactive, so create an active one via the API for the C1 check, and delete it afterwards. Teardown: `python scripts/stop_dev_bypass.py`; `ls .env.dev-bypass` → no such file.

---

### Task 7: Gate, ship, validate

- [ ] **Step 1: Run** `bash scripts/run_all_gates.sh > <scratchpad>/gates_353.log 2>&1` (with the `PYTEST_ADDOPTS` basetemp). Expected in the log: `ALL GATES GREEN`, and `[100%]` with no `=== FAILURES ===`.
- [ ] **Step 2: Drop the #362 noise hunk** from BACKLOG.md (`git diff BACKLOG.md`; restore the `coverage/overall-coverage-drift/` line to its committed text). Keep the #362/#363/#364 rows.
- [ ] **Step 3: Commit** with every file staged explicitly: `fix(#353): archiving a project pauses its repeating tasks`. The body includes the spec link, ADR-038, the PR63 reversal, the CLAUDE.md SOP checklist change, the Gates trailer and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- [ ] **Step 3b: Fresh prod backup BEFORE the push** (user request 2026-10-01). The migration's backfill changes live rows on deploy. Run `gh workflow run daily-backup.yml --ref main`, find the new run (`gh run list --workflow daily-backup.yml -L 1`), and wait for it with `gh run watch <id> --exit-status`. Expected: `completed success`, newer than the push. **No green backup, no push.** Record the run id in the ledger and the SOP report. Restore path if needed: `scripts/restore_drill.py` / the Fernet key in 1Password.
- [ ] **Step 4: Fast-forward** `main`, then push. Tell the user that CACHE_VERSION v259 will reload an open tab within ~60s.
- [ ] **Step 5: Validate.** Run `python scripts/validate_deploy.py --monitor-minutes 5` (full log, never `tail`). Confirm `migrations ok` at the new head. Then `npm run test:e2e:prod`. Verify the served `sw.js` v259 and `project_archive_helpers.js` 200. Verify the backfill landed: `GET /api/recurring?all=1` (validator cookie) shows *"menti survey for april cop session"* `is_active: false`.
- [ ] **Step 6: Flip BACKLOG #353 → ✅**, then run gates, commit and push (the same pattern as `52b92a5`). Print the SOP report and delete the branch.
