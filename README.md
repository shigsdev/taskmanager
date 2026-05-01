# Personal Task Manager

A personal productivity system — task management, goal tracking, and daily
execution. Built with Python + Flask, hosted on Railway, accessible from any
device via browser. Designed for a single user managing 50-100 tasks across
work and personal life, with a regulated (air-gapped) work environment.

## Features

- **Task board** — tier-based organization (Today, Tomorrow, This Week, Next Week,
  Backlog, Freezer, Inbox) with drag-and-drop between tiers, tier-header date
  labels, long-title ellipsis, quick capture bar, detail panel, and voice input
- **Day-strip + Calendar** — Mon-Sat day strip above Today + dedicated `/calendar`
  page; drop a task on a day cell to set its `due_date` (tier auto-routes to
  match). Auto-scrolls the page when dragging near the viewport edge.
- **Due-date → tier auto-route** — setting a `due_date` automatically moves the
  task to the matching tier (today → Today, this week → This Week, etc.)
- **Goals** — grouped by category (Health, Work, Personal Growth, Relationships,
  BAU) with priority ranking, progress tracking, and linked tasks
- **Projects** — task grouping with auto-color by type (Work blue / Personal green),
  goal linkage that cascades onto linked tasks, `priority` + `priority_order` with
  drag-to-reorder within type group, `target_quarter`, lifecycle `status` mirroring
  Goals, plus Actions and Notes fields
- **Inbox triage** — single and bulk triage flow for new tasks
- **Subtasks** — one-level-deep child tasks with progress badge on parent,
  goal/project inheritance, cascade on parent update, force-complete option,
  parent picker in the detail panel, and a `+ Subtask` quick button on every
  parent-eligible card
- **URL save** — paste a URL in quick capture, server fetches page title
  (SSRF-protected), saves as task with clickable link
- **Checklists** — checklist items on tasks with progress tracking
- **Weekly review** — step-through stale task review (keep/freeze/delete/snooze) plus
  a **triage suggestions** panel above the review card listing stale tasks with
  one-click recommended actions (heuristic-based: e.g. inbox >7 days → Backlog,
  backlog >90 days → delete)
- **Recurring tasks** — 16 system defaults plus custom templates; daily, weekly,
  single-day-of-week, or **multi-day-of-week** (e.g. Mon+Wed+Fri); dedicated
  `/recurring` page with multi-select bulk-edit (type / frequency / project /
  goal / pause-resume / delete)
- **Print view** — printer-friendly Today + This Week + Overdue layout
- **Email digest** — daily summary via SendGrid with goals, overdue alerts
- **Image scan** — Google Vision OCR + Claude AI parsing of photos; routes
  candidates to **Tasks, Goals, or Projects** via a target picker
- **Voice memo** — record long-form audio, transcribed via Whisper, parsed into
  candidates by Claude; keyword router classifies each candidate as
  **task / goal / project** (clickable badge to override before commit)
- **Import** — three modes: OneNote tasks (paste-text or .docx), Excel goals
  (.xlsx), Excel/paste-text projects, plus **Excel tasks (.xlsx)** with full
  column set (title, type, tier, due_date, linked_goal, linked_project, notes,
  url) — `linked_goal` / `linked_project` resolved case-insensitive at create time.
  Always-visible expanded preview rows let you edit every field before commit;
  duplicate detection + recycle-bin batch undo.
- **Bulk-edit toolbar** — multi-select on the task board stages multiple
  attribute changes (Type, Tier, Due, Goal, Project) and applies them in a
  single PATCH on Apply — selection persists across stages
- **Settings** — dashboard with service status, app stats, import history
- **Mobile responsive** — 44px touch targets, swipe gestures, iOS zoom prevention
- **Security** — Google OAuth single-user lockdown, Fernet encryption, CSP headers,
  rate limiting, HTTPS via Talisman

## Setup

### Railway Deployment

1. Create a Railway account and a new project
2. Add the PostgreSQL plugin to the project
3. Connect the GitHub repo (`shigsdev/taskmanager`) to Railway
4. Set all environment variables in the Railway dashboard (see below)
5. Deploy — Railway auto-detects Python/Flask via Nixpacks
6. Note the generated Railway URL (e.g. `taskmanager.up.railway.app`)
7. Add the Railway URL to Google Cloud Console as an authorized redirect URI

### Custom Domain (optional)

1. In Railway project settings, add your custom domain
2. Railway provides a CNAME target (e.g. `your-project.railway.app`)
3. In your DNS provider, create a CNAME record pointing to the Railway target
4. Wait for DNS propagation and SSL certificate provisioning
5. Update the Google OAuth redirect URI to use your custom domain

### Google OAuth Setup

1. Go to https://console.cloud.google.com
2. Create a new project: "Task Manager"
3. Enable the Google+ API and Google OAuth2 API
4. Create OAuth 2.0 credentials (Web application)
5. Add authorized redirect URI:
   `https://[your-domain]/login/google/authorized`
6. Copy the Client ID and Client Secret to Railway environment variables

### Environment Variables

All secrets live in the Railway dashboard — never committed to git.

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session secret (random 32+ char string) |
| `ENCRYPTION_KEY` | Fernet symmetric encryption key for sensitive fields |
| `GOOGLE_CLIENT_ID` | From Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | From Google Cloud Console |
| `AUTHORIZED_EMAIL` | The only Google account allowed to log in |
| `DATABASE_URL` | Railway PostgreSQL connection string (auto-injected) |
| `SENDGRID_API_KEY` | SendGrid API key for digest delivery |
| `DIGEST_TO_EMAIL` | Recipient email for the daily digest |
| `DIGEST_FROM_EMAIL` | Sender email (default: noreply@taskmanager.app) |
| `DIGEST_TIME` | Time of day digest is sent (default `07:00`) |
| `DIGEST_TZ` | IANA timezone for the digest scheduler (default `America/New_York`) |
| `APP_URL` | Public base URL of the deployed app, embedded as a clickable link in the digest email body. Optional — link is omitted if unset. |
| `GOOGLE_VISION_API_KEY` | Google Cloud Vision API key for OCR |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude task parsing |
| `OPENAI_API_KEY` | OpenAI API key for Whisper voice-memo transcription. **Optional** — voice memo feature returns a clear error if unset, rest of app works fine. |
| `APP_LOG_LEVEL` | Minimum level persisted to `app_logs` table (default `WARNING`). Set `INFO` to capture per-request summary rows. |
| `APP_LOG_DISABLE` | If set to any truthy value, disables the DB log handler entirely. Useful only for debugging the logger itself. |
| `APP_DEBUG_TOKEN` | Optional shared secret — **READ-ONLY scope**. If set, `/api/debug/logs`, `/api/debug/summary`, and `/api/debug/client-error` accept the `X-Debug-Token: <value>` header in lieu of OAuth — useful for agent / CI tooling that needs log access without a session cookie. Does NOT authenticate mutating endpoints (see `APP_DEBUG_ADMIN_TOKEN`). Keep secret. Unset = OAuth-only access (default). |
| `APP_DEBUG_ADMIN_TOKEN` | Optional shared secret — **ADMIN scope**. Required to authenticate mutating one-shot endpoints `/api/debug/backfill/*` and `/api/debug/realign-tiers` via the header path. The READ token does NOT pass this gate, so a leaked read token cannot rewrite tier/goal/project assignments. Admin token ALSO satisfies the read-scope decorator (admin ⊇ read). Use rarely — typically once per migration; rotate after each use. Unset = OAuth-only access (default). |
| `TLS_EXPIRY_HOST` | Optional `<hostname>[:<port>]` for the `tls_expiry` health check (#5). When set, `/healthz` opens a TLS socket to the host, reads the peer cert's `notAfter`, and reports `ok` (>30 days), `warn: <N> days remaining` (≤30 days), or `warn: cert expired` — never `fail:`, so an expiring cert can't brick a deploy. Cached 5 min per process. Unset = check is `skipped:` (default — Railway-managed TLS auto-renews). |

### Debug / logging endpoints

Both require the authorized user. Data is persisted to the `app_logs` table with scrubbing of emails, API keys, bearer tokens, and session cookies. Retention is capped at 10,000 rows OR 14 days (whichever hits first), enforced on every insert. A circuit breaker disables DB logging after 10 consecutive insert failures to prevent loops when the DB is down.

- `GET  /api/debug/logs` — query recent log rows. Params: `since` (shorthand like `10m`/`2h`/`1d` or ISO-8601, default 1h), `level` (DEBUG|INFO|WARNING|ERROR|CRITICAL), `route` (prefix match), `source` (`server` or `client`), `limit` (default 100, capped at 500).
- `POST /api/debug/client-error` — receives uncaught browser errors and unhandled promise rejections from a global hook in `templates/base.html`. Rate-limited to 1 report per 2 seconds per page.

## Usage

### Daily workflow

1. **Morning**: check Today tier, spawn recurring tasks, review digest
2. **Capture**: use quick capture bar, voice input, or image scan
3. **Triage**: process Inbox items to appropriate tiers
4. **Execute**: work through Today tasks, check off subtasks
5. **Evening**: review progress, move incomplete to This Week

### Weekly review

Navigate to /review to step through stale tasks (not reviewed in 7+ days).
For each task: keep, freeze, delete, or snooze.

### Import

Navigate to /import to:
- Paste OneNote text (bullet lists, numbered items, checkboxes)
- Upload Excel .xlsx file with goals (title, category, priority columns)

### Print

Navigate to /print for a printer-friendly view of Today + This Week + Overdue.

### Voice memo to tasks

Navigate to /voice-memo (or tap the 🎙️ button on the capture bar) to record a
long-form voice memo. The audio is transcribed via OpenAI Whisper, parsed into
task candidates by Claude, and surfaced on a review screen. Selected
candidates land in your Inbox.

Recording is hard-capped at 10 minutes per memo (matches Whisper's 25 MB
upload limit at typical opus bitrates). Audio is processed in memory only —
never written to disk or DB. Per-memo cost is logged to AppLog at INFO
level so you can audit transcription spend via `/api/debug/logs`.

**Cost** at OpenAI Whisper API pricing ($0.006/min as of 2026-04):
- 5-min memo: ~$0.03
- 10-min memo (max): ~$0.06
- Daily commute use (~15 min/day): ~$2.70/month

Requires `OPENAI_API_KEY` env var. If unset, the page loads but the upload
returns a clear error — the rest of the app is unaffected.

**Browser support**: Chrome (Android, desktop), Firefox, Safari (browser tab).
Some iOS Safari PWA standalone versions have a known MediaRecorder bug — if
recording fails in standalone, open in a browser tab instead.

## Architecture

See `ARCHITECTURE.md` for the living architecture diagram, component
descriptions, data flows, and security boundaries.

Brief summary: Flask app + PostgreSQL + gunicorn on Railway, Google OAuth
for auth, Fernet for at-rest encryption, SendGrid for the daily email digest
that bridges to the user's air-gapped work Outlook. Content Security Policy
and rate limiting via Flask-Talisman and Flask-Limiter.

## Development

### Run locally

```bash
python -m venv .venv
source .venv/Scripts/activate  # or .venv/bin/activate on mac/linux
pip install -r requirements.txt
cp .env.example .env           # fill in dev values
flask db upgrade
flask run
```

### Local browser testing with bypass mode

Some UI work needs an actual browser preview to verify (does the radio toggle look right? does the click handler fire?). Real Google OAuth doesn't work in headless preview, so the project ships with an opt-in **dev bypass** that lets the local Flask server skip auth entirely. It is **localhost-only** and triple-gated so it cannot activate on Railway.

**To start a bypass session:**

1. Copy the template: `cp .env.dev-bypass.example .env.dev-bypass`
2. Start the bypass server: `python scripts/run_dev_bypass.py` (or, if you use the Claude Preview tool, ask Claude to start the `taskmanager-dev-bypass` server)
3. Watch for the loud banner in stderr:
   ```
   ================================================================
     ⚠  LOCAL_DEV_BYPASS_AUTH IS ACTIVE  ⚠
     All auth checks are disabled. You are logged in as:
       you@example.com
     This must NEVER be set on Railway. Tripwires verified:
       RAILWAY_PROJECT_ID         not set ✓
       RAILWAY_ENVIRONMENT_NAME   not set ✓
       RAILWAY_SERVICE_ID         not set ✓
     Bypass will remain active until this server stops.
   ================================================================
   ```
4. Every protected route accessed during the session writes a `WARNING` row to the `app_logs` table. Query `/api/debug/logs?level=WARNING` to see the audit trail.

**To end a bypass session (REQUIRED before any commit):**

1. Stop the Flask server (Ctrl+C or `preview_stop`)
2. **Delete `.env.dev-bypass`** — the file's existence is the on/off switch
3. Verify with `ls .env.dev-bypass` (should say "no such file")

**The four gates** (all must pass for the bypass to fire — see `auth._dev_bypass_active`):
1. `LOCAL_DEV_BYPASS_AUTH=1` is set
2. `FLASK_ENV=development` is set
3. NONE of `RAILWAY_PROJECT_ID`, `RAILWAY_ENVIRONMENT_NAME`, `RAILWAY_SERVICE_ID` are set
4. `AUTHORIZED_EMAIL` is set

The triple Railway tripwire means a single Railway env var rename cannot disarm the gate — they would have to rename all three at once. The `scripts/run_dev_bypass.py` launcher applies the same Railway check **before** Flask even imports, so even if you manage to ssh into a Railway shell and run the script, it exits with status 2.

### Run tests

```bash
# Python (Flask routes, models, services)
pytest --cov
ruff check .

# JavaScript (parseCapture unit tests — requires Node.js)
npm install   # first time only
npm test

# Playwright E2E tests (real browser — requires bypass server on port 5111)
npx playwright install chromium   # first time only
npm run test:e2e                  # runs against localhost:5111
npm run test:e2e:headed           # same, but visible browser window
```

### Post-deploy validation

After every `git push`, run `python scripts/validate_deploy.py` to confirm the
deploy actually reached Railway (SHA match) and that every check on `/healthz`
is green. This catches the failure mode where Railway's rolling deploy keeps
the **old** container serving traffic because the new build failed its health
check — a plain `curl /healthz` returns 200 from the old container and looks
fine.

**Basic usage** (unchanged from before):
```bash
python scripts/validate_deploy.py
```

**Extended: `--auth-check`** also verifies that a saved credential is
still accepted by the live server. This catches the "I could log in yesterday
but something broke OAuth" class of bug.

**Preferred setup — mint a long-lived validator cookie** (once per ~90
days). The validator cookie is signed with the same `SECRET_KEY` as
Flask sessions but lives in a dedicated cookie (`validator_token`) that
authenticates `/api/auth/status` AND **GET requests** to any
protected route (so post-deploy Playwright tests can verify page
renders). It does NOT authenticate POST/PATCH/DELETE — a leaked
validator cookie can read but never modify your data.

Two ways to mint, depending on what's installed locally:

```bash
# (A) Standalone script — no Flask app boot, only needs `itsdangerous`
#     (which ships with Flask). Works even if your local Python is
#     missing psycopg or other deploy-only deps.
#     Use this with `railway run` to inject the prod SECRET_KEY.
railway run python scripts/mint_validator_cookie.py | Set-Content -NoNewline -Path "$HOME\.taskmanager-session-cookie"

# (B) Flask CLI command — same effect, but needs the full app to import
#     successfully (so `pip install -r requirements.txt` must be done
#     first, including the postgres driver).
railway run python -m flask mint-validator-cookie | Set-Content -NoNewline -Path "$HOME\.taskmanager-session-cookie"

# Both default to 90 days. Override with --days if needed:
railway run python scripts/mint_validator_cookie.py --days 30 | Set-Content -NoNewline -Path "$HOME\.taskmanager-session-cookie"

# Then any time after:
python scripts/validate_deploy.py --auth-check
```

**On Mac/Linux** the equivalent shell redirect is `> ~/.taskmanager-session-cookie`
(but watch for trailing newlines added by some shells — use
`printf '%s' "$(railway run python scripts/mint_validator_cookie.py)" > ~/.taskmanager-session-cookie`
if `>` adds a newline).

Rotate by re-running the same command. Rotating `SECRET_KEY` on the
server instantly invalidates all minted validator cookies — that's the
emergency revocation lever.

**Legacy fallback — copy the session cookie from Chrome.** Not
recommended because Flask-Dance's auto-refresh silently invalidates the
captured cookie during normal browser use. Kept for the case where you
don't have `flask mint-validator-cookie` available (e.g. different
environment). Steps: open `https://web-production-3e3ae.up.railway.app/`
in Chrome, sign in, DevTools → Application → Cookies → copy the
`session` value, save to `~/.taskmanager-session-cookie`.

Exit codes:
- `0` — DEPLOY GREEN (and auth OK if checked)
- `1` — DEPLOY RED (SHA mismatch, failed checks, or timeout)
- `2` — COOKIE EXPIRED (refresh it — the script prints copy-pasteable instructions)
- `3` — Usage error (missing cookie file or bad args)

Cookies expire after 24 hours of inactivity. On a `2` exit code, the script
walks you through re-capturing the cookie from your browser.

### Prod smoke tests (optional)

After the validator is green, you can optionally run a small suite of Playwright
tests against the **live deployed URL** (not localhost) to verify real browser
behavior end-to-end:

```bash
# Pull the cookie you just saved into an env var
export TASKMANAGER_SESSION_COOKIE="$(cat ~/.taskmanager-session-cookie)"
npm run test:e2e:prod
```

Covers: auth preflight, home/goals page renders, `/api/tasks` shape check,
`/healthz` reports real SHA. Tests live in `tests/e2e-prod/`.

### Standards

See `CLAUDE.md` for coding standards, quality gates, security rules, and
naming conventions.

**Every commit must pass:**
```bash
bash scripts/run_all_gates.sh
```

That single command runs **all** pre-deploy gates in sequence — ruff +
pytest (with 80% coverage floor) + jest + local Playwright + bandit +
semgrep + gitleaks + pip-audit + npm audit + docs-sync check. It auto-
manages the bypass server and exits non-zero on any failure. Skipping
individual gates is an SOP violation; if a gate genuinely cannot run
in this environment, document why in a `Gates-skipped: <gate> (<reason>)`
trailer in the commit message.

**First-time setup (once per clone):**
```bash
bash scripts/install_dev_tools.sh    # downloads gitleaks binary into tools/
bash scripts/install_git_hooks.sh    # wires .githooks/pre-commit via core.hooksPath
```

The native pre-commit hook runs gitleaks against staged content before
every commit (~200ms) and blocks any potential secret before it hits
git history. Belt-and-braces on top of gate 10 in `run_all_gates.sh`.
See ADR-022 for the rationale. Emergency bypass: `git commit --no-verify`.
