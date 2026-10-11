# #406 — Escape and a Tab trap for the five non-panel modals

Filed 2026-10-10 by the #381 spec §5. #381 gave the four `.detail-overlay` side
panels Escape-to-close and a Tab trap through `static/panel_keys.js`, which is
loaded on every page from `base.html`. Five modals use other markup and still
ignore Escape and let Tab walk to the page behind.

## 1. Surface (every modal/overlay, swept 2026-10-11)

| Modal | Page | Markup | Closes today via | z-index | State lost on close |
|---|---|---|---|---|---|
| Recycle Restore/Purge/Empty confirm `#recycleModalOverlay` (`.modal-overlay`) | /recycle-bin | template | Cancel (no ✕, no backdrop) | 1000 | none (type-DELETE box) |
| ✨ Next Week's Focus picker `#reflFocusModal` | /reflection | template | ✕, Cancel, backdrop | 200 | none (choices rebuilt each open) |
| ✨ Plan review `#weeklyFocusPlanModal` | board | template | ✕, Cancel, backdrop | 200 | Claude's suggestions |
| 💡 Auto-categorize review `#autoCategorizeModal` | board | template | ✕, Cancel, backdrop | 1000 | Claude's suggestions + any row overrides |
| Voice memo "Make recurring" `.voice-recur-overlay` | /voice-memo | built in JS, removed on close | Cancel, backdrop | 250 | the form's edits |

Not in scope, already handled:
- `/architecture`'s `<dialog id="diagramZoom">` is native, so the browser handles Escape (#405).
- The three Strength Forge overlays (`.sf-modal-overlay`, `.sf-print-overlay`, `.sf-logform-overlay`) already close on Escape with their own handlers. They have no Tab trap; see §5.

## 2. Decision: Escape = the modal's own Cancel / ✕

**Escape does exactly what ✕ or Cancel does in every one, including
discarding Claude's plan suggestions and auto-categorize overrides.** That's
#381's rule for the panels ("discards unsaved edits exactly as ✕ and a
backdrop click do"), and for these four a backdrop click already discards
them. A native `<select>` or date picker that is open consumes the Escape
itself, so closing a dropdown inside the table doesn't close the modal.

## 3. This ship

1. **`panel_keys.js` covers the five.** `OVERLAY_SELECTOR` adds
   `.modal-overlay`, `.reflection-focus-modal`, `.weekly-focus-plan-modal`,
   `.auto-categorize-modal` and `.voice-recur-overlay`. "Open" is the same
   computed `display !== "none"` test, and the voice overlay only exists
   while open.
2. **`topOverlay` picks by z-index, then DOM order.** The new set spans
   z-index 200 to 1000, so DOM order alone could hand Escape to a panel
   underneath a modal. Jest-tested.
3. **Each modal's close control gets `data-panel-close`**, so Escape runs its
   own close path: recycle Cancel, `#reflFocusClose`, `#weeklyFocusPlanClose`,
   `#autoCategorizeClose`, and the voice dialog's Cancel.
4. **Tests.**
   - Jest: z-index ordering, plus `handleKey` on a modal-shaped DOM
     (Escape clicks its `[data-panel-close]`; Tab wraps inside).
   - Playwright, one per modal (stubbing Claude/voice responses as the
     existing #390 / auto-categorize / reflection tests do): open it,
     Tab from outside lands inside, Shift+Tab from the first control wraps
     to the last, Escape closes it, and the page is still usable.
5. CLAUDE.md Phase 6 checklist line + report rows. Help copy: the
   keyboard section from #381 lists what Escape closes; extend it.

## 4. Not changed

Focus moving INTO a modal on open, and back to the button that opened it
on close: see §5.

## 5. Out of scope (filed)

- **#417** — Strength Forge's three overlays close on Escape but have no
  Tab trap and no focus handling. Their Escape handlers are their own, so
  folding them into `panel_keys.js` means removing those handlers too.
- **#418** — the ✨ Plan modal has no guard against a stale response
  (`weekly_focus.js` `_runPlan`). Close it mid-request (✕ today, Escape
  after this) and open another plan, and the first request's answer can
  overwrite the second's. Pre-existing.
- **#419** — focus in and back for these five modals, the #377 treatment
  the side panels got: focus moves into the modal on open and returns to
  the button that opened it on close. Today, closing leaves focus on the
  page body.
