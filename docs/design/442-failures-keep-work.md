# #442 — Failures that throw away work: voice memo, Strength Forge

Deep review 2026-10-11 §B8.

## Surface (mapped 2026-10-13)

| Where | Today |
|---|---|
| `voice_memo.js` `uploadAndProcess` | A failed upload shows the error screen; the blob (up to 10 min) is dropped. Its only button, Try Again, starts a new recording. The SW may auto-reload on the error screen (busy flag is only set while recording / processing). |
| `voice_memo.js` `confirmCandidates` | A failed Add All / Add Selected switches to the error screen. The reviewed list (routes, categories, repeats, edits) is gone. |
| `strength_forge.js` `logWorkout` (quick ✓ Log) | Failure re-enables the button, says nothing. |
| `delSession` (the log's ↶ Undo) | Failure says nothing; the log stays listed as if Undo did nothing. |
| `saveLogForm` (full log form) | Failure re-enables Save, says nothing. Entries survive (form stays open + on-device draft) but the user can't tell it didn't save. |
| `startFlare` / `setFlarePhaseTracked` / `endFlare` | Failures say nothing; a phase change shows no change. |

## Fix

- `api_helpers.actionFailureMessage(what, err, bulk, tail)`: optional `tail`
  replaces "The page now shows what's saved." where that isn't what happens.
- **Voice upload:** keep the recording (chunks + type) until an upload
  succeeds or a new recording starts. The error screen gets **Upload again**
  (resends the same audio), shown only while a recording is kept; Try Again
  still records a new one. The message says the recording is kept. The SW
  auto-reload stays blocked while a recording is kept.
- **Voice confirm:** stay on the review screen; the list and every edit stay.
  A message above the buttons says it didn't add and, because the server
  creates tasks / goals / projects in separate steps, to check the Inbox
  before adding again. Cleared on the next try.
- **Strength Forge:** each write says so on failure (alert, as #430 does on
  the board) and re-reads the server's state: quick log / Undo reload the
  log; flare start / phase / end reload the flare. The log form's message
  says the entries are still in the form.

## Out of scope (filed)

- **#470** — voice Confirm isn't all-or-nothing: `voice_api.confirm` creates
  tasks, recurring templates, goals and projects in separate commits, so a
  failure part-way leaves some added and a retry can duplicate them.

## Tests

- Jest: `actionFailureMessage` with `tail`.
- Playwright: upload 500 → message + Upload again → stub OK → review (one
  recording, two uploads); confirm 500 → still on review, rows + edit kept,
  message shown → Add All again succeeds; Strength Forge quick log, Undo,
  log form Save and flare start each say so on a 500 (dialog text).
