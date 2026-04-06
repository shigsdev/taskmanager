# Task Manager — Project Backlog

Living feature backlog. Updated every session. Claude Code must update this
file whenever a feature is completed or a new issue is discovered. Items are
moved between sections, never deleted.

---

## In Progress

_(none)_

## Completed

- [x] Project documentation scaffolding — CLAUDE.md, BACKLOG.md, README.md, ARCHITECTURE.md — completed 2026-04-05
- [x] Basic Flask app with Google OAuth login, single user lockdown — completed 2026-04-05
- [x] Database models and migrations (PostgreSQL) — tasks, projects, goals, recurring_tasks, import_log — completed 2026-04-05
- [x] Core task CRUD — JSON API for create, read, update, delete, move between tiers — completed 2026-04-05
- [x] Goals CRUD — JSON API for create, read, update, delete, link to tasks, progress tracking — completed 2026-04-05
- [x] Main UI — tier board, task cards, quick capture bar, detail panel, voice input — completed 2026-04-05
- [x] Goals view — grouped by category, progress bars, filters, linked tasks, create/edit/delete — completed 2026-04-05
- [x] Project grouping for work tasks — CRUD API, seed defaults, project filter, grouped Work view — completed 2026-04-05

## Bugs

_(none yet)_

## Backlog (prioritized)

- [ ] Inbox + triage flow — phase: 1
- [ ] Checklist/notes on tasks — phase: 1
- [ ] Mobile-responsive CSS — phase: 1
- [ ] Weekly review mode — phase: 1
- [ ] Recurring tasks (system defaults + user-defined) — phase: 1
- [ ] Print view (/print) — phase: 1
- [ ] Email digest with goals summary (SendGrid + APScheduler) — phase: 1
- [ ] Image scan to tasks (Google Vision + Claude API parsing + review screen) — phase: 1
- [ ] Import tool — OneNote tasks + Excel goals (/import) — phase: 1
- [ ] Settings page — phase: 1
- [ ] Security hardening (Talisman, session expiry, encryption audit) — phase: 1
- [ ] Railway deployment + DNS — phase: 1

## Freezer (good ideas, not now)

_(none yet)_

## Phase 2 Roadmap

- reMarkable integration via remarkable-mcp (USB bridge on Mac)
- Native iPhone app (React Native or Swift)
- Voice memo processing — record during commute, auto-parse tasks
- Weekly summary email (Friday EOD)
- iCloud calendar integration
- AI-assisted triage suggestions based on task age and patterns
- Habit tracking streaks (morning/evening routine completion)
- AI strategy quality checker (check tasks against goals alignment)
