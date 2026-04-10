# CLAUDE.md — Coding Standards and Quality Gates

Claude Code must read and follow this file on every session. Every commit must
pass the quality gates described here. When in doubt, simpler is better — the
previous system failed because of complexity overhead.

---

## Quality Gates (mandatory on every commit — NO EXCEPTIONS)

These gates run on EVERY change, no matter how small. Do not skip steps.
Do not run partial test suites. Do not deviate unless the user explicitly
says otherwise.

1. **ruff** — `ruff check .` — zero warnings
2. **pytest** — `pytest --cov` — FULL test suite, 80% coverage floor.
   Never run only the affected test file. Always run all tests.
3. **Test report** — before committing, print a summary to the user:
   - Ruff status (pass/fail, warning count)
   - Total tests run, passed, failed
   - Coverage percentage
   - Any skipped or errored tests
   - Files changed in this commit
   Example:
   ```
   Quality Gate Report
   ─────────────────────
   Ruff:      PASS (0 warnings)
   Tests:     247 passed, 0 failed
   Coverage:  93.7% (floor: 80%)
   Files:     app.js, capture.js, style.css
   Status:    READY TO COMMIT
   ```
4. Only after the report shows all green: commit and push
- **Post-push deploy validation** (after every `git push`):
  1. Wait 2–3 minutes for Railway to build and deploy
  2. Run: `curl -s https://web-production-3e3ae.up.railway.app/healthz`
  3. Verify response includes `"checks"` field with `"database": "ok"`
  4. If response is missing `"checks"` or shows the old format, the build
     is still deploying — wait 1 minute and retry
  5. If any check shows `"fail"` or returns `503`, investigate before
     continuing to the next task
- **Post-deploy smoke tests** (after health check passes):
  1. Use Claude Preview (headless browser) to verify affected pages render
     without errors — check for console errors, broken layouts, missing elements
  2. For any UI/frontend change, tell the user which pages to manually test
     on mobile and what to look for — Claude cannot test OAuth-protected pages
     or mobile-specific features (touch, voice, PWA standalone mode)
  3. For API-only changes, hit the affected endpoints with curl to verify

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
