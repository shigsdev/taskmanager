# Spec #393 — the /architecture schema intro is derived from the models

**Filed:** 2026-10-06 (found in #391 Phase 6)
**Status:** built 2026-10-08 — design approved in chat; user added the stale
Playwright gate row to the scope, and chose a compact summary in Phase 6
**UI change** (`templates/architecture.html`) → Phase 6.

---

## 1. The problem

The hand-written intro to "What the database stores" said **"Seven tables. Three
groups"**, showed an **"Auth (sign-in tokens)"** swatch, and summarised 6 tables.
The models define **14** tables in **two** groups (9 core, 5 ops); no auth table
has existed since #188 removed the fictional `flask_dance_oauth`. The per-table
cards and the ER diagram below it were already generated and correct.

The same page's quality-gates row for local Playwright was also stale: it named
`npm run test:e2e` (desktop only) and "23 browser E2E tests"; the gate runs
`npm run test:e2e:local` — ~500 tests over desktop, SW-active and mobile, on two
local servers since #394.

## 2. Behaviour after the change

- **Intro:** "{N} tables, in {G} groups, color-coded:" computed from
  `per_table_schema`; the legend lists only groups that have tables (the Auth
  swatch reappears automatically if an auth-group table is ever added).
- **Summary:** generated from the same data — a compact map, **Table | Links
  to**, one row per table in the curated order, group colour on each row.
  "Links to" = distinct tables named by the columns' `fk_target`, in column
  order (new `links_to` field on `build_per_table_schema()`). The plain-English
  descriptions stay in the cards just below (user choice in Phase 6: the first
  version repeated the full blurbs, ~3 screens tall and duplicating the cards).
- **Gate row 4:** `npm run test:e2e:local`; ~500 tests in three projects
  (desktop at Playwright’s default 1280×720, service-worker-active, mobile 375×812); two throwaway
  local servers (desktop + SW on `127.0.0.1:5111`, mobile on `:5112` with a DB
  copy, #385 / #394); `PLAYWRIGHT_WORKERS=1` for one; not runnable on the old
  Mac (#41, still open).

## 3. Tests (`tests/test_architecture.py`, red first)

- `TestSchemaIntroMatchesModels`: the rendered page states the real table count
  and not "Seven tables"; a legend swatch exists exactly for the groups that
  have tables; the summary lists exactly the model tables, in order; the gate
  row names `npm run test:e2e:local` and not "23 browser E2E tests". All 4 red
  before.
- `TestBuildPerTableSchema::test_links_to_lists_each_linked_table_once_in_column_order`
  — `tasks` → projects, goals, import_log, tasks, recurring_tasks;
  `workout_sets` → workout_sessions; `app_logs` → none.

## 4. Phase 6

`/architecture` at 1280×800 and 375×812: intro reads "14 tables, in 2 groups"
with Core + Operational swatches only; summary 2 columns × 14 rows; link names
wrap only between names; table and page do not overflow; 0 console errors.
