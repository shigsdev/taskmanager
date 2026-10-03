# Spec #369 — The import-undo confirm names the repeating tasks it pauses

**Filed:** 2026-10-02 (from #356's final review; goal note added by #368)
**Status:** approved 2026-10-03; plan `docs/design/369-implementation-plan.md`
**Builds on:** #353 / ADR-038, #356, #368
**Backend changes:** one read-only query helper, one read-only route.
**Frontend:** the `/settings` Import History Undo confirm.
**Severity:** Low. The cascade is correct and Restore reverses it; only
the warning is missing.

---

## 1. Problem

Since #356 and #368, undoing an import archives its projects and goals
through `_set_project_active` / `_set_goal_active`
(`recycle_service.py:313-322`). That pauses every running repeating task
on them, including routines the user created by hand on an imported
project. The `/projects` and `/goals` Archive confirms name those
templates (#353, #368). The Undo confirm (`static/settings.js:200-204`)
says only:

> Move this import to the recycle bin? Source / Items / You can restore
> it later from the Recycle Bin page.

So a routine can stop without a word.

## 2. Goal

- The Undo confirm names the repeating tasks the undo will pause, in the
  same words as the Archive confirms, with a tail that says how to get
  them back.
- No templates affected → the confirm reads exactly as it does today.
- A failed lookup never blocks the undo (#353's ruling: the server
  cascade is the control, the dialog is information).

## 3. Affected surfaces (the complete list)

Every caller of `POST /api/recycle-bin/undo/<batch_id>`, by grep
2026-10-02: **one**, `static/settings.js:211` (Import History → Undo).
The Recycle Bin page has no undo; it only restores and purges batches
already in the bin.

What the undo pauses (`undo_batch` → the cascade), so what the dialog
must list:

- batch projects that are **active** (`_set_project_active` is
  transition-guarded; an already-archived project is skipped), and
- batch goals that are **active** (same guard),
- → every template with `is_active = true` whose `project_id` is one of
  those projects **or** whose `goal_id` is one of those goals
  (`cascade_parent_archive`, archive branch, first update). Listed once
  even if it matches both.

Templates already paused (by the user, or by another archive) aren't
listed: the undo only adds a marker to them, it doesn't stop anything.

## 4. Design

### 4.1 Server: compute the blast radius where the cascade lives

Approach chosen over exposing the batch's project/goal ids on the
history rows and filtering `/api/recurring` in the browser: the server
already knows which parents the undo will touch, and #364 (reflection
proposals) needs the same "which templates would this archive pause"
answer server-side. One query, two consumers, no client-side copy of the
cascade's filter to drift.

- `recurring_service.templates_paused_by_archive(project_ids, goal_ids)
  -> list[RecurringTask]`: active templates whose `project_id` is in
  `project_ids` or whose `goal_id` is in `goal_ids`, ordered by title.
  Empty inputs → `[]` without a query. Its docstring names
  `cascade_parent_archive` as the rule it mirrors.
- `recycle_service.undo_impact(batch_id) -> dict`: `_get_log` (404 on an
  unknown batch), `BatchStateError` if already undone (409, same as
  `undo_batch`), then the active batch projects and goals →
  `{"batch_id": ..., "paused_templates": [{"id", "title"}, ...]}`.
  Read-only: no writes, no commit.
- `GET /api/recycle-bin/impact/<batch_id>` in `recycle_api.py`,
  `@login_required`, 400 / 404 / 409 like its siblings. A separate path,
  not a GET on `/undo/<id>` — that URL mutates, and #190 keeps GET off
  mutating routes.

### 4.2 Client: reuse the /projects message builder

`projectArchiveHelpers.archiveConfirmMessage(paused, tail)` gains an
optional `tail`; omitted, it behaves exactly as today, so `/projects` is
untouched. `/settings` loads `project_archive_helpers.js` (already in
`APP_SHELL` and `EXPECTED_STATIC_FILES`; only a `<script>` tag is new).

`onUndoClick` (`static/settings.js:196`):

1. Disable the button ("Checking…") so a double click can't open two
   dialogs.
2. `GET /api/recycle-bin/impact/<batch_id>`.
3. Build today's message; if the helper returns text, append it after a
   blank line with the tail **"They resume if you restore this import
   from the Recycle Bin."**
4. Any lookup failure (network, 4xx, helper missing) → today's message
   unchanged.
5. Cancel → re-enable the button as "Undo". OK → the existing POST.

### 4.3 Docs

`templates/docs.html` "Recycle bin and undo": add that the Undo confirm
names the repeating tasks it will pause. Same paragraph also fixes one
wrong claim it already makes, "Undo on an import (from Settings → Import
History **or via the Recycle Bin**)": the bin has no Undo. Pulled in
because it's the sentence being edited; fact-checked like the rest.

## 5. Testing plan (written RED first)

pytest (`tests/test_undo_impact.py`):

- template on a batch project → listed; on a batch goal → listed; on
  both → listed once
- user-paused template on a batch project → not listed
- template on a project/goal **outside** the batch → not listed
- batch project already archived before the undo → its templates not
  listed (the undo skips it)
- **parity:** for one mixed fixture, the ids `undo_impact` lists equal
  the ids `undo_batch` actually flips from active to paused
- read-only: calling it changes no row
- route: 200 shape, 400 bad id, 404 unknown batch, 409 already undone,
  unauthenticated rejected
- `templates_paused_by_archive([], [])` → `[]`

Jest (`project_archive_helpers.test.js`): custom tail used; default tail
unchanged; empty list → `""` regardless of tail.

Playwright (`tests/e2e/`): Settings → Undo on a batch whose project has
an active template → dialog names it; on a batch without → dialog has no
"pause" line. (Fixture approach decided at build time from how existing
import-history tests seed batches.)

## 6. Cascade touch-points

- New `/api/...` endpoint → `ARCHITECTURE.md` Data Flows + Route catalog
  (`arch_sync_check`).
- `templates/settings.html` script tag; `static/settings.js` +
  `project_archive_helpers.js` changed → `CACHE_VERSION` bump (the push
  reloads open tabs).
- User-visible copy → `templates/docs.html`, with a fact-check table.
- CLAUDE.md Phase 6 step 9 (Settings) + Regression Report: add
  "Settings: undo names paused tmpl" and "Settings: no-tmpl undo quiet",
  and mirror in `.claude/skills/` only if the cascade table changes (it
  doesn't).

## 7. Out of scope (filed, not absorbed)

- **#373 (new):** the Recycle Bin's Restore / Purge / Empty dialogs count
  tasks and goals but never projects (`list_bin` already returns
  `project_count`), and Purge doesn't say that repeating tasks it paused
  stay paused for good (`docs.html` does; the dialog doesn't).
- **#364** keeps its own ship, but should call
  `templates_paused_by_archive` once this lands. Note added to the row.

## 8. Decisions

1. Server computes the list (one query shared with #364), not the
   browser.
2. Reuse `archiveConfirmMessage` with an optional tail rather than a
   third copy of the wording.
3. Lookup failure → today's dialog; never block the undo.
4. Distinct `GET /impact/<id>` path, never a GET on the mutating URL.
