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
- [x] JS testing infrastructure (Jest phase) — extracted parseCapture to importable module, Jest + jsdom devDeps, 34 unit tests mirroring Python suite, npm test in quality gates — completed 2026-04-16

## Bugs

_(no open bugs)_

## Backlog (prioritized)

| # | Item | Category | Priority | Value | Effort | Complexity | Status |
|---|---|---|---|---|---|---|---|
| 1 | **Playwright browser API testing** — E2E tests for Web Speech, Notifications, SW lifecycle across engines (Chromium, WebKit) | Testing | Medium | Catches browser-specific bugs that Jest/jsdom can't — real SW lifecycle, real speech API, real permission dialogs | Medium — ~500MB browser binaries, new test harness, CI integration | Medium — Playwright API is well-documented but browser permission mocking is fiddly; flaky test risk | Jest done (2026-04-16). Add only if browser-API bugs keep slipping through manual smoke tests |
| 2 | **Live post-deploy browser testing** — agent-driven smoke test of deployed Railway URL after every push | Testing / Infra | Medium-High | Proves the *deployed* app works, not just localhost — catches env var issues, CSP headers, real Postgres differences | Low (option 3) to High (option 1) — `/api/test/*` endpoints are a day; full OAuth bot is multi-day | Low (option 3) to High (option 1) — test endpoints are simple JSON; browser session needs cookie mgmt + secret storage | 3 approaches scoped. Start with `/api/test/*` endpoints (option 3) |

## Freezer (good ideas, not now)

| # | Item | Category | Priority | Value | Effort | Complexity | Blocked on |
|---|---|---|---|---|---|---|---|
| 3 | **Recycle bin: wide-scope** — route regular task/goal delete through soft-delete | UX | Low | Undo accidental deletes, not just import undos — safety net for daily use | Low-Medium — drop `batch_id` requirement, add soft-delete path, update UX copy | Low — straightforward DB change, but every "delete" button needs UX clarity review | UX design for soft vs. hard delete messaging |
| 4 | **Recycle bin: TTL cleanup** — auto-purge soft-deleted rows after N days | Infra | Low | Prevents DB bloat — set-and-forget maintenance | Low — one APScheduler job, one env var, one UI countdown | Low — simple scheduled query + "expires in X days" UI | Only after manual cleanup proves insufficient |
| 5 | **TLS certificate expiry check** — warn-only check in `/healthz` | Infra | Very Low | Early warning on cert expiry — but Railway auto-renews, so near-zero risk today | Very Low — one function, TLS socket check | Very Low — well-understood pattern, warn-only | Only if moving off Railway-managed TLS |
| 6 | **Doc upload (PDF/DOCX)** — extend `/scan` to accept documents via pdfplumber/python-docx | Feature | Medium | Capture tasks from meeting notes and PDFs without manual retyping | Medium — two new deps, text extraction, Claude prompt tuning, MIME validation | Medium-High — scanned PDFs need OCR fallback (doubles code paths), `.doc` rejection, token cost control | Claude API monthly budget + per-upload char cap |

## Phase 2 Roadmap

| # | Item | Category | Priority | Value | Effort | Complexity | Notes |
|---|---|---|---|---|---|---|---|
| 7 | **reMarkable integration** — USB bridge via remarkable-mcp on Mac | Feature | Medium | Capture handwritten notes to tasks directly from the tablet | Medium — depends on remarkable-mcp maturity and USB reliability | High — third-party MCP dependency, USB quirks, handwriting OCR accuracy varies by writing style | Needs remarkable-mcp stable first |
| 8 | **Native iPhone app** — React Native or Swift | Feature | Medium-High | Faster capture, push notifications, offline support, native feel | Very High — entire new codebase, App Store process, offline sync, push infra | Very High — offline-first sync is notoriously hard, two codebases to maintain | Largest item on roadmap; evaluate after web app is stable |
| 9 | **Voice memo processing** — record during commute, auto-parse tasks | Feature | High | Hands-free task capture while driving/walking — biggest friction point today | Medium — audio recording UI, Whisper/Deepgram transcription, Claude parsing, review screen | Medium — transcription API selection, audio format handling, cost per minute of audio | High value, moderate effort — strong candidate for next feature |
| 10 | **Weekly summary email** — Friday EOD digest | Feature | Medium | End-of-week reflection: what got done, what slipped, what's next week | Low — extend existing digest service with weekly template + Friday APScheduler job | Low — reuses digest infrastructure, just a new template and "completed this week" query | Quick win — builds on existing digest |
| 11 | **iCloud calendar integration** — sync due dates and time-blocked tasks | Feature | Medium | See tasks alongside meetings, block time for deep work | High — Apple CalDAV auth, two-way sync, conflict resolution, timezone handling | High — CalDAV protocol is verbose, Apple OAuth is quirky, two-way sync means conflict resolution | Significant auth + sync complexity |
| 12 | **AI-assisted triage suggestions** — recommend tier based on task age and patterns | Feature | Medium | Reduce inbox pile-up — AI suggests "this has sat 14 days, freeze or delete?" | Medium — data analysis queries, Claude prompt, accept/dismiss UI | Low-Medium — heuristics are simple (age, tier, patterns); main work is suggestion UI | Needs enough historical data to be useful |
| 13 | **Habit tracking streaks** — morning/evening routine completion tracking | Feature | Low-Medium | Visualize consistency, motivate daily habits — builds on existing recurring tasks | Medium — streak model/columns, calculation logic, calendar heatmap or counter UI | Low-Medium — builds on recurring task data; main complexity is streak visualization | UI design needed for heatmap vs. counter |
| 14 | **AI strategy quality checker** — check tasks against goals alignment | Feature | Low-Medium | "12 Work tasks but none link to Q2 OKR goal" — strategic drift detection | Low-Medium — query tasks vs. goals linkage, Claude analysis prompt, summary UI | Low — mostly read-only analysis; hard part is a Claude prompt that gives genuinely useful advice | Interesting but low urgency until goal count grows |

### Quick-win picks (high value, low effort)

1. **Weekly summary email (#10)** — Low effort, reuses digest infra, immediate user value
2. **AI triage suggestions (#12)** — Medium effort, reduces daily friction, leverages existing data
3. **Voice memo processing (#9)** — Medium effort, solves biggest capture friction point
