# Deep review — 2026-10-11

Eight read-only reviewers swept the whole codebase (~23k lines of JS, ~25k of
Python, every template and all of `style.css`), one per bug family that has
recurred in recent ships. Findings were then de-duplicated and the
load-bearing ones re-checked by hand.

**Filed** as BACKLOG #424–#459 (A2 → #424, A1 → #425, A3 → #426, A5 → #427,
A4 → #428, A7 → #429, A6 → #430, A8 → #431, A9 → #432, A10 → #433,
A11 → #434, B1–B11 → #435–#448, C1–C5 → #449–#453, D1–D5 → #454–#458,
structural fixes → #459). A12 widened #373; A5 annotated #146.

**Verification key**
- ✔ = re-checked by hand after the review (code read, and where noted, run in
  Node or a real browser at 375 / 1280)
- ◐ = traced end to end by a reviewer, not independently re-run
- ○ = plausible: the code path exists, the trigger depends on timing or environment

Already-open rows (#146 #295 #361 #364 #373 #419 #420 #421 #423) are not
repeated except where a finding widens or explains one.

---

## Why new issues keep turning up

Every ship has found a sibling of the bug it fixed because the same mistakes
are written out by hand in many files, with no shared helper or mechanical
check to stop them:

1. **No shared patterns for async work.** Each page reinvents "disable while
   saving", "drop a stale answer" and "tell the user it failed". Most pages
   do none of the three. (#418 added the first shared helper.)
2. **The same rule lives in two or three places.** Tier ↔ date math is in
   `tier_helpers.js`, `app.js`, `calendar.js` and `task_service.py`; only
   `calendar.js` was fixed for DST. Counts are computed client- and server-side
   with different filters.
3. **Tests check the server, not what the client actually sends.** The
   voice-memo goal/project/recurring paths are fully tested on the server with
   hand-built payloads; the real client never sends those fields.
4. **The test environment is gentler than prod.** SQLite ignores column
   lengths that Postgres enforces; Jest runs in the machine's timezone with no
   DST dates pinned; seeded titles are short; Phase 6 checks the changed page.

The structural fixes at the end of this file target these four causes, so the
next ship stops finding the next sibling.

---

## Tier 1 — wrong data, lost data, or a deadline

### A1. Voice memo: Goal / Project / "Make recurring" have never worked from the app ✔ (found by 3 reviewers)
`static/voice_memo.js:857-865` maps each candidate to
`{title, type, tier, due_date, project_id, goal_id, included}`. The server
(`voice_api.py:218-262`) routes on `route`, `category`, `priority` and
`repeat`, which are never sent. The mapping dates from #37 (2026-04-21);
goal/project routing (#67, 2026-04-26) and recurring (#155, 2026-05-09) were
added server-side later and never wired through. Everything lands as an Inbox
task; the done message says "N tasks added to Inbox". `tests/test_voice_memo.py`
posts `route` by hand, so it passes.
**Fix:** forward the four fields; build the payload in `voice_memo_helpers.js`
with a Jest round-trip test; build the done message from
`data.tasks/goals/projects/recurring` and show `data.warning`.

### A2. Daylight-saving breaks tier/date math on 2026-11-01 (3 weeks out) ✔ (reproduced in Node, TZ=America/New_York)
`static/tier_helpers.js` (`_MS_PER_DAY`, lines 22, 81, 86-91, 117) and
`static/app.js:218, 384-389, 586, 643, 651, 3783-3784` add `n × 86400000` ms to
local midnight. Reproduced:
- On Nov 1, `dueDateForTier("tomorrow")` → **2026-11-01** (today). Tomorrow
  button / drag / panel Section stamp today's date; the card shows in Today and
  Tomorrow.
- On Oct 28, `tierForDueDate("2026-11-08")` → **backlog** (should be next_week).
- On 2027-03-10, `tierForDueDate("2027-03-15")` → **backlog**.
- The day strip shows Nov 1 twice and never Nov 8; next-week headers and
  previews are off by one in the week before each change.

`calendar.js:29-47` already explains and fixes this exact bug.
**Fix:** calendar arithmetic (`new Date(y, m, d + n)`), compare Y/M/D; Jest
cases pinned to 2026-10-28, 2026-11-01, 2027-03-10 under `TZ=America/New_York`.

### A3. Saving a recurring task moves its template's start date, so occurrences are skipped ✔
`task_service.py:448-451` (`_update_repeat`) sends
`start_date = repeat.start_date or task.due_date` on **every** save; the panel
never sends `start_date`, so it is always the spawned task's due date.
`_template_fires_on` then won't fire before it. Push Monday's "Weekly Work
Prep" to next Tuesday and save → next Monday's spawn never happens. If the
pushed date is past the template's `end_date`, the task save is rejected (422).
The comment says it was meant only to backfill a NULL start date.
**Fix:** only backfill when the template's `start_date` is NULL.

### A4. "Deleted tasks land in the recycle bin" — they don't ✔
`static/app.js:3567` (bulk-delete confirm), `templates/docs.html:843-845` and
the reflection prompt (`reflection_service.py:240`) say deletes are
recoverable from the bin. `task_service.delete_task` (`:920-934`) sets
DELETED and clears `batch_id`; the bin lists only import batches
(`recycle_service.py:136-143`). There is no UI path to restore a deleted task.
**Fix:** correct the copy, or give deleted tasks a real restore path (decision).

### A5. Goal links silently wiped — probable root cause of #146 ✔ / ◐
- `task_service.py:752-753`: PATCH `{project_id: null}` clears `goal_id` even
  when the goal was set directly and the task never had a project. The bulk
  toolbar's "No project" does this to every selected task. ✔
- 💡 Auto-categorize Apply (`inbox_categorize.js:151-154, 444-475`) seeds its
  selects from Claude's suggestion, not the task's current values, and always
  sends `project_id`, `goal_id` and `type`. A captured task with a project and
  goal loses both when Claude suggests none; a Work task can flip to Personal. ◐
- #146 ("goal reset to None on save", deferred for lack of a repro) listed
  "bulk-edit" as an unexplained path. Both of these fit.
**Fix:** clear the goal only when it came from the old project; seed
Auto-categorize from current values and omit unchanged fields.

### A6. Board actions that fail look like they worked ◐
No `.catch` / no message on: drag-and-drop (`app.js:1135-1193`, the DOM is
already moved during dragover), quick tier buttons and ✓
(`taskMoveTier`/`taskComplete`, `:1911-1956`), panel Delete and Complete
(`:2338-2348` — Complete closes the panel first), swipe-Delete
(`swipe.js:133-140`), Inbox triage (`:1895-1907`, `Promise.all` — one failure
skips the reload), bulk drop on Completed (`:954-964, 1047-1057`), subtask
checkbox (`:3313-3320`), goal linked-task checkbox (`goals.js:417-424`), goal
Archive toggle (`goals.js:535-556`). The card stays where it was dropped until
the next 55 s poll snaps it back.
Also: `saveReorder` sends the whole tier; a tier with >200 cards gets a 422
after the cross-tier PATCH already landed (`tasks_api.py:286-289`) ○.
**Fix:** one shared error path (alert + `loadTasks()`), as `taskCancel` already does.

### A7. Double taps and network retries create duplicates ✔ / ◐
- `static/api_client.js:93-96` retries **any** method once after a network
  `TypeError` ✔. If the server committed and the response was lost (phone
  switching networks), a POST runs twice: duplicate task, duplicate import,
  a second paid reflection analysis; restore/undo/confirm retries come back
  409 and show "failed" for something that worked.
- No in-flight guard on: recurring template Create (`recurring.js:413-431`)
  — a double click makes two templates that each spawn daily; capture bar
  (`capture.js:14-65`, input cleared only after the await, and it also wipes
  the next thing you started typing); panel Save in create mode
  (`app.js:3162-3222`); goal and project create; goal "add linked task"; add
  subtask; voice memo and scan confirm; /review buttons (a double tap skips the
  next task unreviewed, `review.js:143-156`); /plan Generate (two paid calls).
**Fix:** retry only GET/HEAD; one shared `withInflight(button, fn)` helper.

### A8. Reflection: a failed mid-writing Analyze, then Try Again, can blank the saved draft ◐
`reflection.js:202-231` (interim analyze) routes errors to the error screen,
whose only button runs `resetInput` (`:1091-1116`): it empties the box but
leaves `lastSavedText` and `draftRetired` alone. The next autosave trigger
(tab hidden, any input) PUTs `{text: ""}` and the server overwrites the draft
(`reflection_service.py:1339`). The error copy also claims the transcript is
"in your history below", which is false for an interim run.
**Fix:** send the interim failure back to the writing view with text intact;
reset `lastSavedText` in `resetInput`.

### A9. Import: a late parse after Back imports tasks as goals; Parse buttons die ✔ / ◐
`import.js:127-155` (`resetAll`) sets `currentMode = null` but doesn't cancel
the in-flight parse. A late answer shows the review screen with no mode, and
"Import all" falls through to `/api/import/goals/confirm`
(`import.js:1067-1069`) ✔. Separately, `resetAll` never re-enables the Parse
buttons, so after "Import More" / "Start Over" they stay disabled until reload ◐.
**Fix:** `createRequestGuard` per parse; set the mode inside each handler;
re-enable buttons in `resetAll`.

### A10. Bulk complete / cancel / delete orphans open subtasks ✔
The single-task paths go through `complete_parent_task`/`cancel_parent_task`
(#176). Bulk Mark complete / Mark cancelled / multi-drag to Completed go
through `update_task`'s status branch (`task_service.py:709-720`), which has
no subtask handling; `delete_task` has the same gap. Subtasks become standalone
cards with a dead-parent badge.
**Fix:** route status changes through the parent-aware services.

### A11. Work / Personal board view hides tasks on archived projects ✔
`app.js:807-843` groups by `allProjects` (active only) plus "No project".
Since #353 archiving keeps the link, so a task on an archived project lands in
neither group, while the header count (`:777-782`) still counts it: "Inbox 7",
4 cards. The All tab shows all 7.
**Fix:** put tasks whose project isn't in `allProjects` under an
"(archived project)" group.

### A12. Recycle bin ignores projects (widens #373) ◐
`recycle_bin.js:45-49, 99-100` and `settings.js:135` total only tasks +
goals. A project-only batch (a projects import, then Undo) shows "The recycle
bin is empty", Empty Bin disabled, a batch row reading "0 items", and Purge
says "Permanently delete 0 tasks and 0 goals" while it removes N projects.
**Fix:** fold into #373 — include `project_count` everywhere.

---

## Tier 2 — wrong or misleading, no data lost

### B1. Tier-only moves don't re-date the task ◐
Bulk toolbar tier change (`app.js:3683-3689`), voice-review moves
(`voice_review_api.py:149`) and ✨ Plan promotes (`weekly_focus.js:482-488`)
send `tier` alone; `_auto_fill_tier_due_date` skips tasks that already have a
date. A Today task bulk-moved to Tomorrow keeps today's date and shows in both
panels; a voice-moved overdue task stays overdue and re-queues every run; a
promoted task is moved back by the 00:03 realign. The board's own tier buttons
already send `dueDateForTier` (`app.js:1103, 1920`).

### B2. /plan and the AI planners ✔ / ◐
- `weekly_planner_service.py:258` calls `compute_previews_in_range(start, end)`
  positionally; the function is keyword-only. The TypeError is swallowed, so
  the planner has never seen recurring fires (and it reads `due_date` where the
  key is `fire_date`). Help says it treats them as committed time. ✔
- Accepting a "move" with no suggested date sends `due_date: null`
  (`plan.js:325-326`), wiping the task's date and skipping tier auto-fill (the
  #208 fix in Auto-categorize avoided exactly this). ◐
- "Apply all accepted" applies every **pending** row, deletes included
  (`plan.js:354-367`). Help describes it correctly; the label doesn't. ✔
- Archived goals are offered to all three AI planners
  (`inbox_categorize_service.py:165`, `weekly_planner_service.py:304-309`,
  `weekly_focus_service.py:483`). ◐

### B3. Reflection ◐
- "Today" and the ISO week come from UTC (`reflection_service.py:762, 92-96`):
  after 8 pm ET Claude is told tomorrow's date, and a Sunday-evening reflection
  is filed under next week.
- A partly failed Apply still sets `applied_at`, so the failed actions can
  never be retried (409), and the error text embeds raw SQLAlchemy messages
  (`reflection_service.py:1759-1886`) that #189 removed elsewhere.
- Apply / submit failures throw away the review screen (`reflection.js:968-972,
  751-769`); a retry costs another analysis.

### B4. Week rollover rules (needs a decision) ◐ / ○
- Undated Next Week tasks never become This Week on Monday (realign only
  touches dated tasks; #220 deliberately clears the date on a punt).
- Monday's 00:03 realign moves an overdue This Week / Next Week task to
  Backlog (`task_service.py:1201-1215`); only Today is protected (#170).

### B5. Background jobs can stop silently ○
- The scheduler starts only in gunicorn worker `age == 1`
  (`gunicorn.conf.py:40`); a replacement worker (e.g. after a 120 s timeout
  kill) never starts one, so the nightly jobs and the digest stop until the
  next deploy.
- The 07:00 digest has APScheduler's 1-second misfire grace and no replay.
- `tzdata` isn't in `requirements.txt`; `utils.py:33-40` silently falls back to
  UTC if zoneinfo is missing.

### B6. A failed first load leaves dead or misleading pages ◐
/goals and /projects bind their listeners after the first load, so a failed
load leaves a blank page with dead buttons and a panel that can't be closed.
The board shows "All caught up — inbox is empty" after a failed load; a failed
calendar poll wipes a populated calendar to empty cells; Completed / Cancelled
stay on "Loading…" forever; /recurring, /recycle-bin, /settings and the focus
panel render blank or "0".

### B7. More stale-answer races (siblings of #418 / #421) ◐
- Weekly Focus: switching This/Next Week while a save is in flight can show
  this week's slots under the Next Week tab; ✨ Plan then plans the wrong week.
  A failed tab switch flips the offset anyway, so the next edit saves into the
  other week. Every save re-renders all slots, eating keystrokes in the next
  slot and dropping focus.
- Task panel: a late subtask / parent-link load from task A renders into task
  B's panel (ticking one completes A's subtask); two quick subtask ticks
  duplicate every row.
- Goal panel: a late linked-task refresh paints goal A's tasks into goal B.
- Clicking a recurring preview card, then opening another task, lets the late
  answer replace the open panel and its unsaved edits.

### B8. Failures that throw away work ◐
Voice memo: a failed upload discards up to 10 minutes of recorded audio; a
failed Confirm discards the reviewed list. Strength Forge: logging a workout,
Undo, starting/changing/resolving a flare fail silently.

### B9. Surfaces that disagree ◐ / ✔
- The capture bar on `/tier/<name>` always files to Inbox: `parseCapture`
  always sets `tier: "inbox"` (`parse_capture.js:19`), so the tier page's
  default (`capture.js:28`) never applies. ✔
- Nav Inbox badge is a hard-coded "0" on 11 pages that don't load `app.js`.
- Bulk actions and panel Delete don't refresh Completed / Cancelled or the
  Today ring; Settings counts go stale after Undo.
- Board recurring previews are loaded once and never refreshed.
- /calendar has no place for overdue tasks or tasks beyond the 2/4/8-week
  window — they appear nowhere on that page.
- The digest lists overdue Today tasks twice; /print doesn't.
- Completed cards show the UTC date (`app.js:2201`) while the Today ring uses
  the local date.
- The service-worker auto-reload guard (`base.html:129-130`) only protects the
  task panel; an open ✨ Plan / Auto-categorize review or goal/project panel is
  lost when a deploy lands.

### B10. Server input handling (no data loss; opaque errors) ✔ / ◐
- No length checks against Postgres column widths (task/goal/template titles
  500, project name 200, quarters 20, `ImportLog.source` 100). SQLite ignores
  them, so tests pass; on prod a long paste gets an opaque "Database error",
  and one long line fails a whole import batch.
- Project colour accepts 8-digit hex but the column is `String(7)`
  (`models.py:189` vs `project_service.py:33`). ✔
- References to nonexistent / archived / wrong-type projects and goals aren't
  checked (generic 422, or silently invisible links).
- `complete`/`cancel` don't check current status: completing a DELETED task
  brings it back as ARCHIVED (`task_service.py:849-868`). ✔
- Recurring `is_active: "false"` resumes templates (`bool()` coercion); a null
  project `type`/`status` hits NOT NULL; non-object JSON bodies and non-string
  titles return 500; `Infinity` overflows in several int coercions.
- `/utilities` audit endpoints run up to 2×120 s synchronously (gunicorn
  timeout 120 s) and have no rate limit.

### B11. Help copy that has drifted ◐
Nine claims in `templates/docs.html` no longer match code: recurring preview
click (1563), digest "plain text only" (2583), print metadata (2528-2548),
filter dimensions (2023-2044), rate limits (1724, 1867), Settings bin count
(2627), Unscheduled list (2096), planner recurring fires (1814-1816),
Auto-categorize goal set (1708) — plus A4's recycle-bin claim (843-845).

---

## Tier 3 — phone layout and dark mode

### C1. The capture box is 67 px wide on the phone board ✔ (measured at 375)
The type select plus four icon buttons leave the input 67 px (117 px on
/tier). **Fix:** put the input on its own row at ≤600 px.

### C2. iOS zooms the page when you tap most text fields ✔ (measured 14.4 px)
Capture input, search, focus slots, recycle DELETE box, reflection milestone,
scan/import/voice review fields, Strength Forge log form are all < 16 px; only
the task panel was fixed. In the installed PWA the page stays zoomed.
**Fix:** one ≤767 px rule setting inputs/selects/textareas to 16 px.

### C3. Dark-mode contrast ✔ / ◐
- A selected task card turns pale grey-blue with cream text — barely readable
  (`style.css:4035`, `#e8f0fe`). ✔ (seen in a screenshot)
- The voice-memo error box is cream text on near-white (`style.css:3979-3985`). ◐
- Failure tints (✨ Plan, Auto-categorize, /plan) are near-invisible at 0.08. ✔
- White text on sage/amber buttons (Keep, Snooze, Complete) ≈ 2.5:1; recurring
  preview cards grey on dark and flip to white on hover. ◐

### C4. Things clipped or broken on the phone ◐
- A Completed card's "Re-open" menu is clipped to the card
  (`overflow:hidden` at ≤600 and from `swipe.js`), so only ~10 px shows.
- Swipe-to-reveal shows blank space at ≤600 (buttons clipped); above 600 on
  touch devices it shows unstyled Move/Delete buttons.
- `hidden` loses to `display:flex`: an empty 18 px filter banner is always on
  the board ✔ (measured); Strength Forge detail rows can't collapse; Utilities
  cards get extra margin.
- Bulk toolbar is half the viewport wide above 600 px; /projects bulk
  dropdowns open beneath the toolbar and off-screen; Settings tables are
  clipped 16 px with no scroll; scan/import review rows overflow 375 px; the
  reflection "Analyze together" bar hides under the nav; the nav is 165 px
  tall on the phone ✔.

### C5. Tap targets under 44 px ◐
Subtask complete checkbox (13 px), checklist ✕, linked-task checkbox,
/recurring and /projects bulk checkboxes, Weekly Focus tabs, Auto-categorize ✕,
calendar task links, search box, and most Strength Forge controls.

---

## Tier 4 — keyboard and screen reader (beyond #419 / #295)

- **D1.** Projects, goals, recurring templates and calendar items can't be
  opened by keyboard at all — no way to edit/archive them without a mouse. ◐
- **D2.** File pickers on /import and /scan are `display:none` inputs behind
  unfocusable labels — every Excel/.docx/transcript/scan flow is unreachable. ◐
- **D3.** The panel Tab trap breaks on a "Completed (N)" summary: Tab jumps to
  ✕, skipping Save/Archive and the completed rows (`panel_keys.js:41-48`). ◐
- **D4.** Dropdown menus (triage, re-open, bulk, custom date, /projects,
  /recurring) have no Escape, no focus movement and no menu semantics. ◐
- **D5.** Board quick-action buttons are tab stops with an invisible focus ring
  (opacity 0 until hover); parent-picker results and bulk chips are
  mouse-only; ~50 form controls have no accessible name; overlays lack
  `role=dialog`/`aria-modal`; no skip link. ◐
- **D6.** Weekly Focus re-renders on every blur/change, so Tab out of a slot
  loses focus and arrow keys on the goal select can't pick a goal. ◐

---

## Structural fixes (stop the next sibling)

1. **Shared client helpers**, then migrate callers page by page:
   `withInflight(button, fn)` (A7), `createRequestGuard` everywhere a
   reused container is filled (B7, A9, #421), one `reportFailure(err, {reload})`
   (A6, B6, B8), calendar-day arithmetic in `date_helpers.js` (A2).
2. **Mechanical gates** in `run_all_gates.sh`: ban `86400000`/`_MS_PER_DAY`
   date arithmetic and `toISOString().slice(0, 10)` outside `date_helpers.js`;
   ban a bare `.then(` on `apiFetch` with no `.catch`; a Jest suite run under
   `TZ=America/New_York` with DST dates pinned.
3. **Client-payload round-trip tests** for every review → confirm flow (voice,
   scan, import, reflection, plan, auto-categorize): Jest the payload builder
   against the server's expected keys (A1, A5, B2).
4. **Postgres-only constraints**: a server-side length/format validator driven
   by the model's column widths, plus a test that every `String(n)` column has
   a matching cap (B10).
5. **Phase 6 seed data** with a 300-character title, a URL title, an archived
   project with active tasks, and a >200-card tier.
