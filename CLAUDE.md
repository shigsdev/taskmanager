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

  Railway does **rolling deploys** — the old container keeps serving
  traffic until the new container is healthy. A plain `curl /healthz`
  will happily return 200 OK from the OLD container while the new build
  is still running. Version-pinned validation is mandatory.

  **Preferred method — run the validation script:**
  ```
  python scripts/validate_deploy.py
  ```
  It auto-detects the expected SHA from `git rev-parse HEAD`, polls
  `/healthz` every 15s for up to 10 minutes, and prints the Deploy
  Validation Report. Exit code 0 = GREEN, 1 = RED.

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
     Any `fail:` status, SHA mismatch, or non-200 HTTP means DEPLOY RED
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

  **Include in the SOP Change Report:**
  ```
  Regression test     DONE (desktop + mobile) | N/A — no UI change
  ```

- **SOP Change Report** (mandatory at the end of every change):

  After every discrete change — not just the final commit of a session —
  print an **SOP Change Report** showing exactly which SOP steps ran and
  their status. This is in addition to the Quality Gate Report and
  Deploy Validation Report. A visible checklist makes it impossible to
  quietly skip a step (e.g. forgetting to update ARCHITECTURE.md when the
  topology changed). Use this exact format:

  ```
  SOP Change Report
  ──────────────────
  Change:             <one-line description>
  Files touched:      <list>

  Code changes        DONE | N/A
  Tests added/updated DONE | N/A
  Ruff                PASS | FAIL
  Pytest              <n passed>, <coverage>%
  ARCHITECTURE.md     UPDATED | N/A — <reason if N/A>
  README.md           UPDATED | N/A — <reason if N/A>
  BACKLOG.md          UPDATED | N/A — <reason if N/A>
  CLAUDE.md           UPDATED | N/A — <reason if N/A>
  Regression test     DONE (desktop + mobile) | N/A — <reason if N/A>
  Bypass status       OFF (never enabled)
                    | OFF (enabled during session, torn down pre-commit)
                    | ⚠ ON — MUST NOT COMMIT
  Commit + push       DONE | SKIPPED
  Deploy validation   GREEN  | RED | N/A (no push)
  Smoke test          DONE | N/A
  ```

  N/A is acceptable ONLY with a short reason ("no topology change",
  "no new env vars", etc.). Never mark a row DONE that wasn't actually
  done. If ARCHITECTURE.md or README.md needed updating and didn't get
  it, the report must say FAIL and the change is not complete.

  **Bypass status is mandatory on every report** — never omit the row.
  To compute it: if `.env.dev-bypass` does not exist → OFF (never
  enabled). If it was created and then deleted earlier in the session →
  OFF (enabled during session, torn down pre-commit). If the file still
  exists at the time the report is printed → ⚠ ON, which means **do
  not commit** — delete `.env.dev-bypass` first, re-verify, then
  re-print the report. Verify by running `ls .env.dev-bypass` (should
  return "no such file") before marking OFF.

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
