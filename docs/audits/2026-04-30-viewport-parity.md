# Viewport Parity Audit — Inventory (Phase A)

**Backlog item:** #138
**Filed:** 2026-04-30
**Status:** Phase A inventory shipped (PR75). Phases B–F open.

## Purpose

Phase 6 SOP mandates desktop 1280×800 + mobile 375×812 regression on
every UI change, but each Phase 6 only exercises the changed surface.
This audit cross-cuts by **viewport** — every page × every interaction
is exercised at both widths so we catch desktop-only paths and
mobile-broken interactions that no targeted Phase 6 ever ran.

## How to use this file

For each `(page, interaction)` row:

1. Run the desktop walk (`1280×800`). Mark the cell `PASS` /
   `FAIL: <one-line summary>` / `SKIP: <reason>`.
2. Run the mobile walk (`375×812`). Mark the cell similarly.
3. If FAIL, classify in Phase D:
   - `(a) bug` — file as new BACKLOG row + write a Playwright
     regression. Link the new row to this audit.
   - `(b) deliberate desktop-only` — document the carve-out in
     `templates/docs.html` Help.
   - `(c) needs new feature` — file as BACKLOG row.

**Acceptance per cell** (must hold at both viewports):

- Functional behaviour identical (same final DB state on save)
- Touch targets ≥ 44×44px
- No horizontal overflow
- Truncated text has `title=` fallback
- Modals / dropdowns dismissible by tap-outside
- Drag works on touch (HTML5 DnD + Pointer Events)
- Voice button reachable
- iOS Safari standalone PWA path renders without keyboard /
  address-bar overlap
- No console errors

## Setup

Per CLAUDE.md Phase 6:

```
python scripts/seed_dev_data.py
preview_start taskmanager-dev-bypass
# load with ?nosw=1 to prevent SW reload loops in headless browser
```

**Gap callout — `?nosw=1` masks SW + CSP differences from prod**
(per CLAUDE.md Phase 6 limitation, Bug #55). After Phases B+C complete,
add a final no-bypass real-prod walk on `/voice-memo` + `/architecture`
+ any page that loads CDN scripts to catch SW + CSP regressions the
bypass would mask.

## Pages inventory

Confirmed against `app.url_map` and `templates/base.html` nav on
2026-04-30 (HEAD = `14ebb6a`).

### Top-level rendered routes (12)

| # | Path | Endpoint | Notes |
|---|---|---|---|
| 1 | `/` | `index` | Main board (all 7 tiers + capture bar + filters) |
| 2 | `/goals` | `goals_page` | Goals list + filters + new-goal modal |
| 3 | `/projects` | `projects_page` | Projects list + bulk-edit toolbar (#73) |
| 4 | `/calendar` | `calendar_page` | 2-week Mon-Sat grid + drag-to-day (#73) |
| 5 | `/recurring` | `recurring_page` | Templates list + multi-select bulk toolbar (#63) |
| 6 | `/import` | `import_page` | OneNote / Excel / Outlook ICS import |
| 7 | `/scan` | `scan_page` | Image OCR → tasks |
| 8 | `/voice-memo` | `voice_memo_page` | Record → Whisper → Claude → review |
| 9 | `/review` | `review_page` | Stale-task triage (Keep / Freeze / Snooze) |
| 10 | `/completed` | `completed_page` | Completed + cancelled history (PR ?) |
| 11 | `/recycle-bin` | `recycle_bin_page` | Soft-deleted batches (Empty Bin) |
| 12 | `/settings` | `settings_page` | Stats + digest config + admin actions |
| 13 | `/docs` | `docs_page` | Help / user-facing docs |
| 14 | `/architecture` | `architecture_page` | ARCH.md + ER + Mermaid diagrams (#42) |
| 15 | `/print` | `print_page` | Printable tier list |

### Per-tier detail subpages (7)

`/tier/<name>` renders a single tier's tasks. Each is a separate cell
in this audit because navigation, list rendering, and the tier-banner
treatment can diverge across tiers (e.g. INBOX has a "triage" affordance
the other tiers don't).

| # | Path | Tier |
|---|---|---|
| 16 | `/tier/inbox` | INBOX |
| 17 | `/tier/today` | TODAY |
| 18 | `/tier/tomorrow` | TOMORROW |
| 19 | `/tier/this_week` | THIS_WEEK |
| 20 | `/tier/next_week` | NEXT_WEEK |
| 21 | `/tier/backlog` | BACKLOG |
| 22 | `/tier/freezer` | FREEZER |

**22 total page cells per viewport (44 cells across both viewports).**

## Interactions inventory

Each interaction runs against the most-relevant page (column 2). The
same interaction may need to be exercised on multiple pages if it
behaves differently — those are listed as separate rows.

### Capture / create flows

| # | Page | Interaction | Notes |
|---|---|---|---|
| C1 | `/` | Capture bar: type a title → Enter → task lands in correct tier | Default tier per `parse_capture.js` |
| C2 | `/` | Capture bar: hashtag parser (`#today`, `#tomorrow`, `#work`, `#personal`, `#proj`, `#goal`) | One per known hashtag rule |
| C3 | `/` | Capture bar: 🎤 voice button → SpeechRecognition → text appears | Permission denied + unavailable fallback (#116) |
| C4 | `/voice-memo` | Record → stop → Whisper → review UI shows candidates | Permission denied path |
| C5 | `/voice-memo` | Per-candidate edit: title, type, tier, due_date, project, goal | Sub-PR A cascade (#137) |
| C6 | `/voice-memo` | Confirm selected candidates → tasks created | Confirms only checked rows |
| C7 | `/scan` | Upload image → OCR → review candidates → confirm | Mobile camera capture path |
| C8 | `/import` | OneNote text paste → preview → edit → confirm | Excel + ICS variants |

### Task detail panel (modal)

The panel is reusable across all task-listing pages (`/`, `/tier/*`,
`/completed`, search results). Test fields once, but verify the panel
opens correctly from each surface.

| # | Page | Interaction | Notes |
|---|---|---|---|
| D1 | `/` | Click task → panel opens centered, scroll-locked behind | Tap-outside closes (PR ?) |
| D2 | `/` | Title field: edit + save → persists on reload | |
| D3 | `/` | Tier dropdown: change → tier auto-fills due_date when relevant (#94) | |
| D4 | `/` | Type radio (work/personal): change → project list filters (#117) | |
| D5 | `/` | Project picker: pick → goal cascades (#117 / matches Sub-PR A) | Bug #57 silent payload drop is the regression class |
| D6 | `/` | Goal picker: pick → save → persists | |
| D7 | `/` | Due date: native `<input type="date">` → mobile wheel picker | |
| D8 | `/` | URL field: paste → save → click chip on card opens link | |
| D9 | `/` | Notes textarea: 🎤 voice button per row (#116) | |
| D10 | `/` | Checklist: add row, edit, check, delete | Per-row 🎤 (#120) |
| D11 | `/` | Subtasks: parent picker + `+ Subtask` button (#120) | Subtask cards rendered |
| D12 | `/` | Repeat dropdown: select Weekly → day picker appears | Daily / Weekdays / Multi-day-of-week / Monthly date / Monthly nth weekday / Stop-after end_date input (#101) |
| D13 | `/` | Save → panel closes → card updates without reload | |
| D14 | `/` | Cancel → panel closes → no DB write | |
| D15 | `/completed` | Reopen dropdown → all 7 active tiers selectable (#110) | |

### Tier movement / priority

| # | Page | Interaction | Notes |
|---|---|---|---|
| T1 | `/` | Tier button on card (Done / Tomorrow / Week / Backlog) → moves task | |
| T2 | `/` | Drag card between tier panels (HTML5 DnD on desktop, Pointer Events on mobile) | Touch-drag is the high-risk cell |
| T3 | `/` | Day-strip drag: drop on a day → sets due_date | |
| T4 | `/calendar` | Drag task between calendar days → sets due_date (PR51 #114) | |
| T5 | `/calendar` | Drag from "Unscheduled" panel onto a day | Drag back to clear (#94) |
| T6 | `/projects` | Project priority drag-reorder | |

### Filters / search / multi-select

| # | Page | Interaction | Notes |
|---|---|---|---|
| F1 | `/` | Search bar: type → cards filter live (#107) | |
| F2 | `/` | Project filter chip row: click chip → filters (PR66 batch_id?) | |
| F3 | `/` | Goal filter chip row: click chip → filters | |
| F4 | `/` | Type filter (work / personal toggle) | |
| F5 | `/` | Multi-select: shift-click / long-press → bulk-edit toolbar appears | Pending-changes panel staging (PR ?) |
| F6 | `/` | Bulk apply → all selected tasks update in one PATCH | |
| F7 | `/goals` | Filter by category / priority / status | |
| F8 | `/projects` | Bulk-edit toolbar: type / status / archive | (#73) |
| F9 | `/recurring` | Multi-select + bulk patch: type / frequency / project / goal / active / delete | (#63) |

### Review / weekly triage

| # | Page | Interaction | Notes |
|---|---|---|---|
| R1 | `/review` | Card displays → Keep / Freeze / Snooze buttons advance | |
| R2 | `/review` | Progress counter updates | |
| R3 | `/review` | Empty-state message when queue clears | |

### System / cross-cutting

| # | Page | Interaction | Notes |
|---|---|---|---|
| S1 | All | Top nav: every link reachable + `active_page` highlights correctly | |
| S2 | All | "Network reconnect" prompt fires on offline → recovers (PR58 #115/#118) | |
| S3 | `/` + `/calendar` | visibilitychange refresh on tab return (PR44/PR51) | |
| S4 | All | Console: 0 errors at load | |
| S5 | All | No horizontal overflow at 375×812 | |
| S6 | All | Touch targets ≥ 44×44px on mobile | |
| S7 | `/recycle-bin` | Batch entries display + Empty Bin button | |
| S8 | `/print` | Tier grouping renders → `window.print` looks correct | |
| S9 | `/architecture` | Mermaid sequence diagrams render under SW (NOT bypass-only) | Bug #55 class — MUST verify post-deploy without `?nosw=1` |
| S10 | `/architecture` | ER + per-table cards (#42 / #43 / #44) render | |
| S11 | `/settings` | Stats reflect seeded data; digest config form | |

**~50 interactions × 2 viewports = ~100 cells.** Total audit surface
(pages + interactions × viewports) ≈ 144 cells.

## Walk recording template

Use this template per page during Phase B / C. Copy into a new
markdown sub-section per page-walk session.

```
### Page: <path>  (viewport: 1280×800 | 375×812)

Date: 2026-MM-DD
Tester: <name or "Claude Preview headless">
Console errors at load: <count>

| Cell | Result | Notes / screenshot ref |
|---|---|---|
| C1 | PASS | |
| C2 | PASS | |
| ... | ... | |

Defects filed:
- (a) bug → BACKLOG #<new>, regression test in tests/e2e/
- (b) carve-out → docs.html updated
- (c) feature → BACKLOG #<new>
```

## Phase D classification template

After both walks, summarize per-defect:

```
### Defect <N>

- Cell(s): <interaction id> @ <viewport>
- Symptom: <one line>
- Class: (a) bug | (b) deliberate carve-out | (c) needs new feature
- Action: <BACKLOG # or docs.html section>
- Regression test: <file:test_name or N/A>
```

## Phase F process change

After F, add a "Viewport parity" row to the Regression Test Report
template in `CLAUDE.md` so future single-feature Phase 6 cycles default
to checking the parity rule on the changed page. Consider a
`tests/e2e-mobile/` Playwright project that re-runs the existing
local suite at 375×812 — file as a separate BACKLOG row if scope grows.

---

**Sub-PR breakdown (per backlog row):**

- **Phase A** (this PR): inventory file ← no-code, reviewable
- **Phase B**: desktop walk (~1.5h) — separate PR with walk results
  appended below
- **Phase C**: mobile walk (~1.5h) — separate PR
- **Phase D**: gap analysis + new BACKLOG rows (~30 min)
- **Phase E**: quick-win fixes inline (XS/S items, ~1-2h)
- **Phase F**: process change to CLAUDE.md (~30 min)

## Phone-sandbox scoping confirmations (2026-04-30)

Per the backlog row's "desktop session please double-check" notes:

- **(a) Page list confirmed** against live `app.url_map` and
  `templates/base.html` nav. Found:
  - 15 top-level rendered routes (added `/recycle-bin` and `/login` —
    excluded `/login` since it's not part of the user-facing audit)
  - 7 tier sub-pages
  - 22 page cells total (matches the row's "16" estimate broadly;
    discrepancy is the per-tier expansion which the row noted as
    valid). No new pages have shipped between scoping and Phase A.
- **(b) Interaction list** drafted from current `templates/_task_detail_panel.html`
  + bulk-toolbar partials + `static/app.js` event listener attachments.
  Cross-checked against the per-PR BACKLOG history for completeness.
  Open: nav-link inventory (S1) — verify all nav links once during
  Phase B.
- **(c) Dev-bypass sanity check**: deferred to Phase B start. Run
  `python scripts/seed_dev_data.py` then `preview_start
  taskmanager-dev-bypass` and confirm `?nosw=1` loads `/` without
  console errors before starting Phase B walks.
- **(d) SW + CSP regression check** (Bug #55 class): captured as cell
  S9 with explicit "MUST verify post-deploy without `?nosw=1`" note.
- **(e) Phase D defect linkage**: captured in the classification
  template above ("BACKLOG #<new>" placeholder).
- **(f) Pre/post-PR gates**: this PR ships under
  `bash scripts/run_all_gates.sh` clean. Phase E PRs will too.
