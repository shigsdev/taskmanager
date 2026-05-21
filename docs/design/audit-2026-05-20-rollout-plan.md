# Audit 2026-05-20 — Rollout Plan

**Source:** 34 OPEN backlog rows filed 2026-05-20 by a three-agent audit pass
(commit `51dd22e` on `main`).

**Scope:** 12 bugs (#170–#181) + 9 security (#182–#190) + 13 tech debt
(#191–#203).

**Plan:** 14 PRs across 3 phases, each on its own feature branch through the
full CLAUDE.md workflow (pre-deploy gates → merge → deploy validation +
5-min monitor → prod Playwright smoke). Phase 1 ships before Phase 2,
Phase 2 ships before Phase 3 — but PRs within a phase can flow in any
order if convenient.

---

## Decisions baked in (do NOT re-litigate without explicit reopen)

These were resolved 2026-05-20 before plan was written. If you want to
change one, mark the affected PR as **BLOCKED — decision reopened** and
flag it back here.

| # | Decision | Implication |
|---|---|---|
| 172 | **A** — Claude returns explicit `category` in `_VOICE_PARSE_PROMPT` (one of 5 goal-category enums) | PR 5: prompt rev + UI mapping + voice_api mapping change. Fixes root cause. |
| 176 | **B** — Detail panel Save calls `/complete` (or `/cancel`) instead of plain PATCH when status changes | PR 7: `update_task` stays dumb; client-side routing change. No service-layer cascade added. |
| 185 | **Restrict /logout to POST** (NOT acceptance) | PR 9: route change + navbar form-button. Tightens CSRF surface. Falls in security sweep, not doc-only batch. |
| 189 | **Sanitize `e.orig` exposure** (NOT acceptance) | PR 9: replace `_shape_message` Postgres branch with `"Database error (request_id: X)"`; debug detail still recoverable via `/api/debug/logs` lookup. |
| Plan | **14 PRs** as broken out below (mid-size cohesive batches) | ~7–10 hrs total workflow overhead at ~30–45 min/PR. |
| Order | **Phase 1 → Phase 2 → Phase 3** | Correctness first, security second, drift-prevention + refactors last. |

---

## Workflow overhead — what every PR costs

Per CLAUDE.md, every PR runs the same workflow. Budget this BEFORE
starting:

- **Feature branch** (`feature/<short-name>`) — never commit to `main`.
- **Pre-deploy gates** via `bash scripts/run_all_gates.sh` — ruff,
  pytest with 80% coverage floor, jest, Playwright local desktop +
  mobile (375×812), bandit, pip-audit, npm audit, docs sync,
  arch sync, semgrep, gitleaks, "no string-match-only tests"
  (PR47/49 gate). ~5–15 min.
- **Quality Gate Report** printed to user before commit.
- **Merge to main** via `git merge --ff-only` (or merge commit OK).
- **Deploy validation** via `python scripts/validate_deploy.py
  --monitor-minutes 5` — auto-emits SOP Compliance Report at end.
  ~10–15 min.
- **Prod Playwright smoke** via `npm run test:e2e:prod` (22 tests).
  ~2–3 min.
- **SOP Compliance Report** filled out for Phases 1–7 (auto-template
  prints; operator fills the `[__]` placeholders).
- **BACKLOG row** flipped from OPEN → ✅ RESOLVED on the affected rows
  with commit SHA + ship date.

A PR is NOT done until ALL of these are green. If you split a PR or
re-order, update this doc.

---

## Phase 1 — Correctness bugs (ship first)

User-impact items: silent data loss, cron-batch crashes, off-by-one TZ
drift. Highest priority.

### [ ] PR 1 — TZ-drift sweep #2

- **Items:** #178, #180
- **Theme:** Continuation of PR63's #128 fix. Replace 7 lingering UTC
  `date.today()` calls with `local_today_date()` from `utils.py`.
- **Sites (per #180):** `app.py:509` (/print overdue filter),
  `app.py:516` (print sheet date header), `app.py:571,578`
  (/api/export filename + `exported_at`), `debug_api.py:468` (comment +
  call), `scan_service.py:628-629` (voice prompt date injection).
- **Site (per #178):** `triage_service.py:82-83` (use `astimezone(ZoneInfo(DIGEST_TZ))` on
  `task.updated_at` before `.date()`).
- **Tests:** pytest cases mocking the clock to 9pm–11pm ET assert
  `/print` overdue filter returns same set as 9am ET; scan_service
  prompt-date injection returns ET date not UTC; triage
  `days_since_update == 0` for a task updated 1h ago at 11pm ET.
- **Cascade:** none — pure logic fix.
- **Risk:** Low. Pattern is already established in #128.
- **Effort:** S.

### [ ] PR 2 — DIGEST_TIME boot validation

- **Item:** #179
- **Theme:** Container crash-on-boot if `DIGEST_TIME` env var malformed.
- **Fix:** Wrap the `hour, minute = (int(x) for x in digest_time.split(":"))`
  parse in try/except in `app.py:686-687`. On ValueError, log
  WARNING and default to `(7, 0)`. Add `digest_scheduled_at` field to
  `/healthz` so operator can see the resolved time post-fix.
- **Tests:** boot with `DIGEST_TIME="07:00:00"`, `"7am"`, `""`,
  `"99:99"` — each should NOT raise; assert log line + default
  applied; assert `/healthz` reports `07:00`.
- **Cascade:** README env-var docs note the format is `HH:MM` (24h)
  and falls back to 07:00 on malformed.
- **Risk:** Low. Boot-time defensive code; no behavior change in the
  happy path.
- **Effort:** XS.

### [ ] PR 3 — Realign cron preserves overdue-TODAY

- **Item:** #170
- **Theme:** The 00:03 DIGEST_TZ `realign_tiers_with_due_dates` cron
  silently demotes "due yesterday but kept visible" TODAY tasks to
  BACKLOG. Inverse of #108.
- **Fix:** Extend the skip-list in `task_service.realign_tiers_with_due_dates`
  to skip when `t.tier == Tier.TODAY and t.due_date < today` (currently
  skips only `{FREEZER, INBOX}`). Keep stale-today visible as a nag.
- **Tests:** pytest seeds 3 TODAY tasks (due_date = today-7, today,
  today+1) → realign moves only future-this-week one, leaves overdue-today
  alone, keeps on-day today as-is.
- **Cascade:** ARCHITECTURE.md scheduler section already documents the
  cron; add a sentence on the overdue-TODAY exception.
- **Risk:** Low. Single-function tightening of an existing rule.
- **Effort:** S.

### [ ] PR 4 — Recurring template integrity

- **Items:** #171, #173, #177
- **Theme:** Three independent recurring-template defects, all in the
  same module. Ship as one PR because the test surface overlaps.
- **#171 (drop `days_of_week` + `week_of_month`):** Add the two keys to
  `_apply_repeat` (task_service.py:182-205), `_update_repeat`
  (task_service.py:225-249), `create_recurring_template_from_voice_candidate`
  (recurring_service.py:717-724).
- **#173 (frequency-change validation):** In `recurring_service.update_recurring`,
  when `frequency` changes, re-run the dependent-field validation block
  from `create_recurring` (lines 194-221) and raise `ValidationError`.
  Also: wrap each template in try/except inside `spawn_today_tasks`
  (recurring_service.py:556-577) so one bad row can't crash the morning
  batch.
- **#177 (start>end silent save):** In both `create_recurring` and
  `update_recurring` post-parse, raise
  `ValidationError("start_date must be on or before end_date", "end_date")`
  when both non-null and start > end.
- **Tests:** Jest assert task_detail_payload sends `days_of_week` +
  `week_of_month` for MULTI_DAY_OF_WEEK + MONTHLY_NTH_WEEKDAY. pytest:
  voice-confirm with multi_day_of_week → real template; PATCH frequency
  daily → monthly_date without day_of_month → 422; start>end → 422;
  per-template try/except: seed 3 templates, force middle one to raise
  → other two still spawn.
- **Cascade:** docs.html if user-visible (helpful error wording).
- **Risk:** Medium. Touches multiple cron-spawn code paths. Cron test
  coverage is the safety net.
- **Effort:** M.

### [ ] PR 5 — Voice-memo goal category mapping (decision A)

- **Item:** #172
- **Theme:** Every voice-dictated goal lands as `category=work`.
- **Fix (option A confirmed):** Extend `_VOICE_PARSE_PROMPT` in
  `scan_service.py` to return an explicit `category` field with the 5
  goal-category enum values (`health` / `personal_growth` /
  `relationships` / `work` / `bau`). Forward through the
  `voice_memo.js:739` review UI's per-candidate display so the user
  can override. Map directly in `voice_api.py:221-229` (replace
  `c.get("type")` with `c.get("category")` and the allowlist with the
  5-value goal enum).
- **Tests:** prompt-template self-consistency test (`category` key
  present in JSON shape, example demonstrates each of 5 values).
  pytest case: voice candidate with `category=health` lands as goal
  with the right enum. Jest assert review UI renders the 5-value
  category picker.
- **Cascade:** docs.html voice-memo section gets a sentence about the
  category mapping. CACHE_VERSION bump.
- **Risk:** Low. Prompt changes have a self-consistency test in the
  pattern of #137 sub-PR C.
- **Effort:** S.

### [ ] PR 6 — Reflection-apply correctness

- **Items:** #174, #181
- **Theme:** Both touch `reflection_service.apply_selected_actions`.
- **#174 (half-flushed sessions + opaque 500):** Wrap the creates loop
  (steps 1+2+4 at line 591+) in per-row try/except, mirroring the
  update/delete pattern at line 702, 730. Route catch-all in
  `reflection_api.py:205-209` returns `(summary, 207)` (multi-status)
  instead of opaque 500 — partial successes surface in `summary["errors"]`.
- **#181 (hallucinated hint clears FK):** In `_apply_task_link_hints`
  (reflection_service.py:746-758), when `_resolve_ref` returns None for
  a hint, `pop` the key from the payload entirely instead of setting it
  to None. Append `summary["errors"].append("project_hint <X> not found,
  kept existing project")` so the user sees what happened.
- **Tests:** pytest seeds reflection with 3 create actions, monkeypatch
  middle one to raise → other two committed, summary["errors"]
  contains middle's reason. pytest: reflection UPDATE with stale
  `project_hint` does NOT clear task.project_id; summary surfaces the
  hint-miss.
- **Cascade:** none beyond tests.
- **Risk:** Medium. Reflection is the AI-driven mutation path; needs
  careful test coverage.
- **Effort:** M.

### [ ] PR 7 — PATCH status cascades to subtasks (decision B)

- **Item:** #176
- **Theme:** Detail-panel Save with `status: archived/cancelled` leaves
  open subtasks ACTIVE.
- **Fix (option B confirmed):** Client-side change. When the detail
  panel's Save handler detects `status` changed to ARCHIVED or
  CANCELLED, route the request to `POST /api/tasks/<id>/complete` or
  `POST /api/tasks/<id>/cancel` instead of `PATCH /api/tasks/<id>`.
  Those endpoints already do the cascade properly (`complete_parent_task`
  in task_service.py:558-575).
- **Tests:** Jest assert: task_detail Save with `status=archived` calls
  `/complete` not `/api/tasks/<id>`. Playwright local: complete a
  parent via detail-panel Save → subtask cards now show as archived.
- **Cascade:** none; reuses existing endpoints.
- **Risk:** Low. Client-only logic change.
- **Effort:** S.

### [ ] PR 8 — Recycle purge FK cleanup (migration)

- **Item:** #175
- **Theme:** `recycle_service.purge_batch` nulls Task.project_id +
  Task.goal_id but leaves 4 other FKs to soft-deleted rows → opaque
  422 "violates foreign key constraint" on cross-entity purges.
- **Fix:** Alembic migration adds `ondelete="SET NULL"` to: Project.goal_id
  (models.py:196-198), RecurringTask.goal_id +
  RecurringTask.project_id (models.py:322-327), Task.parent_id
  (models.py:270-272). Mirrors WeeklyFocus.goal_id at line 446-448.
- **Tests:** pytest cross-entity purge — bulk-import goal + project +
  task linked through it → undo + purge in the wrong order → no 422.
- **Cascade:** ARCHITECTURE.md schema-descriptions for affected tables
  note the cascade behavior; `_SCHEMA_DESCRIPTIONS` entries updated.
  Drift-gate test `test_every_column_has_a_description` should still
  pass (FK column descriptions unchanged, just the SQL behavior).
- **Risk:** Low. Migration is mechanical; no data shape change.
- **Effort:** S.

---

## Phase 2 — Security + doc

### [ ] PR 9 — Security hardening sweep

- **Items:** #182, #183, #184, #185, #186, #187, #189
- **Theme:** Seven small input/limit guards in one focused PR. Decisions
  rolled in: #185 to POST (not acceptance), #189 sanitize (not
  acceptance).
- **#182:** `@limiter.limit("5 per minute")` on `digest_api.send` (paid
  SendGrid).
- **#183:** `@limiter.limit("5 per minute")` on
  `import_api.transcript/parse` + `transcript/upload` (paid Claude).
- **#184:** `@limiter.limit("30 per minute")` on `tasks_api.url_preview`
  (outbound fetch).
- **#185:** `/logout` route restricted to `methods=["POST"]`. Navbar
  Logout link → small `<form method="POST" action="/logout">` button
  styled to match. CSRF token: single-user, none needed; but document
  the consideration in the PR description.
- **#186:** Apply `_CTRL_CHARS_RE.sub(" ", raw)` to the accepted
  `X-Request-ID` header before assigning to `g.request_id` (mirror
  PR62's #24 fix on `client-error`). Or stricter:
  `re.match(r"^[A-Za-z0-9._\-]+$")`.
- **#187:** Add `if len(task_ids) > 200: return 422` to
  `tasks_api.reorder`, `recurring_api.bulk_patch`,
  `recurring_api.bulk_delete`. Mirror the cap on `tasks_api.bulk_update`.
- **#189:** `errors._shape_message` Postgres branch returns
  `"Database error (request_id: " + g.request_id + ")"` instead of
  the first line of `e.orig`. Operator looks up details via
  `/api/debug/logs?since_minutes=N&search=<request_id>`. Update
  CLAUDE.md threat-model with the new contract.
- **Tests:** each rate-limit triggers 429 on N+1. /logout GET → 405
  Method Not Allowed. X-Request-ID with `\n` → stripped to space. Bulk
  endpoints with 201 ids → 422. e.orig payload check: confirm
  request_id appears in the JSON response and the full detail appears
  in `/api/debug/logs` for that request_id.
- **Cascade:** CLAUDE.md threat-model section updated (auto-rotate
  `_shape_message` contract). Templates/base.html for the navbar form
  change. CACHE_VERSION bump (template change).
- **Risk:** Medium. /logout UI change needs Phase 6 desktop + mobile.
  e.orig sanitization could mask debugging — test the request_id
  lookup path thoroughly so we don't regress #52's "blank Save failed:"
  experience.
- **Effort:** M.

### [ ] PR 10 — Doc-only batch

- **Items:** #188, #190
- **Theme:** Documentation truth-up. No code changes.
- **#188:** CLAUDE.md threat-model section gets:
  - Strike "Fernet encryption on OAuth tokens" claim — Flask-Dance
    stores OAuth identity in the signed session cookie, not a DB
    table. Document the actual mechanism + the rationale (single user,
    HTTPS-only).
  - Strike "24h sliding TTL" claim — sessions are `timedelta(days=30)`
    per `app.py:188` (changed 2026-05-05). Document the 30-day window
    + the stolen-laptop risk it implies.
- **Remove from `architecture_service._SCHEMA_DESCRIPTIONS`:** the
  fictional `flask_dance_oauth` table entry at lines 591-605. Confirm
  arch_sync_check fails on the entry now and pass with it removed.
- **#190:** Add a row to CLAUDE.md cascade-check table:
  "If you added a new HTTP route that mutates state, confirm it's NOT
  also reachable via GET (would expose to CSRF via img-src). Mark POST/PATCH/DELETE only."
- **Tests:** arch_sync_check passes. No code logic changes, so test
  surface is minimal.
- **Cascade:** none — this PR IS the cascade catch-up.
- **Risk:** None. Doc-only.
- **Effort:** S.

---

## Phase 3 — Drift prevention + refactors

Lower urgency; can pause between PRs if Phase 1+2 work surfaces other
priorities. None depend on each other except where noted.

### [ ] PR 11 — Drift-prevention sweep

- **Items:** #191, #192, #193
- **Theme:** Three drift-prevention items that share the SW + apiFetch
  surface.
- **#191:** Remove the local `apiFetch` / `_hardRecover` /
  `_maybePromptRecovery` from `static/app.js` (they shadow the shared
  globals from `static/api_client.js`). Add a Jest assert that
  `app.js` does NOT define a local `apiFetch` (string search) so a
  future revert can't re-introduce drift.
- **#192:** `static/review.js` + `static/projects.js` still use raw
  `fetch()` — migrate to `window.apiFetch`. (Closes the #132 gap that
  PR67 missed.)
- **#193:** `static/sw.js APP_SHELL` + `health.EXPECTED_STATIC_FILES`
  missing 6 referenced JS files — enumerate from
  `templates/base.html` + per-page templates' `<script src=>` and add
  them. Add a mechanical check (new gate or extend
  `docs_sync_check.py`) that fails if any `<script src>` references a
  file not in APP_SHELL.
- **Tests:** Jest assert no local apiFetch in app.js. Playwright local
  test on /review + /projects asserts the shared apiFetch
  TypeError-retry path fires (not the old raw-fetch path). New gate
  fires on a deliberate omission.
- **Cascade:** CACHE_VERSION bump. ARCHITECTURE.md "Drift-prevention
  gates" table on `/architecture` page (per #54) gets a new row.
- **Risk:** Medium. Removing app.js's local apiFetch could surface
  load-order bugs if any page uses apiFetch before api_client.js
  loads. Phase 6 desktop + mobile MANDATORY.
- **Effort:** M.

### [ ] PR 12 — Helper consolidation

- **Items:** #194, #195, #197
- **Theme:** Three "extract a helper" items.
- **#194:** `import_api.py` reimplements upload validation 5×.
  Migrate each to `utils.validate_upload(request, field_name=...,
  allowed_mime=..., max_bytes=...)`. (ADR-025 pattern.)
- **#195:** Extract `claude_client.py` with one canonical
  `call_claude(messages, model=CLAUDE_MODEL)` + JSON-extractor helper.
  Central model constant `claude-sonnet-4-6` instead of 7 inline
  strings. Migrate scan_service, reflection_service, import_service,
  voice_service, inbox_categorize_service, planner_service,
  weekly_focus_service.
- **#197:** Extract anti-pattern #3 helpers:
  - `static/scan_helpers.js` ← `compressImage` from `scan.js`
  - `static/voice_memo_helpers.js` ← `mimeTypeToExt` from `voice_memo.js`
  - `static/import_helpers.js` ← `_selectFrom` from `import.js`
  - Each with dual-export pattern + Jest tests (~5-8 cases each).
- **Tests:** existing upload tests still pass + size/mime guards still
  trigger. Claude-client unit tests on success, 4xx/5xx, JSON-extract
  edge cases. Jest unit on each new helper.
- **Cascade:** `sw.js APP_SHELL` + `EXPECTED_STATIC_FILES` updated for
  3 new JS files. CACHE_VERSION bump. ARCHITECTURE.md egress section
  notes the new central client.
- **Risk:** Medium. claude_client extraction touches 7 services —
  comprehensive existing-test pass is the safety net.
- **Effort:** M-L.

### [ ] PR 13 — Larger refactors

- **Items:** #196, #198, #199, #200
- **Theme:** Four bigger refactors that don't fit elsewhere.
- **#196:** Extract `@validate_json_body(required=[...], optional=[...])`
  decorator. Migrate 26 sites currently doing
  `if not request.is_json: ...; data = request.get_json(); ...; if not
  data.get("title"): return 400`. Inconsistent error shapes today;
  decorator standardizes to `{"error": "missing required field",
  "field": "title"}`.
- **#198:** Move `_SCHEMA_DESCRIPTIONS` data dict from
  `architecture_service.py` to its own `architecture_schemas.py`. The
  function-side stays where it is; this is a pure data-vs-logic split.
  ~200 lines / 28% of the file.
- **#199:** Table-drive APScheduler registration in `app.py:_init_scheduler`.
  5 nearly-identical blocks → one config table + a registration loop.
  ~120 lines → ~30 lines.
- **#200:** Canonical `Task.to_dict(view="full" | "review" | "export")`
  on the model OR free function in `task_service.py`. Migrate
  `tasks_api._serialize`, `review_api._serialize`,
  `app.py:539 serialize_task`. Add round-trip test that exports every
  Task column for `view="export"` so a future new column triggers a
  test failure (no silent /api/export data loss).
- **Tests:** existing API tests still pass with new error shape (need
  to update fixture expectations). Schema-descriptions tests still
  pass (no content change). Scheduler tests still register all 5 jobs
  + heartbeat. Three-view round-trip on Task ensures parity.
- **Cascade:** CLAUDE.md "Drift-prevention gates" section may grow.
- **Risk:** Medium. Test fixture updates can mask real regressions —
  read each existing test before flipping its expected error shape.
- **Effort:** L.

### [ ] PR 14 — Small cleanups

- **Items:** #201, #202, #203
- **Theme:** XS-each polish.
- **#201:** Delete `# noqa: F401` import of `ProjectStatus, ProjectType`
  from `projects_api.py:9` — nothing else imports them from there.
- **#202:** Expand Jest `collectCoverageFrom` to `["static/*_helpers.js",
  "static/api_client.js", "static/api_helpers.js",
  "static/parse_capture.js", "static/task_detail_payload.js"]`. Optional:
  add `coverageThreshold` to mirror the Python 80% floor.
- **#203:** Add named constants in `rate_limit.py` —
  `PAID_API = "20 per minute"`, `LLM_HEAVY = "5 per minute"`. Migrate
  6 sites (voice_api, scan_api, reflection_api, inbox_categorize_api,
  planner_api, weekly_focus_api) to `@limiter.limit(rate_limit.PAID_API)`.
- **Tests:** existing rate-limit tests still pass. Jest coverage report
  shows 11 new files.
- **Cascade:** none.
- **Risk:** None. Pure polish.
- **Effort:** S.

---

## Tracking checklist

Mark each PR as it ships. A PR is ✅ only after BOTH pre-deploy gates
pass AND post-deploy validation + prod smoke pass.

### Phase 1 — Correctness
- [ ] PR 1 — TZ-drift sweep #2 (#178, #180)
- [ ] PR 2 — DIGEST_TIME boot validation (#179)
- [ ] PR 3 — Realign cron preserves overdue-TODAY (#170)
- [ ] PR 4 — Recurring template integrity (#171, #173, #177)
- [ ] PR 5 — Voice-memo goal category mapping (#172)
- [ ] PR 6 — Reflection-apply correctness (#174, #181)
- [ ] PR 7 — PATCH status cascades to subtasks (#176)
- [ ] PR 8 — Recycle purge FK cleanup (#175)

### Phase 2 — Security + doc
- [ ] PR 9 — Security hardening sweep (#182, #183, #184, #185, #186, #187, #189)
- [ ] PR 10 — Doc-only batch (#188, #190)

### Phase 3 — Drift prevention + refactors
- [ ] PR 11 — Drift-prevention sweep (#191, #192, #193)
- [ ] PR 12 — Helper consolidation (#194, #195, #197)
- [ ] PR 13 — Larger refactors (#196, #198, #199, #200)
- [ ] PR 14 — Small cleanups (#201, #202, #203)

---

## Open questions to resolve mid-rollout (not blockers)

These don't gate the start of PR 1, but flag them now so they don't get
re-rediscovered later:

1. **Plan #204** (Railway resilience design doc) — separate track from
   this audit rollout. Don't conflate the cron-replay cluster
   (#166–#169) or the resilience design (#204) with the audit fixes.
2. **PR 13 #200 fixture churn** — the new error shape from #196 may
   require ~30 test fixture updates. If that's painful, split #196 out
   of PR 13 into its own PR.
3. **PR 11 #193 mechanical check placement** — extend
   `scripts/docs_sync_check.py`? new gate? new `arch_sync_check.py` rule?
   Pick one before coding.
4. **#197 helpers extraction scope** — the row mentions 3 helpers but
   audit notes there may be more sub-helpers worth extracting (e.g.
   `voice_memo.js parseRepeatPhrase`). Treat the row as a sweep, not a
   3-file checklist; if you find more during the PR, file as a
   follow-up row rather than expanding scope mid-PR.
