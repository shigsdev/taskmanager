# Task Manager — Project Backlog

Living feature backlog. Updated every session. Claude Code must update this
file whenever a feature is completed or a new issue is discovered. Items are
moved between sections, never deleted.

---

## In Progress

_(nothing currently in progress)_



## Completed

- [x] Project documentation scaffolding — CLAUDE.md, BACKLOG.md, README.md, ARCHITECTURE.md — completed 2026-04-05
- [x] Basic Flask app with Google OAuth login, single user lockdown — completed 2026-04-05
- [x] Database models and migrations (PostgreSQL) — tasks, projects, goals, recurring_tasks, import_log — completed 2026-04-05
- [x] Core task CRUD — JSON API for create, read, update, delete, move between tiers — completed 2026-04-05
- [x] Goals CRUD — JSON API for create, read, update, delete, link to tasks, progress tracking — completed 2026-04-05
- [x] Main UI — tier board, task cards, quick capture bar, detail panel, voice input — completed 2026-04-05
- [x] Goals view — grouped by category, progress bars, filters, linked tasks, create/edit/delete — completed 2026-04-05
- [x] Project grouping for work tasks — CRUD API, seed defaults, project filter, grouped Work view — completed 2026-04-05
- [x] Inbox + triage flow — verified: default tier, single + bulk triage, filtering, complete/delete from inbox — completed 2026-04-05
- [x] Checklist/notes on tasks — verified: CRUD, progress tracking, round-trips, special chars, independence — completed 2026-04-05
- [x] Mobile-responsive CSS — 44px touch targets, swipe gestures, iOS zoom prevention, full-screen detail panel, project filter scroll — completed 2026-04-06
- [x] Weekly review mode — step-through stale tasks, keep/freeze/delete/snooze actions, progress bar, summary — completed 2026-04-06
- [x] Recurring tasks — CRUD API, 16 system defaults (morning/evening routines, day-specific), spawn to Today tier — completed 2026-04-06
- [x] Print view (/print) — server-rendered, Today + This Week + Overdue, checklists, @media print CSS, no nav chrome — completed 2026-04-06
- [x] Email digest — plain-text digest via SendGrid, preview + send-now API, goals summary, overdue alerts, sanitized content — completed 2026-04-06
- [x] Image scan to tasks — Google Vision OCR + Claude API parsing, review screen with edit/deselect, confirm to Inbox, in-memory only — completed 2026-04-06
- [x] Import tool — OneNote task parsing + Excel goals parsing, duplicate detection, ImportLog audit trail — completed 2026-04-06
- [x] Settings page — app stats, service status, digest controls, import history, quick links — completed 2026-04-06
- [x] Security hardening — Fernet encryption, CSP headers, rate limiting, session hardening, auth audit — completed 2026-04-06
- [x] Railway deployment — Procfile, gunicorn config, runtime.txt, deployment readiness tests, full README — completed 2026-04-06
- [x] Bulk-import undo + Recycle Bin (narrow scope) — import-undo only, manual cleanup, batch_id UUID soft-delete, five new routes — completed 2026-04-09
- [x] Photo-to-goal scan — image scan page parses into Goals (not just Tasks) via radio toggle, shared batch_id with ImportLog — completed 2026-04-10
- [x] LOCAL_DEV_BYPASS_AUTH — four-gate localhost-only auth bypass for agent browser testing, triple Railway tripwire, audit trail — completed 2026-04-10
- [x] URL save on tasks — quick-capture auto-detects URLs, server-side SSRF-protected title fetch, clickable link on task card — completed 2026-04-11
- [x] Subtasks (one-level deep) — parent_id self-referential FK, subtask badge on parent card, goal/project inheritance + cascade, force-complete — completed 2026-04-11
- [x] Personal projects — ProjectType.PERSONAL enum, project CRUD type support, detail panel filters by task type, project filter bar in Personal view — completed 2026-04-13

## Bugs

_(no open bugs)_

## Backlog (prioritized)

| Item | Risks / Notes |
|---|---|
| JS/E2E testing infrastructure — Jest for unit tests + Playwright for browser API testing (Web Speech, Notifications) across engines (Chromium, WebKit) | Adds a whole new toolchain + CI surface. Playwright browser binaries are ~500MB. Start with Jest-only for unit tests, add Playwright later only if browser-API bugs keep slipping through. |
| Live post-deploy browser testing against Railway — agent-driven end-to-end smoke test of the deployed production URL after every push, not just localhost | **Why we want it:** the local `LOCAL_DEV_BYPASS_AUTH` flow (added 2026-04-10) lets the agent click through pages on localhost, but those tests run against local Flask + local DB. They prove the *code* renders correctly; they do not prove that the *deployed Railway version* serves correctly with real env vars, real Postgres, real CSP/Talisman headers. SHA-pinned `/healthz` only proves the container booted — it does not prove the UI is interactive. **Approach options, in increasing order of complexity:** (1) **Second OAuth identity** — add a second authorized email (e.g. `taskmanager-bot@...` Google account) to a new `BOT_AUTHORIZED_EMAIL` env var, log into it once via real OAuth in a headless browser, persist the session cookie to a secret store, and have the agent reuse that cookie for post-deploy tests. Risks: cookie expiry (~24h with current session settings), real Google account needed, cookie is a long-lived credential the agent must handle carefully. (2) **Service-account API token** — instead of a browser session, mint a long-lived bearer token tied to the bot identity and accept it on a `Authorization: Bearer ...` header in `auth.py` (parallel to the `X-Debug-Token` pattern but for the full app, not just `/api/debug`). Simpler than cookies but expands the auth surface. (3) **Dedicated `/api/test/*` endpoints** — narrow JSON-only endpoints that the agent hits with a token to verify each post-deploy invariant (e.g. `GET /api/test/scan-page-renders`). No browser at all; just contract tests against the live deployment. Smallest blast radius, but only catches API breakage, not visual/JS regressions. **Recommended sequence:** start with (3) for the next deploy cycle (cheap, low-risk, immediate value), revisit (1) only once we have a UI bug that (3) can't catch. Either way: every endpoint must be rate-limited, must log every access as WARNING (same pattern as `X-Debug-Token`), and the bot identity's email must be on a separate allowlist from the real user. |

- [x] Mobile-responsive CSS — phase: 1 (done)
- [x] Weekly review mode — phase: 1 (done)
- [x] Recurring tasks (system defaults + user-defined) — phase: 1 (done)
- [x] Print view (/print) — phase: 1 (done)
- [x] Email digest with goals summary (SendGrid + APScheduler) — phase: 1 (done)
- [x] Image scan to tasks (Google Vision + Claude API parsing + review screen) — phase: 1 (done)
- [x] Import tool — OneNote tasks + Excel goals (/import) — phase: 1 (done)
- [x] Settings page — phase: 1 (done)
- [x] Security hardening (Talisman, session expiry, encryption audit) — phase: 1 (done)
- [x] Railway deployment + DNS — phase: 1 (done)

## Freezer (good ideas, not now)

| Item | Risks / Notes |
|---|---|
| Recycle bin: wide-scope (route regular task/goal delete through recycle bin) | Deferred at build time to avoid UX confusion and doubled test surface. Current recycle bin is import-undo only. To enable: drop the `batch_id` requirement on undo routes, add a soft-delete path in the regular delete API, and audit all "delete" UX copy for clarity. Modest code change but non-trivial UX implications. |
| Recycle bin: automated TTL cleanup | Deferred at build time. Would add a scheduled APScheduler job that hard-deletes soft-deleted rows older than N days (candidate: 30). Risk: silent data loss if user forgets the bin exists. If added, surface a prominent "Expires in X days" countdown on each batch in the bin UI, and make the TTL configurable via env var. Only enable once manual cleanup has proven insufficient. |
| Infra monitoring: TLS certificate expiry check in `/healthz` | Railway terminates TLS at their edge and auto-renews Let's Encrypt certs, so the app has no cert to check and a failure would be outside our control. Revisit if we move to a custom domain with a self-provisioned cert, migrate off Railway to a VPS with certbot, or add mTLS client certs for outbound API calls. When revisited, implement as a `warn`-only check (never `fail`) that opens a TLS socket to the public hostname and compares `notAfter` to now (<14 days or expired → `warn`). Cert issues are loud and immediate in browsers anyway, so this is a nice-to-have early warning, not a critical signal. |
| Doc upload (PDF / DOCX) via top-left Upload button — extend `/scan` to accept documents alongside images, parse text via `pdfplumber` / `python-docx`, feed to existing Claude task parser, reuse review screen | **Primary blocker: Claude API token cost.** A 40-page PDF can blow past Claude's input window or cost many multiples of an image scan per upload. Need per-upload char cap (~50k) with truncation warning, and likely a monthly usage budget before enabling. **Other risks:** (1) scanned PDFs have no extractable text — would need Vision OCR fallback, doubling the code paths; (2) legacy `.doc` (binary Word 97-2003) requires `textract` / `antiword` system binaries — reject `.doc` with "Save As → .docx" error instead; (3) new deps `pdfplumber` + `python-docx` (both pure-Python, low risk, but Railway rebuild required); (4) iOS file picker needs user to tap "Browse" not "Photo Library" — UI copy must say so; (5) must stay in-memory only per security rules, same as image scan; (6) MIME spoofing — validate file magic bytes, not just `Content-Type` header; (7) SW cache version bump needed if scan page template changes. **Design decision already made:** route stays `/scan` (no URL breakage), page heading becomes "Upload & Scan", top button stays single-button (no dropdown), file input accepts `image/*,.pdf,.docx`. Revisit once (a) there is a monthly Claude budget in place, or (b) a cheaper local text-to-tasks extraction path exists. |

## Phase 2 Roadmap

- reMarkable integration via remarkable-mcp (USB bridge on Mac)
- Native iPhone app (React Native or Swift)
- Voice memo processing — record during commute, auto-parse tasks
- Weekly summary email (Friday EOD)
- iCloud calendar integration
- AI-assisted triage suggestions based on task age and patterns
- Habit tracking streaks (morning/evening routine completion)
- AI strategy quality checker (check tasks against goals alignment)
