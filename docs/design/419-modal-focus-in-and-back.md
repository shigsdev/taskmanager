# #419 — The pop-up dialogs move focus in when they open and back when they close

Found 2026-10-11 by the #406 spec §5.

## What was wrong

#406 and #417 gave the eight pop-up dialogs (Recycle Bin confirm, the
reflection focus picker, ✨ Plan, 💡 Auto-categorize, voice memo Make
recurring, and Strength Forge's how-to, log form and print sheet) Escape and
a Tab trap. The side panels also got #377 / #454's focus handling: into the
panel on open, back to whatever opened it on close. The dialogs didn't. After
a keyboard open, focus stayed on the page behind; after a close it dropped to
the page body, so a keyboard user started over from the top.

## Decision: one watcher, not eight wirings

Each dialog shows and hides its own way: `style.display` (recycle, focus
picker, Plan, Auto-categorize), the `hidden` attribute (Strength Forge
how-to, log form), or a node built on open and removed on close (voice Make
recurring, print sheet). Each also has several close paths (✕, Cancel,
Escape, backdrop, Apply, Save). Wiring each one would be about 30 call sites,
and any close path that gets missed fails silently.

`panelKeys.watchModals` (`static/panel_keys.js`) uses a MutationObserver
on `style` / `class` / `hidden` plus childList. It watches the same overlay
list Escape uses, minus `.detail-overlay`: the side panels keep their own
#377 / #454 code. The open state is the computed display, as for Escape.

- **Open.** Remember the opener and focus the dialog's `[data-panel-close]`
  control, unless the dialog's own code already put focus inside it (the
  recycle confirm's type-DELETE box). The opener is:
  - whatever had focus just before (newest first, skipping the dialog
    itself);
  - never a text field, because refocusing one pops the phone keyboard
    (#454's rule);
  - if focus is on the page body, a control that was just disabled or
    marked `aria-busy`. #429's `withInflight` disables 💡 and ✨ while their
    request runs, and Chrome drops focus from a disabled control to the
    page, sometimes before the watcher looks;
  - otherwise nothing. Safari doesn't focus a clicked button, and handing
    focus back to some older element would scroll the page to it.
- **Close** (hidden, or removed). Hand focus back to the opener, unless the
  dialog's own close already sent focus somewhere live outside it. With
  nothing to hand back, don't leave focus on a hidden control.
- A dialog already open when watching starts is left alone. Stacked dialogs
  (the log form's ℹ️ how-to on top of the log form) each hand back to their
  own opener.
- Mouse and tap opens: a script-moved focus shows a ring only after keyboard
  use (`:focus-visible`), as in #377.

## This ship

- `watchModals` in `panel_keys.js`, started on load next to `attachPanelKeys`.
- Help → Keyboard in panels: one sentence.
- CACHE_VERSION bump.

## Tests

- `tests/js/unit/modal_focus.test.js` (jsdom), red before the fix: all
  eight selectors, the `hidden` attribute, a built-and-removed dialog, a
  dialog that focuses its own field, opened from a text field, opened with
  focus on the page body, a disabled opener, focus the dialog's own close
  sent elsewhere, stacked dialogs, side panels ignored, already open at load.
- `tests/e2e/modal_focus.spec.js`, red before the fix, at both viewports:
  the Strength Forge how-to by keyboard and by mouse (no ring), the
  recycle confirm (its own box keeps focus), 💡 Auto-categorize (the
  disabled-opener case), and voice Make recurring (a removed node).
