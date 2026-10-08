# Spec #366 — `/api/export` exports all of your data

**Filed:** 2026-10-01 (from #353's final review)
**Status:** direction chosen 2026-10-08 — "make it complete" (not retire, no
UI button)
**Backend only** — no template/static change → no Phase 6, no `CACHE_VERSION`
bump. Python change → full gates + deploy + prod smoke.

---

## 1. The problem (measured in code, 2026-10-08)

`GET /api/export` (`app.py` `export_data`) returns `tasks`, `goals` and
`projects` only, and is wrong in four ways:

| Gap | Cause | Effect on the file |
|---|---|---|
| 9 tables absent | hand-picked keys | no `recurring_tasks`, `weekly_focus`, `reflections`, `global_context_files`, `app_settings`, `workout_sessions`, `workout_sets`, `flare_states`, `import_log` — every task's `recurring_task_id` points at nothing |
| Archived goals + projects absent | `list_goals()` / `list_projects()` default `is_active=True` | tasks/templates reference goal/project ids not in the file |
| Projects lose 8 of 14 columns | inline `serialize_project` | no `goal_id`, `status`, `notes`, `actions`, `target_quarter`, `priority`, `priority_order`, `batch_id` |
| Goals lose 2 of 13 columns | inline `serialize_goal` | no `is_active` (archived vs live), `batch_id` |

`tasks` is already correct (#200: `serialize_task(view="export")` derives from
`Task.__table__.columns`; `list_tasks(status=None)` returns every status).

Context: nothing in the UI calls the endpoint and nothing restores from it; the
real backup is the daily encrypted `pg_dump` (#154), which has every table.
This file is a human-readable copy of the user's data.

## 2. Behaviour after the fix

- New `export_service.py` with `build_export() -> dict`. For every mapped
  model in `db.Model.registry` whose table is **not** in
  `EXPORT_EXCLUDED_TABLES`, it emits `<table name>: [row, ...]`, where each row
  is `{column name: _column_value(value)}` over **all** of
  `Model.__table__.columns`, for **all** rows (no `is_active` / status
  filter). Rows are ordered by primary key so two exports of the same data are
  identical.
- `EXPORT_EXCLUDED_TABLES = {"app_logs", "cron_audit"}` — server logs and
  scheduler bookkeeping, not user data. Each entry carries a one-line reason.
  Everything else is exported, including `import_log` (the Import History the
  user sees on /settings) and `app_settings` (the user's settings; the keys
  there are not secrets — revoked token ids, last digest send, milestone,
  weekly-focus slot count).
- `_column_value` stays in `task_service.py` and is imported from there, so
  #200's callers don't churn.
- Top-level keys stay backward compatible: `exported_at` (unchanged, DIGEST_TZ
  date, #180), `tasks`, `goals`, `projects` (same names; goals/projects gain
  columns and archived rows). New: one key per added table.
- Download filename unchanged: `taskmanager-backup-<date>.json`.
- `app.py` `export_data` shrinks to: `build_export()`, `_jsonify`, set the
  `Content-Disposition` header. Auth unchanged (`@login_required`; the
  read-only validator cookie can GET it, as today).
- **No new exposure.** The export now includes reflections, context-file
  text, workouts and settings, but the validator cookie could already GET
  all of those through existing routes (`/api/reflection`,
  `/api/reflection/<id>`, `/api/reflection/global-context`, …). No column
  is field-encrypted. (CLAUDE.md's threat model says a leaked validator
  cookie reads "all your tasks/goals" — already an understatement before
  #366; not changed here.)

## 3. Tests (`tests/test_export.py`, new)

1. **Every user-data table is exported** — the key set equals
   `{t.name for every mapped table} - EXPORT_EXCLUDED_TABLES | {"exported_at"}`.
   This is the drift gate: a new model fails it until it is exported or
   explicitly excluded with a reason.
2. **Every column is exported** — for each exported table with a seeded row,
   the row's keys equal the table's column names.
3. **Archived goals and projects are exported** with `is_active: false`, and a
   project's `goal_id` survives.
4. **References resolve** — a task spawned from a template has a
   `recurring_task_id` present in `recurring_tasks`; a task on an archived
   project has a `project_id` present in `projects`.
5. **Excluded tables are absent** — no `app_logs` / `cron_audit` key, even with
   rows in those tables.
6. **The response is JSON with the attachment header** (existing
   `test_print_view.py` tests cover `exported_at` + filename; keep them green).

Red before: 1, 2, 3, 4 (5 passes trivially today — kept as a guard).

## 4. Cascade

- `ARCHITECTURE.md`: `/api/export` line → "download every user-data table as
  JSON (excludes app_logs, cron_audit)"; Components: add `export_service.py`.
- No env vars, no routes added, no models, no user-facing copy (API-only).

## 5. Out of scope

- A /settings "Download my data" button (user chose API-only).
- An import/restore path for this file.
