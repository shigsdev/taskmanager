# #473 — A deploy reload no longer wipes the review screens

Filed 2026-10-14 by the #446 spec. Checked 2026-10-16 against
`templates/base.html` `userIsBusy()`, `static/scan.js`, `static/import.js`,
`static/plan.js` and `static/reflection.js`.

## What was wrong

base.html polls for a new service worker every 60s and applies it — which
reloads the page — unless `userIsBusy()` objects. It objects to a focused
field, any open panel / pop-up (#446) and live audio (#331,
`window.__mediaCaptureBusy`). Four review steps are part of the page, not an
overlay, so once you click away from a field a deploy reload throws them
away:

| Page | What is lost | Cost |
|---|---|---|
| /scan | the candidate review (and an upload still being read) | Vision + Claude call |
| /import | the parsed preview and the confirm summary (and a parse still running) | Claude call (paste / docx / transcript); Excel is free but edits are lost |
| /plan | the suggestions you haven't accepted or ignored yet (and a plan still being made) | Claude call |
| /reflection | the proposal review (and an analysis still running) | Claude call |

Checked for /reflection: the proposals ARE saved on the reflection, but
nothing re-opens them — History only offers "↻ Re-analyze", which is a
second paid call. So a reload does lose them (filed as #495 below).

## This ship

- New `static/reload_guard_helpers.js` (dual export, loaded in base.html's
  head): `createReloadGuard()` → `{ add(fn), during(promise), busy() }`.
  `add` registers a "something on screen would be lost" check; `during`
  marks a request in flight until it settles (either way); `busy()` is true
  while any request is in flight or any check says so. A check that throws
  is skipped (never blocks forever, never breaks the updater).
  `window.reloadGuard` is the page's one guard.
- `userIsBusy()` also asks `window.reloadGuard.busy()`.
- /scan: busy while the upload is in flight or the review is showing.
- /import: busy while any Parse is in flight, or the review / confirm
  summary is showing.
- /plan: busy while the plan is being made, or while the suggestions are
  showing with at least one row still pending (`planHelpers.hasPendingRows`).
  Once every row is accepted or ignored there is nothing left to lose.
- /reflection: busy while analyzing or on the review.
- The "Update available" banner still shows in every case, so you choose
  when to take the new version (same as #331 / #446).

The quiet cases: each page on its first screen, a finished scan / import
(done screen), a plan whose rows are all decided, and a reflection that has
been applied are not busy.

## Out of scope — filed

- #495: a reflection's saved proposals can only be reached again by
  re-analyzing (a paid call). Add a "Review proposals" button on History
  that opens the saved `proposed_actions` without calling Claude.
