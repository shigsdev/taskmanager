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
- **Inbox triage** — single and bulk triage flow for new tasks; plus
  one-click **AI auto-categorize** that sends every active Inbox task
  to Claude Haiku in a single batch and surfaces suggested
  tier / project / goal / due-date / type per task in a review modal
  (override per row, then Apply)
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
- **Plan my week (AI)** — dedicated `/plan` page; pick a Monday → one-click
  Claude Haiku pass reviews ALL active non-frozen tasks + 4 weeks of completion
  history + recurring fires + goals → returns a Mon–Sun plan with per-task
  action (keep / move / delete / freeze), day-by-day grouping, goal progress
  hints, optional velocity warning, and a separate stale-freezer review (items
  frozen > 60 days). Review + override per row, then "Apply all" routes through
  canonical PATCH /api/tasks. Per-task `planner_ignore` flag auto-resets on any
  task touch — silence is per-suggestion, not permanent.
- **Recurring tasks** — 16 system defaults plus custom templates; daily, weekly,
  single-day-of-week, or **multi-day-of-week** (e.g. Mon+Wed+Fri); dedicated
  `/recurring` page with multi-select bulk-edit (type / frequency / project /
  goal / pause-resume / delete)
- **Print view** — printer-friendly Today + This Week + Overdue layout
- **Email digest** — daily summary via authenticated SMTP (Gmail) with goals, overdue alerts
- **Image scan** — Google Vision OCR + Claude AI parsing of photos; routes
  candidates to **Tasks, Goals, or Projects** via a target picker
- **Voice memo** — record long-form audio, transcribed via Whisper, parsed into
  candidates by Claude; keyword router classifies each candidate as
  **task / goal / project** (clickable badge to override before commit)
- **Import** — multiple modes: OneNote tasks (paste-text or .docx), Excel goals
  (.xlsx), Excel/paste-text projects, **Excel tasks (.xlsx)** with full column
  set (title, type, tier, due_date, linked_goal, linked_project, notes, url) —
  `linked_goal` / `linked_project` resolved case-insensitive at create time —
  and **meeting transcript ingestion** (paste or `.md`/`.txt` upload) that
  runs the transcript through Claude to extract action items as task
  candidates. Designed for HyNote, Notion AI Meeting Notes, or any plain-text
  meeting export. Always-visible expanded preview rows let you edit every
  field before commit; duplicate detection + recycle-bin batch undo.
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
| `SMTP_HOST` | SMTP server for the digest (default `smtp.gmail.com`) |
| `SMTP_PORT` | SMTP submission port (default `587`, STARTTLS) |
| `SMTP_USERNAME` | SMTP login — for Gmail, your Gmail address |
| `SMTP_PASSWORD` | SMTP password — for Gmail, a 16-char App Password (requires 2-Step Verification) |
| `DIGEST_TO_EMAIL` | Recipient email for the daily digest |
| `DIGEST_FROM_EMAIL` | Sender email (defaults to `SMTP_USERNAME`; Gmail requires the authenticated account or a verified alias) |
| `DIGEST_TIME` | Time of day digest is sent in 24-hour `HH:MM` format (default `07:00`). Malformed values (e.g. `7am`, `07:00:00`, empty) fall back to `07:00` with a WARNING log + `digest_scheduled_at.fell_back: true` on `/healthz` (#179). |
| `DIGEST_TZ` | IANA timezone for the digest scheduler (default `America/New_York`) |
| `APP_URL` | Public base URL of the deployed app, embedded as a clickable link in the digest email body. Optional — link is omitted if unset. |
| `SENDGRID_API_KEY` | **Optional, GitHub-Actions secret** — used only by the recurring audit/backup workflow scripts (`backup_to_github.py`, `check_*.py`, `restore_drill.py`) to email failure/finding alerts. NOT used by the app's daily digest (which sends via SMTP — see ADR-035). Unset = those workflows still run, just no alert email. Migration to SMTP tracked in backlog #298. |
| `GOOGLE_VISION_API_KEY` | Google Cloud Vision API key for OCR |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude task parsing |
| `OPENAI_API_KEY` | OpenAI API key for Whisper voice-memo transcription. **Optional** — voice memo feature returns a clear error if unset, rest of app works fine. |
| `APP_LOG_LEVEL` | Minimum level persisted to `app_logs` table (default `WARNING`). Set `INFO` to capture per-request summary rows. |
| `APP_LOG_DISABLE` | If set to any truthy value, disables the DB log handler entirely. Useful only for debugging the logger itself. |
| `APP_DEBUG_TOKEN` | Optional shared secret — **READ-ONLY scope**. If set, `/api/debug/logs`, `/api/debug/summary`, and `/api/debug/client-error` accept the `X-Debug-Token: <value>` header in lieu of OAuth — useful for agent / CI tooling that needs log access without a session cookie. Does NOT authenticate mutating endpoints (see `APP_DEBUG_ADMIN_TOKEN`). Keep secret. Unset = OAuth-only access (default). |
| `APP_DEBUG_ADMIN_TOKEN` | Optional shared secret — **ADMIN scope**. Required to authenticate mutating one-shot endpoints `/api/debug/backfill/*` and `/api/debug/realign-tiers` via the header path. The READ token does NOT pass this gate, so a leaked read token cannot rewrite tier/goal/project assignments. Admin token ALSO satisfies the read-scope decorator (admin ⊇ read). Use rarely — typically once per migration; rotate after each use. Unset = OAuth-only access (default). |
| `TLS_EXPIRY_HOST` | Optional `<hostname>[:<port>]` for the `tls_expiry` health check (#5). When set, `/healthz` opens a TLS socket to the host, reads the peer cert's `notAfter`, and reports `ok` (>30 days), `warn: <N> days remaining` (≤30 days), or `warn: cert expired` — never `fail:`, so an expiring cert can't brick a deploy. Cached 5 min per process. Unset = check is `skipped:` (default — Railway-managed TLS auto-renews). |
| `GITHUB_DISPATCH_TOKEN` | Optional — fine-grained PAT for the #223 `/utilities` backup-trigger + restore-drill cards. Create at https://github.com/settings/personal-access-tokens with **Repository access**: `shigsdev/taskmanager` only, **Permission**: `Actions: Read and write`, **Expiration**: 90 days. The Flask app POSTs to GitHub's `workflow_dispatch` endpoint to fire `daily-backup.yml` or `monthly-restore-drill.yml` on-demand. Unset = the two dispatch endpoints return HTTP 503 with a setup-instructions message; the rest of /utilities still works. |
| `GITHUB_REPO` | Optional override for the `GITHUB_DISPATCH_TOKEN` target repo (default `shigsdev/taskmanager`). Set this only if you forked and want the /utilities dispatch buttons to fire workflows on the fork. |

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
for auth, Fernet for at-rest encryption, SMTP (Gmail) for the daily email digest
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

### Voice-review action token (#297 / ADR-034)

For the hands-free "review my tasks while driving" iOS Shortcut, mint a
**scoped voice-action token** — a `SECRET_KEY`-signed bearer token that
authenticates ONLY `/api/voice-review/*` (read the today/overdue/tomorrow
queue + complete / move-to-`{today,tomorrow,next_week,backlog}` / cancel
a task). It cannot touch tasks CRUD, settings, or exports — see
ADR-034.

```powershell
# Mint (90-day default). The token prints to stdout; the jti prints to
# stderr so you can revoke this specific token later.
railway run python -m flask mint-voice-action-token
# or the standalone (no app import):
railway run python scripts/mint_voice_action_token.py --days 90
```

Paste the token into the iOS Shortcut's `Authorization: Bearer <token>`
header. **Revoke** a single token with `flask revoke-voice-action-token
<jti>`; rotating `SECRET_KEY` on the server invalidates *every* token
(voice-action AND validator cookie) at once — the emergency lever.

Validator cookies expire after the `--days` lifetime they were minted with
(default 90 days, no sliding refresh). Browser session cookies (legacy
fallback) follow the app's session lifetime — 30 days of inactivity. On
a `2` exit code, the script walks you through re-capturing the cookie
from your browser.

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

### Re-running missed cron jobs

Four cron jobs fire between 00:01 and 00:05 every night:
`tomorrow_roll`, `promote_due_today`, `realign_tiers`, and
`recurring_spawn`. If Railway has an outage at midnight and the
scheduler misses the fire, the four jobs silently skip until the
next 24h cycle — tasks in Tomorrow stay in Tomorrow, today-due
items don't promote, etc.

#### Auto-heal at container boot (default — #167, no manual action required)

As of 2026-05-28, the scheduler self-heals at container boot. After
`scheduler.start()` runs in worker 1, a `replay_missed()` loop walks
every nightly job and replays any whose `cron_audit.last_fire_at`
predates today's scheduled time. So when Railway recovers from a
midnight outage, the four nightly crons run automatically inside
the first boot — the user doesn't need to remember to ssh in.

The manual script below is now the FALLBACK path for:

  - Cases the auto-replay didn't cover (e.g. you want to re-run
    `recurring_spawn` for a back-dated day via `--date`)
  - Re-running before the auto-replay window (a deploy that lands
    BETWEEN 00:00 and 00:05 will see "scheduled time is in the
    future today" and skip; for that case manual replay after
    00:05 is still useful)
  - Debugging which row a given fire would touch via `--dry-run`

#### Canonical path — `railway ssh` from inside the container

```bash
railway ssh

# Preview what would run (no writes persist)
/app/scripts/run_missed_crons.py --dry-run

# Real run — all four in scheduler order (00:01 → 00:05)
/app/scripts/run_missed_crons.py

# Subset (e.g. just recurring spawn)
/app/scripts/run_missed_crons.py --only recurring_spawn

# Spawn for a back-dated day (only meaningful for recurring_spawn)
/app/scripts/run_missed_crons.py --date 2026-05-19
```

The `#!/opt/venv/bin/python` shebang plus the executable mode bit
in git mean `./scripts/...` resolves the in-container venv
automatically — no `ModuleNotFoundError: No module named 'dotenv'`
to debug at 11pm during an outage (#169).

#### Legacy / fallback path — `railway run` from your laptop

```bash
railway run python scripts/run_missed_crons.py --dry-run
railway run python scripts/run_missed_crons.py
```

`railway run` injects the prod `DATABASE_URL` + `DIGEST_TZ` into
your local Python so the script touches the production database
directly — no deploy is required. **Caveat:** Railway's internal
Postgres hostname (`postgres.railway.internal`) is only resolvable
from inside the Railway network, so this path will fail with a
DNS hang on most laptops. The script has a fast-fail pre-flight
that exits 2 with a hint pointing you back to `railway ssh` (#168)
rather than blocking for 30s on the SQLAlchemy connect timeout.

#### What gets logged

Every job logs start, finish, and rowcount at WARNING through the
standard logging chain, so the run shows up in `/api/debug/logs`
alongside real scheduler firings.

The 07:00 `daily_digest` is intentionally NOT covered by this
script — use `POST /api/digest/send` for that (avoids accidental
re-sends if you re-run the script).

### Standards

See `CLAUDE.md` for coding standards, quality gates, security rules, and
naming conventions.

**Every commit must pass:**
```bash
bash scripts/run_all_gates.sh
```

That single command runs **all** pre-deploy gates in sequence — ruff +
pytest (with 80% coverage floor) + jest + local Playwright + bandit +
semgrep + gitleaks + pip-audit + npm audit + docs-sync check +
embedded-credentials check on git remote URLs (gate 11, see
[Git credentials runbook](docs/security/git-credentials.md)). It auto-
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

**Token rotation procedure:** if gate 11 catches an embedded credential
in a remote URL (e.g. `https://shigsdev:github_pat_…@github.com/...`),
follow the step-by-step in
[`docs/security/git-credentials.md`](docs/security/git-credentials.md):
revoke the leaked token at https://github.com/settings/tokens, re-set
the remote with SSH or credential-helper-only HTTPS, and audit shell
scrollback / OneDrive version history / screenshots for other copies.
