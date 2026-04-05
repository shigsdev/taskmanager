# Architecture

Living architecture document. Claude Code must update this file whenever a new
component is added, a data flow changes, or a security boundary shifts.

---

## Diagram

```
                        ┌──────────────────────────────┐
                        │       User Devices           │
                        │  iPhone · Mac · Windows PC   │
                        └──────────────┬───────────────┘
                                       │ HTTPS (Talisman)
                                       │ Google OAuth 2.0
                                       ▼
        ┌──────────────────────────────────────────────────────────┐
        │                      Railway                             │
        │  ┌────────────────────────────────────────────────────┐  │
        │  │                 Flask App                          │  │
        │  │  Routes: auth · tasks · goals · digest ·           │  │
        │  │          scan · import · settings                  │  │
        │  │  Services: task · goal · digest · scan             │  │
        │  │  Crypto: Fernet (encrypt sensitive fields)         │  │
        │  └────────┬─────────────────┬────────────────┬────────┘  │
        │           │                 │                │           │
        │           ▼                 ▼                ▼           │
        │   ┌───────────────┐  ┌────────────┐  ┌──────────────┐   │
        │   │  PostgreSQL   │  │ APScheduler│  │  In-memory   │   │
        │   │ tasks·goals·  │  │ daily      │  │  image buffer│   │
        │   │ projects·     │  │ digest @   │  │ (never       │   │
        │   │ recurring·    │  │ DIGEST_TIME│  │  persisted)  │   │
        │   │ import_log    │  │            │  │              │   │
        │   └───────────────┘  └─────┬──────┘  └──────┬───────┘   │
        └──────────────────────────┬─┴─────────────────┬──────────┘
                                   │                   │
                           SendGrid│           Google  │  Anthropic
                                   ▼           Vision  ▼  Claude API
                           ┌───────────────┐    ┌──────────────────┐
                           │ Work Outlook  │    │  OCR + task      │
                           │ (air-gapped,  │    │  parsing (server │
                           │  one-way in)  │    │  side only)      │
                           └───────────────┘    └──────────────────┘

        GitHub (shigsdev/taskmanager) ──push to main──► Railway auto-deploy
```

---

## Components

- **User devices** — iPhone, Mac laptop, Windows PC. All access the app via
  browser over HTTPS.
- **Flask app** — the single web service. Hosts routes, auth, services, and
  scheduler. One process, gunicorn-served.
- **PostgreSQL** — Railway-managed. Stores tasks, projects, goals, recurring
  tasks, and import log.
- **APScheduler** — in-process scheduler that fires the daily digest at
  `DIGEST_TIME` in the user's configured timezone.
- **Fernet crypto module** — symmetric encryption for sensitive fields
  (work email, API keys if ever stored in DB).
- **Google OAuth 2.0** — only login path. Validates the authenticated email
  against `AUTHORIZED_EMAIL` before any data is served.
- **SendGrid** — outbound daily digest email to work Outlook.
- **Google Vision API** — OCR for the image scan feature. Server-side only.
- **Anthropic Claude API** — parses OCR text into discrete task candidates.
  Server-side only.
- **Work Outlook** — receives the daily digest. Air-gapped from the app;
  digest is the only bridge.
- **GitHub repo** (`shigsdev/taskmanager`) — source of truth. Push to main
  triggers Railway auto-deploy.
- **reMarkable** — manual capture only in Phase 1, no API integration.

---

## Data Flows

- **User → App**: HTTPS request, Google OAuth session cookie (encrypted,
  24h inactivity expiry).
- **App → DB**: SQLAlchemy ORM queries. No raw SQL.
- **App → SendGrid**: once per day at `DIGEST_TIME`, plain-text email with
  Today / Overdue / Goals summary / This Week count.
- **Image scan**: browser uploads image → Flask holds in memory → Google
  Vision (server-side) → Claude API (server-side) → task candidates returned
  to browser for review → confirmed candidates written to DB Inbox tier →
  image discarded.
- **Import**: user pastes OneNote text or uploads Excel goals file → parser
  produces preview → user confirms → records written to DB, entry written
  to `import_log`.
- **GitHub → Railway**: push to `main` triggers rebuild + deploy via Nixpacks;
  `release` phase runs `flask db upgrade`.

---

## External Dependencies (version pins maintained in `requirements.txt`)

- flask, flask-sqlalchemy, flask-migrate, flask-dance, flask-talisman
- psycopg2-binary
- cryptography (Fernet)
- apscheduler
- sendgrid
- google-cloud-vision
- anthropic
- gunicorn
- python-dotenv (local dev only)

---

## Security Boundaries

- **HTTPS-only**: all external traffic enforced by Flask-Talisman.
- **Auth boundary**: every data route validates authenticated email ==
  `AUTHORIZED_EMAIL` before serving anything.
- **Encryption at rest**: work email address encrypted with Fernet. Any
  future sensitive fields follow the same pattern.
- **Secrets boundary**: all keys live in Railway environment variables.
  `.env` is gitignored; nothing secret is ever committed.
- **Server-side-only APIs**: Google Vision and Anthropic Claude calls are
  made from the Flask backend. The browser never holds those keys or talks
  to those APIs directly.
- **Image handling boundary**: uploaded images live only in memory for the
  duration of one request. Never written to disk, never written to DB, no
  metadata retained.
- **Air-gap boundary**: the user's work VDI cannot reach the app directly.
  The daily digest email to work Outlook is the only (one-way) bridge.

---

## Baseline

This document's baseline is the initial spec (generated April 2026). Claude
Code must regenerate and update it whenever the system topology changes.
