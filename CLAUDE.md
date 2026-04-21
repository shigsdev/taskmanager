# CLAUDE.md — Coding Standards and Quality Gates

Claude Code must read and follow this file on every session. Every commit must
pass the quality gates described here. When in doubt, simpler is better — the
previous system failed because of complexity overhead.

---

## Branching Workflow (mandatory for all changes)

Never commit directly to `main`. All work happens on a feature branch,
gets tested there, and only merges to `main` when all quality gates pass.

1. **Create a feature branch** before writing any code:
   ```
   git checkout -b feature/<short-name>
   ```
   Use a descriptive kebab-case name: `feature/jest-testing`,
   `fix/sw-cache-bump`, `feature/calendar-view`, etc.

2. **Do all development on the feature branch.** Commit as often as
   needed — messy WIP commits are fine here.

3. **Run all quality gates** on the feature branch (ruff, pytest, jest,
   regression if UI changed). Everything must be green.

4. **Merge locally into `main`:**
   ```
   git checkout main
   git pull origin main        # catch any remote changes first
   git merge feature/<name>    # fast-forward or merge commit, either OK
   ```

5. **Push `main`:**
   ```
   git push
   ```

6. **Run deploy validation** (`python scripts/validate_deploy.py`).

7. **Clean up** the feature branch after deploy is green:
   ```
   git branch -d feature/<name>
   ```

**Exceptions** — the user may explicitly approve pushing directly to
`main` for trivial changes (typo fixes, doc-only edits). When in doubt,
use a branch.

---

## Quality Gates (mandatory on every commit — NO EXCEPTIONS)

These gates run on EVERY change, no matter how small. Do not skip steps.
Do not run partial test suites. Do not deviate unless the user explicitly
says otherwise.

### CRITICAL: Phase 6 UI regression is NOT optional for UI changes

Any change that touches:
- a template file (`templates/*.html`)
- a static asset (`static/*.css`, `static/*.js`)
- a new route that renders HTML
- any CSS selector, layout change, or new UI element

REQUIRES a live-browser regression via Claude Preview at BOTH desktop
(1280×800) and mobile (375×812). Passing Playwright tests that don't
specifically exercise the changed page/element DO NOT substitute for
Phase 6. Backend tests DO NOT substitute for Phase 6. HTTP 200 on
`curl` DO NOT substitute for Phase 6.

**Anti-pattern that happened on 2026-04-18 (voice memo feature):**
The feature passed 16 backend tests, the full Jest suite, 23 local
Playwright tests, prod validation, and 5 prod Playwright tests. The
BACKLOG got marked ✅. Claude Preview was never opened on the new
page. A subsequent manual Preview pass found TWO real bugs:
  1. `.icon-btn` display mismatch between `<a>` and `<button>` — caused
     the new voice-memo button to render ~3px off compared to other
     icon-btns
  2. Capture bar overflowed on mobile (375px) because the added 4th
     icon-btn pushed it past the bar width — `<input>`'s intrinsic
     min-width from placeholder text prevented it from shrinking
Both bugs were invisible to every automated test in the suite. Both
would have been caught in 5 minutes of Preview at desktop+mobile.

**If the regression is skipped, the change is not complete.** Mark
BACKLOG status `🔄 IN PROGRESS — Phase 6 not yet run` rather than ✅
until a human-viewable regression is documented in the Regression Test
Report.

1. **ruff** — `ruff check .` — zero warnings
2. **pytest** — `pytest --cov` — FULL test suite, 80% coverage floor.
   Never run only the affected test file. Always run all tests.
3. **jest** — `npm test` — FULL JS test suite, all tests must pass.
   Node.js is required on all dev machines. If `node` is not found,
   STOP and install it before proceeding — do NOT skip unless the user
   explicitly approves it.
4. **Test report** — before committing, print a summary to the user:
   - Ruff status (pass/fail, warning count)
   - Python tests run, passed, failed + coverage percentage
   - Jest tests run, passed, failed
   - Any skipped or errored tests
   - Files changed in this commit
   Example:
   ```
   Quality Gate Report
   ─────────────────────
   Ruff:      PASS (0 warnings)
   Python:    247 passed, 0 failed
   Coverage:  93.7% (floor: 80%)
   Jest:      34 passed, 0 failed
   Files:     app.js, capture.js, style.css
   Status:    READY TO COMMIT
   ```
4. Only after the report shows all green: commit and push
- **Post-push deploy validation** (after every `git push`):

  **Skip for doc-only changes.** If the push only touches `.md` files,
  `.gitignore`, or other non-code files that don't affect the running
  app, deploy validation is not required. Mark Phase 8 as
  `[⏭️] N/A — doc-only change` in the SOP Compliance Report.

  Railway does **rolling deploys** — the old container keeps serving
  traffic until the new container is healthy. A plain `curl /healthz`
  will happily return 200 OK from the OLD container while the new build
  is still running. Version-pinned validation is mandatory for code changes.

  **Preferred method — run the validation script:**
  ```
  python scripts/validate_deploy.py
  ```
  It auto-detects the expected SHA from `git rev-parse HEAD`, polls
  `/healthz` every 15s for up to 10 minutes, and prints the Deploy
  Validation Report. Exit code 0 = GREEN, 1 = RED, 2 = cookie expired.

  When `~/.taskmanager-session-cookie` is present (the mint-validator
  token), the script auto-enables TWO additional checks:

  - **Auth preflight**: hits `/api/auth/status` to confirm the validator
    cookie still authenticates. 401 means rotate the cookie before
    continuing any API calls.
  - **Error log scan**: queries `/api/debug/logs?level=ERROR&since_minutes=N`
    where N is the time since the new container's `started_at`. Any
    server-side ERROR row = DEPLOY RED. This is what catches 500s on
    routes that Playwright smoke doesn't exercise — the gap that let
    the 2026-04-19 enum outage slip past validate_deploy into "green".
    Client-side errors (`source=client`) are ignored by default to
    avoid browser-extension noise.

  To force-skip the log scan, pass `--no-check-logs`. To skip everything
  except `/healthz` SHA + checks, delete/rename the cookie file.

  **Manual method** (if the script is unavailable):

  1. Capture the expected commit SHA BEFORE validating:
     `EXPECTED_SHA=$(git rev-parse HEAD)`
  2. Poll `/healthz` every 15s, up to 10 minutes:
     ```
     curl -s https://web-production-3e3ae.up.railway.app/healthz
     ```
  3. The deploy is complete ONLY when ALL of these are true:
     - HTTP status is `200`
     - `status` is `"ok"`
     - `git_sha` equals `$EXPECTED_SHA` (this is the critical check —
       proves you are hitting the NEW container, not the old one)
     - Every check in `checks` is `"ok"`, `"skipped: ..."`, or `"warn: ..."`
     - NO check starts with `"fail:"`
  4. If `git_sha` still shows the previous SHA after 5 minutes, Railway
     is still building or the new container failed its own health check.
     Check the Railway deploy logs before continuing.
  5. If the `git_sha` matches but any check is `"fail:"`, STOP and
     investigate. Common failures and what they mean:
     - `database: fail` — DB connection broken (check DATABASE_URL)
     - `migrations: fail: at X expected Y` — alembic never ran; check
       railway.toml `startCommand` includes `flask db upgrade`
     - `migrations: fail: alembic_version table missing` — fresh DB that
       never had a migration; run `flask db upgrade` manually
     - `tables: fail: missing ...` — schema drift or wrong database
     - `writable_db: fail` — DB is in read-only mode or hot standby
     - `encryption: fail` — ENCRYPTION_KEY rotated or corrupted
     - `digest: fail: daily_digest job missing` — scheduler didn't start
     - `static_assets: fail` — build dropped a required file
  6. Never consider a deploy "green" based on HTTP 200 alone. The
     `git_sha` equality check is non-negotiable.
  7. **Print a Deploy Validation Report** to the user after every
     post-push check. Use this exact format so it's scannable at a
     glance:
     ```
     Deploy Validation Report
     ─────────────────────────
     Expected SHA:   <first 8 chars of git rev-parse HEAD>
     Deployed SHA:   <first 8 chars of healthz git_sha>
     SHA match:      PASS | FAIL
     HTTP status:    200 | 503
     Overall status: ok | fail
     Started at:     <started_at timestamp>
     Auth preflight: PASS | FAIL | (omitted if no cookie)
     Error log scan: PASS | FAIL (N server ERROR rows) | SKIP: <reason>

     Checks:
       database       ok
       env_vars       ok
       migrations     ok
       tables         ok
       writable_db    ok
       encryption     ok
       digest         ok | warn: ... | skipped: ...
       static_assets  ok

     Status: DEPLOY GREEN | DEPLOY RED
     ```
     Each check shows its exact status string. Warnings are allowed.
     Any `fail:` status, SHA mismatch, non-200 HTTP, failed auth
     preflight, OR any server-side ERROR rows in the log scan means
     DEPLOY RED
     and you must stop and investigate.
- **Post-deploy smoke tests** (after health check passes):
  1. Use Claude Preview (headless browser) to verify affected pages render
     without errors — check for console errors, broken layouts, missing elements
  2. For API-only changes, hit the affected endpoints with curl to verify
  3. For any UI/frontend change, also run the **mobile viewport check** below

- **Visual + functional regression** (mandatory for any UI/frontend change):

  Before committing UI changes, run a deep regression at both desktop
  (1280×800) and mobile (375×812). This covers layout AND functionality.

  **Setup:**
  1. Seed the local dev DB with realistic data (idempotent, safe to re-run):
     ```
     /usr/local/bin/python3.14 scripts/seed_dev_data.py
     ```
  2. Start the local bypass server:
     ```
     preview_start taskmanager-dev-bypass
     ```
  3. Always navigate with `?nosw=1` to prevent service worker reload loops
     in the headless browser (e.g. `http://localhost:5111/?nosw=1`)

  **Visual checks** (both viewports — desktop first, then mobile):
  3. Navigate to every page affected by the change
  4. For each page, check:
     - `preview_console_logs` — no errors
     - `preview_snapshot` — elements visible, not overlapping, text not
       truncated, buttons/inputs are tappable size (min 44×44px on mobile)
  5. Take a `preview_screenshot` of each affected page as proof

  **Functional checks** (both viewports):
  6. **Tasks page**: create a task via capture bar, verify it appears in the
     correct tier. Open detail panel, change fields, save, verify changes
     persist on reload. Click Done/Week/Backlog tier buttons, verify task
     moves. Test repeat dropdown (select Weekly, verify day picker appears).
  7. **Goals page**: verify goal cards show progress bars with correct task
     counts. Filter by category/priority/status, verify results change.
  8. **Review page**: click Keep/Freeze/Snooze, verify the card advances
     and the progress counter updates.
  9. **Settings page**: verify stats reflect the seeded data counts.
  10. **Import page**: verify buttons render and are clickable.
  11. **Scan page**: verify radio buttons toggle and upload area is tappable.
  12. **Recycle bin**: verify batch entries show, Empty Bin button is visible.
  13. **Print view**: verify tasks are listed with correct tier grouping.

  **Cleanup:**
  14. Stop the bypass server and delete `.env.dev-bypass` before committing

  **What automated testing CANNOT cover** (tell the user to manually verify):
  - OAuth-protected pages on Railway (bypass is local-only)
  - Native mobile features: touch gestures, PWA standalone mode, Web Speech
  - Real device quirks: iOS Safari address bar, Android keyboard overlap

  **Regression Test Report** (mandatory after every regression run):

  After completing the regression, print a **Regression Test Report** so
  the user can see exactly what was tested and at which viewport. Use this
  exact format:

  ```
  Regression Test Report
  ───────────────────────
  Seed data:          24 active, 5 completed, 3 recycled, 4 goals, 4 projects, 5 recurring
  Console errors:     0

  Desktop (1280×800)                          Mobile (375×812)
  ─────────────────────                       ─────────────────────
  Tasks: capture bar create     PASS          Tasks: capture bar create     PASS
  Tasks: detail panel save      PASS          Tasks: detail panel save      PASS
  Tasks: persist on reload      PASS          Tasks: persist on reload      PASS
  Tasks: tier button move       PASS          Tasks: tier button move       PASS
  Tasks: repeat dropdown        PASS          Tasks: repeat dropdown        PASS
  Goals: progress bars          PASS          Goals: progress bars          PASS
  Goals: filter category        PASS          Goals: filter category        PASS
  Goals: filter priority        PASS          Goals: filter priority        PASS
  Goals: filter status          PASS          Goals: filter status          PASS
  Review: Keep                  PASS          Review: Keep                  PASS
  Review: Freeze                PASS          Review: Freeze                PASS
  Review: Snooze                PASS          Review: Snooze                PASS
  Settings: stats               PASS          Settings: stats               PASS
  Import: button click          PASS          Import: button click          PASS
  Scan: radio toggle            PASS          Scan: radio toggle            PASS
  Scan: upload area             PASS          Scan: upload area             PASS
  Recycle bin: batch entries    PASS          Recycle bin: batch entries    PASS
  Recycle bin: Empty Bin btn    PASS          Recycle bin: Empty Bin btn    PASS
  Print: tier grouping          PASS          Print: tier grouping          PASS

  Status: ALL PASS | <N> FAIL (list failures)
  ```

  Mark each test PASS, FAIL, or SKIP (with reason). Any FAIL means the
  change is not ready to commit — fix and re-test before proceeding.

  **Updating the test checklist when adding features:**

  When a new feature adds a page, UI element, or user interaction, you
  MUST add corresponding functional check lines to the checklist above
  (steps 6–13) AND to the Regression Test Report template. This ensures
  every feature is tested on every future change. Examples:
  - New "Calendar" page → add step 14 and two report rows
  - New "drag to reorder" interaction on Tasks → add a line under step 6
  - New filter on Goals → add a line under step 7

  **Include in the SOP Compliance Report** under Phase 6 (Regression).

- **SOP Compliance Report** (mandatory at the end of every change):

  After every discrete change — not just the final commit of a session —
  print an **SOP Compliance Report** showing exactly which SOP phases ran
  and their status. This is in addition to the Quality Gate Report and
  Deploy Validation Report. A visible checklist makes it impossible to
  quietly skip a step (e.g. forgetting to update ARCHITECTURE.md when the
  topology changed).

  **This rule failed 7× in the 2026-04-20 sprint** (#28–#34 shipped
  without rendered SOP reports; status instead got inlined into commit
  messages — which is NOT equivalent, because the checklist discipline
  is the entire point of the ceremony). If a change is worth a commit,
  it is worth 30 seconds to render the report. No exceptions for
  "small changes" — small changes are exactly the ones where a skipped
  ARCHITECTURE update or a forgotten Phase 6 slips through.

  **Treat a missing SOP report as a `[❌]` — the change is not done.**
  Not a `[⏭️]`. Go back, write it, then consider the change complete.

  **Status indicators:**
  - `[✅]` — done and passed
  - `[⏭️]` — skipped (N/A) with reason
  - `[❌]` — failed or not done (change is NOT complete)

  Use this exact format, adapting the one-line description and phases to
  the actual work done:

  ```
  SOP Compliance Report — <one-line description>
  ──────────────────────────────────────────────────
  Phase 1  Planning
    [✅] Checked backlog                        <backlog item or reason>
    [✅] Scoped work                            <brief scope>
    [✅] Identified affected files              <file list>
  Phase 2  Git Workflow
    [✅] Pulled latest main                     <branch state>
    [✅] Feature branch created                 feature/<name>
    [✅] Small logical commits                  <N> commits: <summaries>
    [✅] Merged to main + pushed                fast-forward | merge commit
    [✅] Feature branch cleaned up              deleted
  Phase 3  Coding Standards
    [✅] Code changes                           <what changed>
    [⏭️] Frontend changes                       N/A — no UI change
    [✅] Security rules followed                <relevant checks>
  Phase 4  Quality Gates
    [✅] Ruff                                   PASS (0 warnings)
    [✅] Pytest                                 <n> passed, <coverage>%
    [✅] Jest                                   <n> passed, 0 failed
  Phase 5  Tests
    [✅] Tests added/updated                    <what was tested>
    [⏭️] Route tests                            N/A — no new routes
  Phase 6  Regression (UI changes only)
    [✅] Bypass server started                  seed + preview_start
    [✅] Desktop (1280x800)                     all pages pass
    [✅] Mobile (375x812)                       all pages pass
    [✅] Console errors                         0
    [✅] Bypass torn down                       .env.dev-bypass deleted
  Phase 7  Documentation
    [✅] ARCHITECTURE.md                        <what updated or N/A reason>
    [✅] README.md                              <what updated or N/A reason>
    [✅] BACKLOG.md                             <what updated or N/A reason>
    [⏭️] CLAUDE.md                              N/A — no SOP change
  Phase 8  Deploy
    [✅] Deploy validation                      GREEN — <SHA>, all checks ok
    [✅] Error log scan                         PASS (0 server ERROR rows since deploy start)
    [✅] Post-deploy smoke test                 <what was verified>
  Summary: <N> done, <N> skipped (N/A), <N> not done
  Commits: <SHA list>
  ```

  **Rules:**
  - `[⏭️]` is acceptable ONLY with a short reason after it.
  - Never mark `[✅]` for a step that wasn't actually done.
  - Any `[❌]` means the change is not complete — fix and re-run.
  - If ARCHITECTURE.md or README.md needed updating and didn't get it,
    mark `[❌]` and the change is blocked.
  - **Phase 6 is mandatory for any UI/frontend change.** For non-UI
    changes, skip the entire phase with `[⏭️] N/A — no UI change`.
  - **Bypass status check:** before printing the report, verify
    `.env.dev-bypass` does not exist by running `ls .env.dev-bypass`
    (should return "no such file"). If the file still exists, mark
    `[❌]` on the bypass row — **do not commit** until it's deleted.

---

## Testing Requirements

- **Flask route tests** — 200 / 400 / 422 cases for every endpoint
- **Database model tests** — CRUD operations, constraint validation, enum
  boundaries, foreign key behavior
- **Auth tests** — Google OAuth flow, unauthorized access rejection,
  single-user lockdown verification (email must match `AUTHORIZED_EMAIL`)
- **Email digest tests** — mock SendGrid, verify digest content and format,
  verify sensitive fields never leak into logs or output
- **Encryption tests** — verify sensitive fields are encrypted at rest and
  never logged in plaintext
- **Import parser tests** — OneNote text parsing, Excel goals parsing,
  duplicate detection, malformed input handling
- **Image scan tests** — mock Google Vision and Claude API, verify images
  never persist to disk or DB, verify task candidate parsing
- **PWA / browser API tests** — any feature using a browser-only API
  (Web Speech, Notifications, etc.) must be manually smoke-tested in the
  installed PWA standalone view, not just the browser tab. Verify error
  states (permission denied, API unavailable) show clear user feedback.

---

## Security Rules

- Never log or print sensitive fields (email addresses, API keys, tokens,
  session cookies, OAuth state)
- Always encrypt sensitive config before storing in DB (Fernet)
- Always validate that the authenticated user matches `AUTHORIZED_EMAIL`
  before serving any data — enforce at the route decorator level
- Never commit `.env` or secrets to git — `.env` is in `.gitignore` from day one
- All user input sanitized before DB insertion
- Images are processed in memory only — never written to disk or DB
- Google Vision and Claude API calls are server-side only — browsers never
  talk to those APIs directly
- Session tokens expire after 24 hours of inactivity
- HTTPS enforced via Flask-Talisman in all environments except local dev

---

## Boundary Safety

- **Python → SQL**: always use SQLAlchemy ORM, never raw string queries
- **Python → HTML**: always use Jinja2 auto-escape (never disable it)
- **Python → Email**: sanitize task content before inserting into digest
- **Python → Shell**: no shell commands built from user input, ever
- **Browser → External APIs**: never — all third-party calls are server-side

---

## Naming Conventions

- **Routes**: kebab-case (`/weekly-review`, `/print-view`)
- **Python functions**: snake_case
- **DB columns**: snake_case
- **JS functions**: camelCase, prefixed by view area
  (`taskCard*`, `goalBadge*`, `inboxTriage*`)
- **Python classes**: PascalCase
- **Constants / env vars**: UPPER_SNAKE_CASE

---

## File Structure Conventions

- One route file per major feature area: `auth`, `tasks`, `goals`, `digest`,
  `import`, `scan`
- **Models** in `models.py` — no business logic, just schema
- **Business logic** in service files: `task_service.py`, `goal_service.py`,
  `digest_service.py`, `scan_service.py`
- **Templates** follow feature naming: `tasks/index.html`, `goals/index.html`
- **Static assets** grouped by purpose: `app.js`, `capture.js`, `style.css`

---

## Documentation Rules

- `BACKLOG.md` is updated every session — move items between sections, never
  delete them
- `ARCHITECTURE.md` is regenerated whenever system topology changes
- `README.md` reflects current setup steps and current feature list
- New environment variables must be documented in README.md the same commit
  they are introduced

### Backlog completion gate (mandatory)

A backlog item is **NOT** marked ✅ complete in `BACKLOG.md` until BOTH:

1. **Pre-deploy gates pass**: ruff, pytest with coverage floor, jest,
   local Playwright. **ALL of them. Always.** There is no "when
   applicable" — the judgment call always errs toward skipping. See
   anti-pattern #2 below. Run via `bash scripts/run_all_gates.sh`.
2. **Post-deploy validation passes**: `python scripts/validate_deploy.py`
   returns DEPLOY GREEN with the new SHA, AND `npm run test:e2e:prod`
   passes against the live URL for any change that could affect
   HTTP-served behavior (any Python, template, or route change).

Until both are green, the backlog row uses status `🔄 IN PROGRESS — <what's
done, what's pending>` not ✅. The reason: a feature that's "code complete"
but not running on Railway hasn't actually shipped, and marking it complete
hides that risk from the next session's planner.

If a feature is purely doc-only (no code change to deploy), only the
pre-deploy gate applies — but this is rare; almost any code change requires
post-deploy verification.

### Anti-pattern #2: skipping gates that "can't fail on this change"

**Incident 2026-04-18 (voice memo iOS Safari content-type fix):** A
small backend regex fix in `voice_api.py` passed ruff + pytest, was
committed + merged + deployed, and reported "done" — but jest, local
Playwright, and prod Playwright were silently skipped. The skipped
gates would not have caught a bug in this specific change, but their
absence violated the gate rule and normalized under-testing.

Why this happens:
- "Small backend fix" triggers a `mental shortcut: "Jest tests JS, this
  is Python, Jest can't catch anything here"`.
- Hotfix urgency (user is blocked) pressures shipping over discipline.
- Rules phrased with judgment language (*"when applicable"*) invite
  this erosion.

Rules going forward:
- Run `bash scripts/run_all_gates.sh` before every commit. Full stop.
- The script runs ruff + pytest + jest + local Playwright in order.
  Zero human-judgment calls about which gates "apply."
- If a gate genuinely cannot run in this environment (e.g. node not
  installed on a mac without node dev setup), the commit message must
  include a `Gates-skipped: jest (no node env)` trailer. Silent skip
  is an SOP violation.

### Pre-commit checklist (mandatory)

Before `git commit` on a feature branch:

```
bash scripts/run_all_gates.sh
```

The script exits 0 only if ALL gates pass. Paste the tail (at minimum
the "ALL GATES GREEN" line and any gate that printed a summary) into
the bottom of your commit message, after a blank line, like:

```
<commit message body>

Gates:
  ruff: PASS
  pytest: 903 passed, 89% coverage
  jest: 34 passed
  playwright-local: 23 passed
```

Any skipped gate in this trailer requires a one-line reason.

### Cascade check — when you change X, what else must change?

A surprising number of bugs come from "I updated the code but forgot
to update the comment / test / docstring / README / ADR." This table
is the explicit checklist. After every change, walk it line by line.
Mark each row in the SOP Compliance Report (Phase 3 or new Phase 3b)
as ✅ done / ⏭️ N/A:

| If you changed... | Then also update / verify |
|---|---|
| An auth decorator (`login_required`, validator-cookie path, dev-bypass gates) | Module docstrings of all auth files (auth.py, auth_api.py, validator_cookie.py) so scope claims still match; add a test asserting the new boundary; consider whether an ADR-supersede is needed |
| Any code reading or writing env vars | README.md env-var table; `.env.example`; `scripts/docs_sync_check.py` passes (it will catch missed README rows) |
| A new file-upload endpoint | `MAX_CONTENT_LENGTH` already covers the global cap, but per-endpoint MIME whitelist (with `;codecs=` parameter normalization), size check BEFORE read, and empty-file guard AFTER read; add oversize + empty + bad-MIME tests |
| A new external API caller (Whisper, Claude, Vision, etc.) | Key goes in `Authorization` or vendor-specific header NEVER in URL query string; `scrub_sensitive` regex covers the key format; add a `test_strips_<vendor>_key` test in test_logging.py; `requests.post(..., timeout=N)` (never bare); error message uses `type(e).__name__` not the URL |
| A new HTTP route that mutates state | `@login_required` (real OAuth — validator cookie won't authenticate POST/PATCH/DELETE/PUT); rate-limited if user-controlled; input validated; CSRF not strictly needed (single-user) but think about it |
| A new HTTP route that reads state | `@login_required`; validator cookie WILL authenticate it on GET — that's intentional but document if the route exposes anything sensitive |
| A new static asset (CSS/JS/icon) | `static/sw.js` `APP_SHELL` includes it; `health.py` `EXPECTED_STATIC_FILES` includes it; bump `CACHE_VERSION` |
| A new HTML template / route renderer | Add to nav in `base.html` if user-visible (or capture-bar button if quick-action); set `active_page`; **Phase 6 manual regression** at desktop + mobile — bandit/Playwright don't substitute; **also update `ARCHITECTURE.md`** — new routes change topology and must appear in the Components + Data Flows sections AND the Route catalog (`scripts/arch_sync_check.py` enforces this via `run_all_gates.sh` — your commit will fail without the catalog update) |
| A new background job (APScheduler cron, at-startup gate, etc.) | Update `ARCHITECTURE.md` Components section — the diagram's scheduler box and the Components list should reference the job by id + what it does; add to the Data Flows section if the job triggers user-observable changes; **literal `job_id` must appear in the Route catalog** (arch_sync_check enforces) |
| A new API endpoint (`@bp.get/post/…`) under `/api/…` | Update `ARCHITECTURE.md` Data Flows section with the request→response flow; **literal URL pattern must appear in the Route catalog** (arch_sync_check enforces) |
| A new database column / enum member | Update `ARCHITECTURE.md` PostgreSQL box in the diagram to list the new column / enum member; update the matching Components bullet |
| A new function called from `static/app.js init()` (or any helper it calls transitively like `renderBoard` → `updateTodayWarning`) | **Null-guard every `document.getElementById` / `querySelector`** that targets a board-specific DOM element. Subpages (`/tier/<name>`, `/completed`, `/goals`, `/projects`, etc.) load `app.js` too, so any unguarded access to an element that only exists on the board will throw and stop init — downstream loaders (loadCompletedTasks, loadCancelledTasks, etc.) won't run. Pattern: `const el = document.getElementById("X"); if (!el) return;` **before** reading any property. Two occurrences so far — updateTodayWarning (2026-04-19 client error + 2026-04-20 /completed Phase 6); don't let it be three. |
| Refactored a security-sensitive function (e.g. broadened a scope, changed an auth check) | Write a new ADR superseding the old one in `docs/adr/`; grep all docstrings/comments for the OLD claim and update them; add a regression test that asserts the new scope |
| Bumped a dependency in requirements.txt or package.json | `pip-audit` / `npm audit` clean; pytest still passes (some bumps break APIs) |
| Added a new SOP rule or process change to CLAUDE.md | Mention it in the next commit message so future sessions notice; consider whether `run_all_gates.sh` can enforce it |

If a row triggers and you're not sure how to handle it: STOP, write
a one-paragraph note, and commit-message it. Don't silently skip.

### Threat model (for audit-eye perspective)

Re-read this at the top of every session that touches auth, uploads,
external APIs, logging, or anything that handles user-controllable input.

This app is a **single-user personal tool** with:

- One authorized email (configured via `AUTHORIZED_EMAIL`)
- OAuth session cookies (Google) as the primary auth mechanism, 24h
  sliding expiry
- A long-lived signed validator cookie (`validator_token`) for
  automation — read-only access via the `login_required` GET branch
- External API keys for Google (Vision, OAuth), OpenAI (Whisper),
  Anthropic (Claude), SendGrid

**Realistic attack scenarios to defend against:**

1. **Cookie theft** via malicious browser extension, stolen laptop, or
   network interception — mitigated by `SESSION_COOKIE_SECURE`,
   `HttpOnly`, `SameSite=Lax`, HTTPS-only deploy
2. **API key leak** via logs, error messages, accidental commits —
   mitigated by `scrub_sensitive` regex chain, `.gitignore` covering
   `.env*` and `.flaskenv`, never including keys in URLs
3. **SSRF** from server-side URL fetching (`url-preview`, `scan` if
   we ever add URL inputs) — mitigated by IP-pin + redirect-disable
   in `tasks_api.url_preview` (see ADR-006)
4. **Memory-exhaustion DoS** via huge uploads — mitigated by Flask
   `MAX_CONTENT_LENGTH=30MB` + per-endpoint size checks
5. **Accidental commits of secrets** (.env, cookie files) — mitigated
   by `.gitignore`, would be further mitigated by a gitleaks pre-commit
   hook (TODO)
6. **Validator cookie leak** via a sloppy commit or paste — mitigated
   by 90-day expiry, GET-only scope (no mutations possible), and the
   `SECRET_KEY` rotation kill-switch

**Out of threat model for this app** (different apps would worry
about these — they're not relevant here):

- Multi-tenant data leakage (only one tenant)
- Account takeover of other users (no other users exist)
- Sophisticated APT / nation-state attacker (not a target)
- DDoS at scale (Railway provides basic protection; not worth
  engineering against)

**Things that are technically risky but acceptable trade-offs:**

- `/healthz` is unauthenticated and returns the deployed git_sha
  (deliberate — Railway needs it for health probes)
- Validator cookie can read all your tasks/goals for 90 days if
  leaked (read-only, no mutation, rotatable via `SECRET_KEY`)
- `LOCAL_DEV_BYPASS_AUTH` exists at all (acceptable because of the
  four-gate defense including the triple Railway tripwire)
