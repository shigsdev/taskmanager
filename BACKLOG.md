# Task Manager — Project Backlog

Living feature backlog. Updated every session. Claude Code must update this
file whenever a feature is completed or a new issue is discovered. Items are
moved between sections, never deleted.

---

## In Progress

| Item | Risks / Notes |
|---|---|
| Bulk-import undo + Recycle Bin (narrow scope, manual cleanup only) | Building now. Recycle bin is import-undo only — regular task delete stays hard-delete. No automated TTL cleanup — user manually empties bin or purges individual batches. Five new routes + new page + global `do_orm_execute` filter for soft-delete. Schema: `batch_id UUID` + `deleted_at DATETIME` on `tasks`/`goals`, `batch_id UUID` + `undone_at DATETIME` on `import_log`. |



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

## Bugs

| Item | Risks / Notes |
|---|---|
| Voice input on iPhone — recording starts and stops but captured text does not appear in the task input bar (reported 2026-04-09) | iOS WebKit Web Speech API is flaky in PWA standalone mode. May need polyfill or server-side Whisper fallback. Hard to reproduce without physical iPhone. |

## Backlog (prioritized)

| Item | Risks / Notes |
|---|---|
| JS/E2E testing infrastructure — Jest for unit tests + Playwright for browser API testing (Web Speech, Notifications) across engines (Chromium, WebKit) | Adds a whole new toolchain + CI surface. Playwright browser binaries are ~500MB. Start with Jest-only for unit tests, add Playwright later only if browser-API bugs keep slipping through. |

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
