# #369 Import-Undo Confirm Names Paused Templates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Settings → Import History Undo confirm names the repeating tasks the undo will pause, and reads exactly as today when there are none.

**Architecture:** A read-only server query (`recurring_service.templates_paused_by_archive`) mirrors the archive branch of `cascade_parent_archive`; `recycle_service.undo_impact` applies it to the batch's active projects and goals; `GET /api/recycle-bin/impact/<batch_id>` exposes it. `settings.js` fetches it before `confirm()` and formats it with the existing `/projects` message builder, which gains an optional tail.

**Tech Stack:** Flask, SQLAlchemy 2.0, pytest, Jest, Playwright.

**Spec:** `docs/design/369-undo-confirm-names-paused-templates.md`

## Global Constraints

- Branch `fix/369-undo-confirm-names-paused-templates`. Never commit to `main` directly.
- Tail copy, exact: `They resume if you restore this import from the Recycle Bin.`
- `archiveConfirmMessage(paused)` with no tail must return byte-identical text to today (`/projects` unchanged).
- The impact route is GET on its own path `/impact/<batch_id>`; never a GET on `/undo/<id>` (#190).
- `undo_impact` writes nothing and never commits.
- A failed lookup (network, non-2xx, helper missing) falls back to today's confirm text; it never blocks the undo.
- DOM via `createElement` / `textContent` only; never `innerHTML`. Don't touch the pre-existing `innerHTML` lines in `settings.js` renderImports.
- `settings.js` is a classic script: no new top-level `const`/`let` (it's already wrapped; keep new code inside the existing closure).
- Bump `CACHE_VERSION` in `static/sw.js` v261 → v262.
- Before the push: `gh workflow run daily-backup.yml --ref main`, wait for success + `[backup] pushed`.
- Stage files explicitly; never `SESSION_HANDOFF.md`; revert #362 audit-row noise in `BACKLOG.md` before staging.

## Review Focus

1. **Parity with the real cascade:** the ids the dialog lists must equal the ids `undo_batch` actually pauses for a mixed fixture (project match, goal match, both, user-paused, outside-batch, already-archived parent). → Task 1 `test_impact_matches_what_undo_actually_pauses`.
2. **A template paused by the OTHER parent's archive** (inactive, `paused_by_goal_archive=True`, on a batch project): undo only adds a marker, so not listed. → Task 1 `test_template_paused_by_other_archive_not_listed`.
3. **Lookup fails (500):** the dialog still shows today's text and OK still undoes the batch. → Task 2 Playwright `lookup failure falls back to today's confirm`.
4. **Cancel after a slow lookup:** the button comes back as an enabled "Undo" and nothing moves to the bin. → Task 2 Playwright `cancel leaves the import live`.
5. **Batch already undone (another tab):** impact → 409 → the client falls back; the existing POST 409 path then shows "Undo failed". → Task 1 route test `test_impact_409_when_already_undone`; the client fallback is covered by (3)'s code path.

---

### Task 1: Server — query helper, `undo_impact`, impact route

**Files:**
- Modify: `recurring_service.py` (new function after `cascade_parent_archive`)
- Modify: `recycle_service.py` (new `undo_impact` after `undo_batch`; import `templates_paused_by_archive`)
- Modify: `recycle_api.py` (new route + module docstring endpoint list)
- Test: `tests/test_undo_impact.py` (new; fixtures modelled on `tests/test_recycle_restore_snapshot.py` `_batch` / `_goal` / `_project` + a `_template(project=None, goal=None, active=True, title=...)`)

**Interfaces:**
- Produces: `recurring_service.templates_paused_by_archive(project_ids: Iterable[uuid.UUID], goal_ids: Iterable[uuid.UUID]) -> list[RecurringTask]` — `is_active` AND (`project_id` in P OR `goal_id` in G), ordered by `title`; both empty → `[]` with no query.
- Produces: `recycle_service.undo_impact(batch_id: uuid.UUID) -> dict` = `{"batch_id": str, "paused_templates": [{"id": str, "title": str}]}`; raises `BatchNotFoundError` / `BatchStateError`.
- Produces: `GET /api/recycle-bin/impact/<batch_id>` → 200 that dict; 400 bad uuid; 404; 409.

- [ ] **Step 1: Write the failing tests** — service: `test_template_on_batch_project_listed`, `test_template_on_batch_goal_listed`, `test_template_on_both_listed_once`, `test_user_paused_template_not_listed`, `test_template_paused_by_other_archive_not_listed`, `test_template_outside_batch_not_listed`, `test_already_archived_batch_project_skipped`, `test_impact_matches_what_undo_actually_pauses` (snapshot `is_active` per template before, `undo_batch`, compare the set that flipped True→False to the impact ids), `test_impact_is_read_only` (no `is_active` / marker change, `db.session.dirty` empty, log `undone_at` still None), `test_listed_in_title_order`, `test_empty_inputs_return_empty_list`; route: `test_impact_route_200_shape`, `test_impact_400_bad_id`, `test_impact_404_unknown_batch`, `test_impact_409_when_already_undone`, `test_impact_requires_login` (plain `client` → 401/302 as sibling tests expect).
- [ ] **Step 2: Run** `python -m pytest tests/test_undo_impact.py --no-cov -q -p no:cacheprovider` — Expected: FAIL (ImportError / 404).
- [ ] **Step 3: Implement** the three pieces. Helper docstring names `cascade_parent_archive`'s archive branch as the rule it mirrors and #364 as the second consumer. `undo_impact` uses `_batch_projects` / `_batch_goals` filtered to `is_active` (the transition guard in `_set_*_active`).
- [ ] **Step 4: Run** the same command — Expected: all PASS. Then `python -m pytest tests/test_recycle_bin.py tests/test_recycle_restore_snapshot.py --no-cov -q -p no:cacheprovider` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(#369): undo impact lookup lists the repeating tasks an undo pauses`.

### Task 2: Client — helper tail, Settings Undo confirm

**Files:**
- Modify: `static/project_archive_helpers.js` (`archiveConfirmMessage(paused, tail)`; header comment notes #369 second consumer)
- Modify: `templates/settings.html` (`<script>` for `project_archive_helpers.js` before `settings.js`)
- Modify: `static/settings.js` `onUndoClick`
- Modify: `static/sw.js` `CACHE_VERSION` v262
- Test: `tests/js/unit/project_archive_helpers.test.js`, `tests/e2e/pages.spec.js` (new describe at the end)

**Interfaces:**
- Consumes: `GET /api/recycle-bin/impact/<batch_id>` (Task 1).
- Produces: `archiveConfirmMessage(paused: Array<{title}>, tail?: string) -> string`.

- [ ] **Step 1: Write the failing Jest tests** — `custom tail replaces the project tail`: `archiveConfirmMessage([{title:"A"}], "X.")` → `'This will pause 1 repeating task: "A". X.'`; `omitted tail keeps the project tail` (existing TAIL); `empty list is "" even with a tail`.
- [ ] **Step 2: Run** `npx jest tests/js/unit/project_archive_helpers.test.js` — Expected: the custom-tail test FAILS.
- [ ] **Step 3: Implement** the optional `tail` (`typeof tail === "string" && tail ? tail : TAIL`). Run Jest — PASS.
- [ ] **Step 4: Write the Playwright describe** `Import undo names the repeating tasks it pauses (#369) @noviewport`: fixture = `POST /api/import/projects/confirm` `{candidates:[{name, type:"work"}], source:"E2E 369 <stamp>"}` + optional `POST /api/recurring` `{project_id}`; find the Settings row by its source text. Tests: (a) `the undo confirm names the template` — message contains `"<title>"` and the tail, accept → batch shows "In Recycle Bin", template inactive; (b) `an import with no repeating tasks gets today's confirm` — message has no `repeating task`; (c) `cancel leaves the import live` — dismiss → button enabled with text `Undo`, template still active; (d) `lookup failure falls back to today's confirm` — `page.route("**/api/recycle-bin/impact/**")` → 500, message has no `repeating task`, accept still undoes. Cleanup: restore (if undone) not needed — purge via `POST /api/recycle-bin/purge/<id>` `{confirmation:"DELETE"}` after undo; for live batches undo then purge; delete templates first.
- [ ] **Step 5: Implement `onUndoClick`** per spec §4.2: disable + "Checking…", `window.apiFetch("/api/recycle-bin/impact/" + batchId)`, `.then` build extra via `window.projectArchiveHelpers && window.projectArchiveHelpers.archiveConfirmMessage(data.paused_templates, UNDO_TAIL)`, `.catch(() => "")`, then confirm(base + (extra ? "\n\n" + extra : "")); cancel → re-enable "Undo"; OK → "Undoing…" + the existing POST chain unchanged.
- [ ] **Step 6: Run** the new Playwright describe against the bypass (via `run_all_gates.sh` in Task 3) — Expected: PASS.
- [ ] **Step 7: Commit** `feat(#369): Settings Undo confirm names the repeating tasks it will pause`.

### Task 3: Docs, cascade, gates

**Files:** `templates/docs.html` (#recycle-bin: fix "or via the Recycle Bin"; add the confirm sentence), `ARCHITECTURE.md` (Data Flows + Route catalog `/api/recycle-bin/impact/<batch_id>`), `CLAUDE.md` (Phase 6 step 9 + two Regression Report rows), `BACKLOG.md` (#369 → 🔄 IN PROGRESS; file #373; note on #364).

- [ ] **Step 1:** Edit docs + fact-check table for the review message.
- [ ] **Step 2:** Run the `cascade-check` skill; resolve every row.
- [ ] **Step 3:** Full gates with forward-slash `--basetemp`; grep log for `ALL GATES GREEN`.
- [ ] **Step 4:** Phase 6 desktop + mobile on `/settings`; teardown `stop_dev_bypass.py`.
- [ ] **Step 5:** Commit with the Gates trailer.
