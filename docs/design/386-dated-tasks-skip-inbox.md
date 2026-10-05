# Spec #386 — a task created with a due date still lands in Inbox

**Filed:** 2026-10-04 (user report, iPhone screenshot: three Inbox cards
already carrying due dates 2026-10-08 / 10-15 / 10-22, projects DTCC
Onboarding / JPMC Transition, goal "Transition out of JPMC")
**User's words:** "When I create a task and assign a date it should not
go to the inbox."
**Status:** decisions recorded 2026-10-05 (§8) — approved to build
**Backend change:** yes (task_service, scan_service, import_service).
**Frontend change:** yes (`static/app.js` task panel) → Phase 6 + CACHE_VERSION bump.
**Prod data:** checked 2026-10-05 via the validator cookie — 76 active
tasks, **0 in Inbox**, so no cleanup/migration is needed.

---

## 1. The rule that already exists

`task_service._tier_for_due_date` (`task_service.py:238`) maps a date to
its natural section: today → Today, tomorrow → Tomorrow, this Mon–Sun →
This Week, next Mon–Sun → Next Week, later → Backlog.
`_auto_promote_tier_on_due_today` (`:274`) applies it whenever a write
carries `due_date`, **except** when (a) the same write also carries
`tier` ("caller explicit about both", `:286`), (b) the task is in
Freezer, (c) the task is not Active.

The Help page documents exactly this (`templates/docs.html:1403-1424`).

## 2. Why dated tasks still land in Inbox — four causes

### A. Three create paths never run the rule at all (the screenshot)

`create_task` (`task_service.py:460`) is the only creator that calls
`_auto_promote_tier_on_due_today` — and its only caller is
`POST /api/tasks` (`tasks_api.py:107`). Every other path builds
`Task(...)` directly with whatever tier it was handed:

| Path | Code | Tier it is handed |
|---|---|---|
| Reflection proposals ("apply") | `reflection_service.py:1789-1806` → `scan_service.create_tasks_from_candidates` | `f.get("tier") or "inbox"` (`:1796`) |
| Scan (photo) confirm | `scan_api.py:219` → same function | LLM-inferred, default inbox (`scan_service.py:1385-1389`) |
| Voice memo confirm | `voice_api.py:264` → same function | LLM-inferred, default inbox |
| Import confirm (OneNote/Excel) | `import_service.py:745-827` | `candidate.get("tier") or "inbox"` (`:763`) |

So a reflection that proposes "Turnover LLM Suite ownership, due
2026-10-08" creates an Inbox task with that date, full stop. The
screenshot's JPMC-transition tasks fit this path.

This also makes the Help page wrong today: the Excel import section says
a due date "will auto-route the task to the matching section on save"
(`docs.html:1176`) — the import path never routes.

### B. The API treats a *default* `inbox` as an explicit choice

The new-task panel (`taskDetailOpenNew`, `static/app.js:2511`) opens with
`tier: "inbox"` and saves with **both** `tier` and `due_date`
(`taskDetailSave`, `:3173-3176`). Rule (a) then keeps Inbox.

Normally the panel's live listener (`app.js:2461-2471`) flips the
Section dropdown when you pick a date, so the payload already says
e.g. `this_week`. But when the date is **pre-filled by code** — the
`/calendar` empty-cell click passes `prefillDue` (#270, `:2508-2518`) —
no `change` event fires, the dropdown stays on Inbox, and the task is
saved to Inbox on the very day you clicked.

### C. The live listener only listens for `change`

`app.js:2461` uses `addEventListener("change", …)` on the date input.
iOS Safari's date picker is reported to commit values without a timely
`change` in some versions; if it doesn't fire before Save, the dropdown
is still Inbox and cause B applies. Not reproduced yet — §6 tests it.

### D. Once in Inbox, a dated task never leaves on its own

The 00:03 `realign_tiers_with_due_dates` job skips Inbox on purpose
("still needs triage", `task_service.py:1124,1141`), and the 00:02
`promote_due_today_tasks` job only promotes from This Week / Next Week /
Backlog (`:1171`). So a dated Inbox task stays in Inbox even on its due
date.

### Not a cause: the capture bar

The row suspected `parse_capture.js:19` (`tier: "inbox"` default).
`parseCapture` never produces a due date (no `due:` syntax,
`docs.html:415`); a date only comes from `#today` / `#tomorrow`, which
set the matching section anyway. No change needed there.

## 3. Proposed rule

> **Inbox never keeps a task whose due date arrives in the same write.**
> A date is triage information; if it's there, the task goes where the
> date says.

- **On create via the API / task panel (`POST /api/tasks`):** if the
  resulting tier is **Inbox** and a due date is set → route with
  `_tier_for_due_date`. Applies whether the caller sent `inbox`
  explicitly or got it as the default, because the API can't tell those
  apart. An explicit **non-Inbox** section still wins there (existing
  rule (a), unchanged), as do Freezer and non-Active.
- **On create via reflection / scan / voice / import (decision 2):**
  **the date always wins.** Any candidate with a due date is placed by
  `_tier_for_due_date`, whatever section was proposed or picked on the
  review screen — **including Freezer** (decision 2 follow-up). A
  candidate with no date keeps its section (default Inbox).
- **On update:** route out of Inbox only when the **date actually
  changes** in this write (new non-null date ≠ old date). Consequences:
  - Pick a date on an Inbox task in the panel → it routes, even if the
    iPhone never fired `change` (fixes C server-side).
  - Deliberately move an already-dated task *into* Inbox (bulk "Inbox",
    calendar drag to the Inbox bucket, panel dropdown with the date
    untouched) → it stays in Inbox. Explicit placement wins.
- **Nightly jobs unchanged.** With the write-time rule, a dated task is
  only in Inbox because you put it there, which is exactly the "needs
  triage" case the 00:03 job already respects (D stays as designed).

## 4. Design

**Server**

1. `task_service.py`: add one public helper for the candidate paths —
   `tier_for_candidate(tier: Tier, due_date: date | None) -> Tier`
   (returns `_tier_for_due_date(due_date)` whenever `due_date` is set,
   else `tier`; decision 2 — no Inbox/Freezer special case here).
2. `_auto_promote_tier_on_due_today` gains the Inbox case: when `"tier"
   in data` and the resulting tier is Inbox and the date changed (create:
   always "changed"; update: compare against a pre-update snapshot,
   `old_due_date`, taken next to the existing `old_goal_id` snapshot at
   `:603`), route instead of returning early. All other explicit tiers
   keep the early return.
3. `scan_service.create_tasks_from_candidates` (`:1418`) and
   `import_service` (`:806`) call the helper before constructing `Task`.
   That covers reflection, scan, voice and import in two edits.
4. Also apply `_auto_fill_tier_due_date`'s symmetric rule there? **No** —
   out of scope (candidates with tier Today and no date are a separate,
   unreported gap; file it if found).

**Client** (`static/app.js`)

5. `taskDetailOpenNew`: when `prefillDue` is given, open with
   `tier: window.tierHelpers.tierForDueDate(prefillDue)` instead of
   `"inbox"`, so the dropdown shows where the task will actually go
   (the server would route it anyway — this keeps the panel honest).
6. Date input: listen to `input` as well as `change` (same handler,
   idempotent), so the dropdown tracks the iPhone picker.

No new routes, columns, jobs or static files.

## 5. Tests

**pytest**
- `POST /api/tasks` `{tier: inbox, due_date: today+3}` → natural tier;
  `{tier: inbox}` (no date) → Inbox; `{tier: this_week, due_date: +30d}`
  → This Week (explicit wins); `{tier: freezer, due_date: X}` → Freezer.
- `PATCH`: Inbox task + new date (with `tier: inbox` in the payload, as
  the panel sends) → routed; dated This Week task + `{tier: inbox,
  due_date: <same date>}` → stays Inbox; `{tier: inbox}` alone → Inbox.
- `create_tasks_from_candidates` with `source_prefix="reflection"`,
  `"voice"`, default (scan): inbox/missing tier + date → routed;
  explicit `this_week` + date next month → Backlog (date wins);
  `freezer` + date → routed (date wins over Freezer too); no date →
  proposed section kept.
- Import confirm: same three cases.
- Boundary dates reuse `_tier_for_due_date`'s existing tests (no
  duplicate week-boundary matrix).

**Jest** — `tierForDueDate` is already covered (`tier_helpers`); the
`taskDetailOpenNew` prefill decision is one call, exercised end-to-end
below rather than extracted.

**Playwright** (`tests/e2e/pages.spec.js`)
- `/calendar` empty cell 3 days out → New Task panel shows the matching
  Section → save → task is in that section, not Inbox.
- New Task panel, set the date via `fill()` + dispatch **only** `input`
  → dropdown updates; save → correct section.
- Inbox task, panel, new date, save → leaves Inbox.

**Prod smoke** — one assertion: `POST` a dated Inbox task through the
API is not possible read-only, so smoke stays page-render only; the
behaviour is covered by pytest + local Playwright (note in SOP report).

## 6. Phase 6 (desktop 1280×800 + mobile 375×812)

- New Task from the capture-bar ➕ with a date next week → lands in Next
  Week. Same with no date → Inbox (the quiet case — must not regress).
- `/calendar` empty-cell create → lands on that day's section.
- Existing Inbox task, set a date in the panel → leaves Inbox.
- Dated task moved to Inbox via the bulk toolbar → **stays** in Inbox.
- Reflection apply with a dated proposal (dev data) → not in Inbox.
- iPhone date picker: the native picker can't be driven from the
  desktop browser — flagged for **manual check on the phone** after
  deploy (CLAUDE.md "what automated testing cannot cover").

## 7. Docs + cascade

- `templates/docs.html` (user-facing → fact-check table in the review):
  - Section auto-route exceptions (`:1420-1424`): add "Inbox is never
    an explicit choice when a date arrives — a dated task always leaves
    Inbox on create, and when you change its date".
  - Excel import (`:1176`): becomes true; keep, cite the new code.
  - Scan candidates (`:1004`) and text import (`:1084`, `:1134`):
    "land in Inbox" → "land in Inbox unless they carry a due date".
  - Scan / voice / reflection / import sections: "a candidate with a due
    date is filed by its date — the Section you see on the review screen
    is used only when there is no date" (decision 2).
- CLAUDE.md Phase 6 step 6 + Regression Test Report: add
  "Tasks: dated task skips Inbox" and "Tasks: undated task stays in
  Inbox" rows (new checklist rule).
- `static/sw.js` `CACHE_VERSION` bump (app.js changed).
- ARCHITECTURE.md: no topology change (no routes/jobs/columns) → N/A,
  but re-check the "auto-route" wording in Components if present.
- ADR: not needed (no auth/security surface).

## 8. Decisions (user, 2026-10-05)

1. **Update rule:** route out of Inbox **only when the date changes**.
   A deliberate move of a dated task into Inbox is respected.
2. **AI / import paths:** **the date always wins** over a proposed or
   review-screen section. (I had recommended keeping the proposed
   section; the user chose consistency with the date.)
   - Follow-up: **date wins over Freezer too** on these paths. (I had
     recommended keeping Freezer.) Freezer stays protected on the API /
     panel and in the nightly jobs — only the candidate paths change.
3. **Panel same-save:** accepted — changing a date while the dropdown
   says Inbox leaves Inbox; keeping a dated task in Inbox is a separate
   second step.
4. **Overdue dates** (gap found by the cascade audit after the first
   build — `_tier_for_due_date` maps a past date to This Week / Backlog):
   on the #386 paths (dated candidate; Inbox task getting a date) an
   **overdue date files to Today**, matching #170's "keep the nag
   visible". Implemented as `task_service._tier_for_filed_date` +
   `tier_helpers.tierForFiledDate` (Jest-tested). Non-Inbox tiers keep
   #74's mapping unchanged.

**Consequence to file as a follow-up row:** the import / voice / scan /
reflection review screens still show the proposed Section dropdown, so a
row reading "This Week" with a date next month will land in Backlog. The
Help page will say so (§7); syncing those dropdowns live is a separate
UI change.

## 9. Out of scope (file separately if wanted)

- Changing the 00:02 / 00:03 jobs' Inbox exclusion.
- `_auto_fill_tier_due_date` (section → date) on the candidate paths.
- Reflection prompt changes to make the model propose sections.
- Any data cleanup (prod has 0 dated Inbox tasks).
