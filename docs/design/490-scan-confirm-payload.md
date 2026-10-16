# #490 — /scan's confirm payload is built in a tested helper

Split from #459 on 2026-10-15 (the deep review's "client-payload round-trip
test for every review→confirm flow").

## What was wrong

Voice (#425), import, ✨ Plan, 💡 Auto-categorize and reflection build their
confirm payload in a helper Jest checks. `static/scan.js`
`confirmCandidates` mapped each candidate by `currentKind` inline, and
nothing checked it against what the server reads — a renamed field would
silently drop data (the voice A1 bug's shape). Checked 2026-10-16: today's
mapping is correct (the upload returns only `title` / `type` for tasks, so
nothing is lost), so this is a missing guard, not live data loss.

## This ship

- `scanHelpers.scanConfirmPayload(kind, candidates, allIncluded)` in
  `static/scan_helpers.js` (#488's module), same mapping:
  - tasks → `title`, `type` (`scan_service.create_tasks_from_candidates`)
  - goals → `title`, `category`, `priority`, `target_quarter`, `actions`
    (`scan_service.create_goals_from_candidates`)
  - projects → `name` (the review's `title`), `type`, `target_quarter`
    (`import_service.create_projects_from_import`)
  - `included`: Add All sends every row; Add Selected leaves out a row only
    when it was unticked.
- `scan.js` calls it. CACHE_VERSION v344.

## Tests

- `tests/js/unit/scan_confirm_payload.test.js` — each kind's exact keys and
  defaults, Add All vs Add Selected (red before: no helper).
- `tests/e2e/scan_confirm_roundtrip.spec.js` — the upload stubbed, Add All
  REAL; the created goal / project / task is read back from the API with
  every field. Mutation-checked: sending projects as `title` instead of
  `name` fails it.
