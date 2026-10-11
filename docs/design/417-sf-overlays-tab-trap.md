# #417 — Strength Forge's three pop-ups keep Tab inside

Filed 2026-10-11 by the #406 spec §5. Strength Forge (`static/strength_forge.js`)
builds three overlays in JS. Each closes on Escape through its own document
`keydown` handler, but none traps Tab, so Tab walks to the page behind.

## 1. Surface

| Overlay | Opens from | Close controls | Hidden by | z-index | Lost on close |
|---|---|---|---|---|---|
| Exercise how-to `.sf-modal-overlay` | ℹ️ on any exercise row | ✕ `.sf-modal-close`, backdrop | `[hidden]` | 1000 | nothing |
| Log form `.sf-logform-overlay` | "Log details" on a plan | ✕ (head), Close `.sf-logform-cancel`, backdrop | `[hidden]` | 1000 | nothing: the on-device draft autosaves on a 400ms debounce that still fires after the form hides |
| Print sheet `.sf-print-overlay` | 🖨 Print buttons | ✕ Close `.sf-print-close`, backdrop | removed from the DOM | 1200 | nothing |

They can't stack: the log form's exercise blocks don't open the how-to
modal, and the print sheet opens only from page buttons.

## 2. This ship

1. Add the three classes to `panel_keys.js` `OVERLAY_SELECTOR`. Tab and
   Shift+Tab then stay inside. `[hidden]` already computes to
   `display: none`, so open detection works unchanged.
2. Mark each overlay's first close control `data-panel-close` (the head ✕
   for the modal and the log form, ✕ Close for the print sheet). Escape then
   runs that control's own close path.
3. **Remove Strength Forge's three Escape handlers.** One keypress must be
   handled once, in one place. Behaviour is unchanged: Escape still closes
   each one, now through `panel_keys.js`.
4. Tests:
   - Jest: the three classes join the #406 per-class `test.each`.
   - Playwright, desktop + mobile: each overlay traps Tab and closes on
     Escape. The log form keeps a typed rep through Escape + reopen (draft
     intact). The print sheet's Escape removes the `sf-print-active` body
     class (print mode off).
5. Help: the #406 paragraph's dialog list names the Strength Forge pop-ups.
   CLAUDE.md: the #406 Phase 6 line names them too.

## 3. Out of scope

Focus moving in on open and back on close stays with **#419**. Its row is
widened to include these three.
