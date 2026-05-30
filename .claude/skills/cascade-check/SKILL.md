---
name: cascade-check
description: Walks CLAUDE.md's "if you changed X, also update Y" cascade table against the changed files in the working tree / branch. Outputs a per-row checklist with the exact follow-up files to update or an N/A reason. Use after coding and before committing, and again before the SOP Compliance Report.
---

# Cascade Check Skill

## Purpose

CLAUDE.md has a ~18-row **cascade table** ("when you change X, what else
must change?"). Skipped rows are a recurring bug class — e.g. #248
(changed `app.py` module behavior, missed the `test_deployment.py` /
guard update), #138 D-B1 (changed a CSS grid, missed the
`minmax(0,...)` cascade), #57 (extended a feature to a new type, missed
a stale `type === "work"` gate). Walking the table from memory lets rows
slip. This skill walks it **mechanically** against the actual diff.

Filed as #258-D. The forward-checklist counterpart of the `cascade-auditor`
subagent (#258-G, retrospective).

## When to use

- After coding is done, **before `git commit`** — so the follow-ups land
  in the same change.
- Again right before printing the SOP Compliance Report (`/sop-report`),
  to fill the Phase 3 / Cascade-check row honestly.

## Source of truth

**CLAUDE.md's cascade table is authoritative.** The rule list below is a
distilled, detection-augmented mirror of it. If a rule here disagrees
with CLAUDE.md, CLAUDE.md wins — and the skill is stale (see "Keeping
this skill in sync" at the bottom). Before trusting the list, glance at
the CLAUDE.md table (`### Cascade check — when you change X`) and confirm
the row count still matches (~18 rows).

## Step 1 — gather the changed files + signals

```bash
# Changed files on this branch vs main (the usual case). Fall back to
# --cached or plain `git diff --name-only` for staged / unstaged work.
git diff --name-only origin/main...HEAD

# Content-based triggers (new column, new route, new env var, …) match
# ADDED lines. ALWAYS scope to the relevant code path with `-- <path>`,
# never the whole diff. Helper — added lines in a path filter:
#   git diff origin/main...HEAD -- <pathspec> | grep -E '^\+' | grep -v '^\+\+\+'
# e.g. row 11 (new DB column) is scoped to models.py. NOTE: this repo uses
# SQLAlchemy 2.0 — match `mapped_column(` / `Mapped[` AS WELL AS the legacy
# `db.Column(`, or you'll miss every modern model (e.g. CronAudit):
git diff origin/main...HEAD -- 'models.py' | grep -E '^\+' | grep -v '^\+\+\+' | grep -E 'db\.Column\(|mapped_column\(|Mapped\['
```

**Self-match caveat (learned the hard way):** documentation files
contain the literal trigger tokens (`os.environ`, `db.Column`,
`@bp.post`, …) because they *describe* the triggers — this very skill
and `CLAUDE.md`'s cascade table both do. So a whole-diff grep
self-triggers. **Scope every content grep to the code path named in the
row, and exclude docs/skills**: add `':(exclude).claude/**' ':(exclude)docs/**' ':(exclude)*.md'`
to the pathspec, or just point `-- <path>` at the specific code file the
row names (`models.py`, `*_api.py`, `static/*.js`, `app.py`).

Run the targeted detection greps inline as you walk each rule below
(each rule names the signal AND the path to scope to). A row only
triggers if THIS change introduced the signal **in real code**, not in
prose that mentions it.

## Step 2 — walk the rules

For each row: decide TRIGGERED (a changed file / added line matches the
signal) or N/A. For every TRIGGERED row, list the specific follow-up
files and whether each is already handled in the diff.

| # | Trigger — and how to detect it in the diff | Then verify / update |
|---|---|---|
| 1 | **Auth decorator / scope change** — diff touches `auth.py`, `auth_api.py`, `validator_cookie.py`, or adds/edits `@login_required`, validator-cookie path, or dev-bypass gates | Update module docstrings of all three auth files so scope claims still match; add a test asserting the new boundary; consider an ADR-supersede |
| 2 | **Env var read/write** — added line matches `os\.environ(\.get\(|\[)["'][A-Z_]` in any `.py` | README.md env-var table; `.env.example`; `scripts/docs_sync_check.py` passes (or allow-list it if framework-level — e.g. `TMPDIR`) |
| 3 | **New file-upload endpoint** — diff adds a route reading `request.files` / multipart | Use `utils.validate_upload(request, field_name=, allowed_mime=, max_bytes=)` (ADR-025); add oversize + empty + bad-MIME route tests |
| 4 | **New external API caller** — added line adds `requests.post/get(` or a new Whisper/Claude/Vision call | Route through `egress.safe_call_api(url=, headers=, vendor=)` — never raw `requests.*` (ADR-023); key in `Authorization`/vendor header, NEVER URL query (ADR-007); `scrub_sensitive` regex covers the key; add `test_strips_<vendor>_key` in test_logging.py. User-controlled URL → `egress.safe_fetch_user_url` (ADR-006) |
| 5 | **New state-mutating route** — diff adds `@bp.post/patch/delete/put` or a `methods=[...]` containing POST/PATCH/DELETE/PUT | `@login_required` (real OAuth — validator cookie can't auth mutations); **NEVER add GET to a mutating route's methods** (#190/#185 CSRF — `SameSite=Lax` doesn't block top-level GET); rate-limit if user-controlled; validate input |
| 6 | **New state-reading route** — diff adds `@bp.get` / a GET-only route | `@login_required`; validator cookie WILL auth it on GET (intentional) — document if it exposes anything sensitive |
| 7 | **New static asset** — a new file under `static/` (`*.css`/`*.js`/icon) appears in the diff (`git diff --name-only --diff-filter=A`) | `static/sw.js` `APP_SHELL` includes it; `health.py` `EXPECTED_STATIC_FILES` includes it; bump `CACHE_VERSION` |
| 8 | **New HTML template / route renderer** — new `templates/*.html` or a new `render_template(...)` route | Add to nav in `base.html` if user-visible (or a capture-bar button); set `active_page`; **Phase 6 desktop + mobile** (Playwright/bandit don't substitute); update `ARCHITECTURE.md` Components + Data Flows + Route catalog (`arch_sync_check` enforces) |
| 9 | **New background job** — diff adds APScheduler `add_job(` / a new cron closure in `app.py` `_init_scheduler` | `ARCHITECTURE.md` Components (scheduler box + the job by `job_id` + what it does); Data Flows if user-observable; **literal `job_id` must appear in the Route catalog** (arch_sync_check enforces) |
| 10 | **New `/api/…` endpoint** — diff adds `@bp.get/post/...` under an `/api/...` blueprint | `ARCHITECTURE.md` Data Flows (request→response); **literal URL pattern in the Route catalog** (arch_sync_check enforces) |
| 11 | **New DB column / enum member** — added `db.Column(` / `mapped_column(` / `Mapped[` in `models.py`, or a new enum value | `ARCHITECTURE.md` PostgreSQL box + matching Components bullet (ER diagram auto-generates from `db.Model.registry`); if user-visible (new tier/field), also `templates/docs.html` per row 15 |
| 12 | **New `db.Model` subclass (new table)** — added `class X(db.Model)` | Add the table to `_ER_TABLE_GROUPS` (`core`/`ops`/`auth`) + `_ER_TABLE_ORDER`, and a `_SCHEMA_DESCRIPTIONS` entry (`blurb` + `columns:{col:{desc,notes,fk_target?}}`). **Resolve the real definition site with `grep -rn "_SCHEMA_DESCRIPTIONS ="`** — it now lives in `architecture_schemas.py` (re-exported into `architecture_service.py`), not where older docs say. Drift-gate tests `test_every_model_table_has_a_group` + `test_every_column_has_a_description` fail otherwise |
| 13 | **New column on an existing model** — added `db.Column(` / `mapped_column(` / `Mapped[` on a model that already exists | If not in `_HIDDEN_ER_COLUMNS`/`_DESCRIPTION_OPTIONAL_COLUMNS`, add `_SCHEMA_DESCRIPTIONS[table]['columns'][col]` (in `architecture_schemas.py` — `grep` for it) with FK cols including `fk_target`. `test_every_column_has_a_description` fails otherwise |
| 14 | **New gate in `run_all_gates.sh`** — diff touches `scripts/run_all_gates.sh` adding a gate/check | Update the "11 quality gates" OR "Drift-prevention gates" table in `templates/architecture.html` (#54); note the bug it prevents in the Prevents-recurrence-of column; update the Engineering-details run-command if syntax changed |
| 15 | **User-visible behavior** — diff touches `parse_capture.js`, tier rules, a voice-memo prompt, recurring spawn timing, a user-facing error message / button label / time window, or any new affordance | Update `templates/docs.html` (Help, #33/#40); walk the user-facing **fact-check SOP** (every claim cited to `file:line`); add a section if genuinely new; verify desktop + mobile in Phase 6 |
| 16 | **Process flow with a sequence diagram** — diff touches the recurring-spawn, voice-memo, or auth flow (others added later) | Update the Mermaid sequence diagram in `templates/architecture.html` to match the code path (re-walk per fact-check SOP); keep the prose + "Related ADRs" list accurate; new flow worth a diagram → draft one + add a TOC entry |
| 17 | **New function called from `static/app.js` `init()`** (or a transitive helper like `renderBoard`→`updateTodayWarning`) | **Null-guard every `getElementById`/`querySelector`** for a board-only element BEFORE reading any property (`const el = …; if (!el) return;`) — subpages load `app.js` too and an unguarded access stops init + downstream loaders. (Burned twice: updateTodayWarning 2026-04-19 + /completed 2026-04-20) |
| 18 | **Extending a feature from one task type to multiple** — diff broadens a `type === "work"` / `type == "work"` (or personal) gate | grep **all** `type === "work"` AND `type == "work"` (+ personal equivalents) across `static/*.js`, route guards, templates — decide whether each gate is still valid. Write the payload round-trip test FIRST (#57 silent project_id drop) |
| 19 | **Security-sensitive function refactor** — broadened a scope / changed an auth check (overlaps row 1) | New ADR superseding the old one in `docs/adr/`; grep all docstrings/comments for the OLD claim and update; add a regression test asserting the new scope |
| 20 | **Dependency bump** — diff touches `requirements.txt` / `requirements-dev.txt` / `package.json` | `pip-audit` / `npm audit` clean; pytest still passes (some bumps break APIs) |
| 21 | **New SOP rule / process change in CLAUDE.md** — diff touches `CLAUDE.md` | Mention it in the next commit message so future sessions notice; consider whether `run_all_gates.sh` can enforce it. If you changed the **cascade table itself**, also update THIS skill (see below) |

(Rows 19–21 split CLAUDE.md's last three rows for cleaner detection;
the substance matches CLAUDE.md 1:1. CLAUDE.md's own count is ~18.)

## Step 3 — emit the checklist

Output one line per TRIGGERED row plus a single rolled-up N/A line.
Match CLAUDE.md's `[✅]`/`[⏭️]`/`[❌]` markers so it drops straight into
the SOP report's Phase 3 cascade row.

```
Cascade Check — <branch> (<N> files changed)
────────────────────────────────────────────
[✅] Row 7  New static asset (static/favicon.svg)
            → sw.js APP_SHELL: DONE · health.py EXPECTED_STATIC_FILES: DONE · CACHE_VERSION bumped: DONE
[❌] Row 11 New DB column (models.py: Task.snoozed_until)
            → ARCHITECTURE.md PostgreSQL box: NOT YET · _SCHEMA_DESCRIPTIONS: NOT YET
[⏭️] Rows 1-6, 8-10, 12-21  N/A — not triggered by this diff
Verdict: 1 row needs follow-up before commit (Row 11).
```

Rules:
- A TRIGGERED row with an unhandled follow-up is `[❌]` — **the change is
  not done**; do the follow-up, then re-run.
- Only mark `[✅]` when every follow-up file in that row is actually
  updated in the diff (or genuinely doesn't apply, with a one-line why).
- If a row triggers and you're unsure how to handle it: STOP, write a
  one-paragraph note, and put it in the commit message (per CLAUDE.md).

## Keeping this skill in sync (meta-cascade)

This skill mirrors CLAUDE.md's cascade table. **If you edit that table
(add/remove/change a row), update this `SKILL.md` in the same change** —
otherwise the skill silently walks a stale list. CLAUDE.md's cascade
table has a row for exactly this (row 21). There is no automated drift
gate for it; the discipline is the guard.
