# #446 — A deploy reload can wipe an open review or panel

Filed by the deep review (§B9).

## What happens

`base.html` polls for a new service worker every 60 s (and on focus). When
one has installed, it asks `userIsBusy()`: busy → show the "Update
available" banner and let the user choose; not busy → `SKIP_WAITING`, and
`controllerchange` reloads the page. (`sw.js` never calls `skipWaiting()` on
its own, so this is the only gate.)

`userIsBusy()` knows three things: a focused input / textarea / select /
contenteditable, the **task** panel (`#detailOverlay`) open, and a live
recording (`window.__mediaCaptureBusy`, #331). Anything else open with no
focused field is reloaded away — after a click on a checkbox, a button or a
`<select>` that has since closed, focus is not in a text field:

- the goal panel, the project panel, the /recurring editor (`.detail-overlay`
  but not `#detailOverlay`);
- the board's ✨ Plan review and 💡 Auto-categorize review — each the answer
  to a paid Claude call;
- the /recycle-bin Empty Bin confirm, /reflection's focus picker, the voice
  memo's Make-recurring dialog, Strength Forge's how-to, log form and print
  sheet.

## Change

`panel_keys.js` already lists every one of these (its `OVERLAY_SELECTOR`,
#381 / #406 / #417) and finds the open ones for Escape. Reuse it:

- New `panelKeys.anyOpen(doc, win)` → true when any listed overlay's
  computed `display` isn't `none`.
- `userIsBusy()` asks `window.panelKeys.anyOpen(document, window)`, keeping
  the old `#detailOverlay` check as the fallback if `panel_keys.js` didn't
  load.

The banner path is unchanged: busy at the moment the update is ready → the
banner, and the user clicks it when they're done. Nothing is persisted.

The risk is the other way round: an overlay that reads "open" while closed
would keep the banner up forever and strand the user on old code. So the
quiet case is tested on every page: idle → not busy.

## Help

Troubleshooting → a "How updates arrive" bullet (checks every minute and on
return, reloads unless typing / a panel or pop-up is open / recording, then the
"New version available · Tap to refresh" bar). The old "applies on the next
launch" line was wrong; the reflection bullet named the bar "Update available".

## Out of scope (filed)

- **#473** — the in-page review screens that follow a paid call are not
  overlays and are still reloaded away: /scan's candidate review, /import's
  parsed preview, /plan's suggestions, /reflection's proposal review (voice
  memo's review is already covered by #331). Each needs its page to publish
  a busy state, as voice memo does.

## Tests

- Jest (`panel_keys.test.js`): `anyOpen` false with nothing open, true for a
  side panel and for each of the eight modals, false again once closed.
- Playwright: on every page, idle → `__userIsBusy()` false (the quiet case);
  open the goal panel, project panel, recurring editor, ✨ Plan, 💡
  Auto-categorize, recycle-bin confirm and a Strength Forge pop-up with focus
  moved off any field → true; close → false. Red on the old code for every
  overlay except the task panel.
