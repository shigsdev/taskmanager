# #429 — Double taps and network retries no longer duplicate

Filed 2026-10-11 by the deep review (§A7). (Spec written after the code map
and before the commit — the surface came from a full sweep of every
non-GET action in `static/*.js`.)

## 1. Surface

**Network retry.** `static/api_client.js` `apiFetch` retried ANY method once
after a network `TypeError`. A TypeError can also mean the server committed
and only the response was lost, so a retried write duplicated a task or
import, ran a second paid analysis, or turned a restore / undo / confirm
into a false "failed" (409 / 404). The PATCH/PUT/DELETE endpoints were
checked: PATCH/PUT are absolute-value sets, but a retried DELETE can 404.

**Double taps — no guard (from the sweep):**

| Site | Code | A double fire |
|---|---|---|
| Recurring Create | `recurring.js` `saveEditor` | two templates, each spawning |
| Capture bar | `capture.js` `submitCapture` | two tasks; text typed meanwhile wiped |
| ➕ New Task (panel create) | `app.js` `taskDetailSave` | two tasks |
| Goal create | `goals.js` `goalDetailSave` | two goals |
| Project create | `projects.js` `projectDetailSave` | two projects |
| Goal "add linked task" | `goals.js` `goalAddLinkedTask` | two tasks |
| Add subtask | `app.js` `addSubtask` | two subtasks |
| Voice memo Add All / Selected | `voice_memo.js` | whole batch twice |
| Scan Add All / Selected | `scan.js` | whole batch twice |
| /review Keep/Freeze/Snooze/Delete | `review.js` `handleAction` | next task skipped unseen |
| /plan Generate | `plan.js` `generate` | two paid calls |
| 💡 Auto-categorize | `inbox_categorize.js` `openModal` | two paid calls |
| ✨ Plan / Plan all | `weekly_focus.js` | two paid calls (#418 drops the stale answer, not the call) |

Already guarded (unchanged): reflection Analyze/Done/Apply, import parse +
confirm, recycle bin, settings Undo, plan row Accept/Apply all, Copy to
tomorrow, triage/categorize Apply, Strength Forge saves, scan upload.

## 2. This ship

1. `apiFetch` retries only GET / HEAD; a failed write goes to the recovery
   prompt.
2. In `api_client.js` (loaded on every page): `withInflight(el | [els], fn)`
   — one run at a time per element (or group), buttons disabled +
   `aria-busy` meanwhile, re-enabled on success or failure, errors passed
   through; and `inflightSubmit(handler)` — the same for a form's `submit`
   listener, keyed on its submit button.
3. Wiring: `inflightSubmit` on the recurring, task-panel, goal and project
   forms; `withInflight` on voice/scan (both buttons as one group), /review
   (all four buttons as one group), /plan Generate, 💡 Auto-categorize and
   ✨ Plan / Plan all (per button — another slot can still plan, #418). The
   capture bar, add subtask and add linked task clear their input as soon as
   the text is read and put it back only if the save fails and the box is
   still empty: a second Enter finds nothing to send, and text typed
   meanwhile is kept.
4. Tests (red on old code): Jest for the retry rule and both helpers;
   Playwright (both viewports) holding the first request open and firing
   again — capture bar, ➕ New Task, recurring Create, /review.
5. CACHE_VERSION bump; CLAUDE.md Phase 6 line + row. No Help change — no
   documented behaviour changes (buttons just can't fire twice).

## 3. Out of scope (not filed — harmless)

- Reflection Continue can show two confirms; the server 409s the second.
- /plan Apply all while a row's Accept is in flight re-sends an idempotent
  PATCH/DELETE.
- Unguarded idempotent PATCH/DELETE buttons (Pause, Archive, Complete…).
- A gate banning unguarded create handlers is part of #459.
