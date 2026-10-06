# Spec #390 — review screens show the section a dated row will really get

**Filed:** 2026-10-05 by #386 (decision 2: on reflection / scan / voice /
import the due date always wins, Freezer included; overdue → Today)
**Status:** approved to build 2026-10-06 (user picked #390); no open decisions
**Frontend only.** No server change — #386 already files dated rows by date.

---

## 1. Which screens are actually affected

| Screen | Section control? | Date control? | Affected |
|---|---|---|---|
| Voice memo review (`static/voice_memo.js` `renderCandidate`, ~472-503) | yes, `.voice-candidate-tier` | yes | **yes** |
| Import preview, tasks mode (`static/import.js` ~644-663; OneNote paste, Excel, transcript, file upload all land here) | yes, labelled "Tier" | yes | **yes** |
| Scan review (`static/scan.js` `renderCandidates`) | no | no | no — OCR candidates carry neither |
| Reflection proposal list (`static/reflection.js` `renderActionRow`) | no | no | no — a create proposal has `changes: []` (`reflection_service.py:976`), so the row shows only "Create task: X" + reason |

The backlog row listed all four; the code shows only two can mislead.

## 2. Behaviour

On both screens, per task row:

- **Row has a due date** → the Section dropdown shows the section that
  date files to (same rule as the server: overdue or today → Today,
  tomorrow → Tomorrow, this week → This Week, next week → Next Week,
  later → Backlog), is **disabled**, and a short muted hint beside it
  reads **"Set by due date"** (also its `title`, and wired with
  `aria-describedby` so a screen reader hears why it's disabled).
- **Date is changed** → the dropdown follows immediately (`input` event,
  like the task panel's #386 fix).
- **Date is cleared** → the dropdown is enabled again and shows the
  section the row had before (the user's / model's choice is kept, never
  overwritten by the date).
- **Row has no date** → unchanged from today.

The submitted payload is unchanged (it still carries the row's own
`tier`); the server's `tier_for_candidate` decides for dated rows, so the
screen and the result now agree by construction.

## 3. Design

- `static/tier_helpers.js`: one pure, Jest-tested helper
  `candidateSection(tier, dueDate)` → `{ tier, setByDate }` — returns
  `tierForFiledDate(dueDate)` + `setByDate: true` when the date parses,
  else the given tier + `false`. Mirrors `task_service.tier_for_candidate`.
  `base.html` already loads `tier_helpers.js` on every page.
- Each screen gets a small local `sync…Section()` that applies the helper
  to its dropdown + hint, called on render and on the date input's
  `input` event. No shared DOM helper (two call sites, different markup).
- Global-scope rule (#359 / the #386 lesson): no new top-level names
  outside the IIFEs; the helper is reached via `window.tierHelpers`.

## 4. Tests

- **Jest** (`tests/js/unit/tier_helpers.test.js`): dated → filed section
  + `setByDate`; overdue → today; Freezer + date → date section; no date /
  unparseable → own tier + `false`.
- **Playwright** (`tests/e2e/pages.spec.js`), both viewports:
  - Import: stub `POST /api/import/tasks/parse` with one dated and one
    undated candidate → the dated row's dropdown is disabled, shows the
    filed section and the hint; clearing its date re-enables it with the
    original section; the undated row is untouched.
  - Voice memo: stub `getUserMedia` / `MediaRecorder` with an init script
    and `POST /api/voice-memo` with candidates → same assertions.

## 5. Docs / cascade

- `templates/docs.html`: voice-memo bullet and the "Sections and
  auto-fill" candidate paragraph — say the review screen now *shows* the
  date's section, locked, and that clearing the date unlocks it (fact-check
  table in the review).
- `CLAUDE.md` Phase 6: step 10 (Import) + a voice-memo line, and report
  rows.
- `static/sw.js` `CACHE_VERSION` bump (three static JS files change).
- No ARCHITECTURE change (no routes / jobs / columns / files).

## 6. Out of scope

- Showing section/date on reflection create proposals (they show neither
  today — a separate enhancement if wanted).
- Renaming the import screen's "Tier" label to "Section".
- The board's inbox auto-categorize modal (an update path where an
  explicit non-Inbox section still wins by #74 — not a candidate path).
