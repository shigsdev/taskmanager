# Personal Task Manager

A personal productivity system — task management, goal tracking, and daily
execution. Built with Python + Flask, hosted on Railway, accessible from any
device via browser. Designed for a single user managing 50-100 tasks across
work and personal life, with a regulated (air-gapped) work environment.

## Features

_Features are added here as backlog items are completed. See `BACKLOG.md` for
current status._

## Setup

### Railway Deployment

1. Create a Railway account and a new project
2. Add the PostgreSQL plugin to the project
3. Connect the GitHub repo to Railway
4. Set all environment variables in the Railway dashboard (see below)
5. Deploy — Railway auto-detects Python/Flask via Nixpacks
6. Note the generated Railway URL (e.g. `taskmanager.up.railway.app`)
7. Add the Railway URL to Google Cloud Console as an authorized redirect URI

### Google OAuth Setup

1. Go to https://console.cloud.google.com
2. Create a new project: "Task Manager"
3. Enable the Google+ API and Google OAuth2 API
4. Create OAuth 2.0 credentials (Web application)
5. Add authorized redirect URI:
   `https://[your-railway-url]/login/google/authorized`
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
| `DATABASE_URL` | Railway PostgreSQL connection string |
| `SENDGRID_API_KEY` | Or SMTP credentials for digest delivery |
| `WORK_EMAIL` | Encrypted work Outlook address (for digest) |
| `DIGEST_TIME` | Time of day digest is sent (default `07:00`) |
| `GOOGLE_VISION_API_KEY` | OCR for image scan feature |
| `ANTHROPIC_API_KEY` | Claude API for parsing OCR text into tasks |

## Usage

_Day-to-day usage notes (capture, triage, weekly review, digest, import) will
be added as features come online._

## Architecture

See `ARCHITECTURE.md` for the living architecture diagram, component
descriptions, data flows, and security boundaries.

Brief summary: Flask app + PostgreSQL + APScheduler on Railway, Google OAuth
for auth, Fernet for at-rest encryption, SendGrid for the daily email digest
that bridges to the user's air-gapped work Outlook.

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

### Run tests

```bash
pytest --cov
ruff check .
```

### Standards

See `CLAUDE.md` for coding standards, quality gates, security rules, and
naming conventions. Every commit must pass `pytest --cov` (80% floor) and
`ruff check .` with zero warnings.
