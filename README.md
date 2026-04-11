# Personal Task Manager

A personal productivity system — task management, goal tracking, and daily
execution. Built with Python + Flask, hosted on Railway, accessible from any
device via browser. Designed for a single user managing 50-100 tasks across
work and personal life, with a regulated (air-gapped) work environment.

## Features

- **Task board** — tier-based organization (Today, This Week, Backlog, Freezer, Inbox)
  with drag-and-drop, quick capture bar, detail panel, and voice input
- **Goals** — grouped by category (Health, Work, Personal Growth, Relationships)
  with priority ranking, progress tracking, and linked tasks
- **Projects** — work task grouping with color coding and goal linkage
- **Inbox triage** — single and bulk triage flow for new tasks
- **Checklists** — subtask checklists on tasks with progress tracking
- **Weekly review** — step-through stale task review (keep/freeze/delete/snooze)
- **Recurring tasks** — 16 system defaults plus custom templates, daily/weekly/day-of-week
- **Print view** — printer-friendly Today + This Week + Overdue layout
- **Email digest** — daily summary via SendGrid with goals, overdue alerts
- **Image scan** — Google Vision OCR + Claude AI parsing of photos into tasks
- **Import** — paste OneNote text or upload Excel goals with duplicate detection
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
| `GOOGLE_VISION_API_KEY` | Google Cloud Vision API key for OCR |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude task parsing |
| `APP_LOG_LEVEL` | Minimum level persisted to `app_logs` table (default `WARNING`). Set `INFO` to capture per-request summary rows. |
| `APP_LOG_DISABLE` | If set to any truthy value, disables the DB log handler entirely. Useful only for debugging the logger itself. |

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
pytest --cov
ruff check .
```

### Standards

See `CLAUDE.md` for coding standards, quality gates, security rules, and
naming conventions. Every commit must pass `pytest --cov` (80% floor) and
`ruff check .` with zero warnings.
