# Spec #374 — pause confirms say "It resumes" for one repeating task

Status: building (2026-10-10).

## 1. The bug

All three "this will pause…" confirms already pick the noun by count
("1 repeating task" / "2 repeating tasks"), but close with a fixed plural:

| Confirm | Builder | Closing sentence |
|---|---|---|
| /projects archive (#353) | `static/project_archive_helpers.js` `archiveConfirmMessage`, default `TAIL` (:25) | "They resume when you unarchive the project." |
| /goals archive (#368) | `static/goal_archive_helpers.js` `goalArchivePauseMessage` (:186) | "They resume when you unarchive the goal." |
| /settings import Undo (#369) | `static/settings.js` `UNDO_PAUSE_TAIL` (:197), passed as `tail` to `archiveConfirmMessage` | "They resume if you restore this import from the Recycle Bin." |

So n=1 reads `This will pause 1 repeating task: "Daily standup notes". They resume…`.
The current Jest cases (`project_archive_helpers.test.js:58,78,89,95,98`,
`goal_archive_helpers.test.js:282`) and the three e2e tests
(`pages.spec.js:5805,6011,6153`) assert that wrong n=1 text.

## 2. Behaviour

- n = 1 → "It resumes when you unarchive the project." / "…the goal." /
  "It resumes if you restore this import from the Recycle Bin."
- n ≥ 2 → unchanged ("They resume …").
- n = 0 / not an array → still `""` (no dialog — the quiet case).

## 3. Implementation

- `archiveConfirmMessage(paused, tail)`: `tail` becomes a `{one, many}` pair
  (the default is the project pair). A missing or malformed `tail` falls back
  to the project pair, as an empty string does today. Plain strings are no
  longer accepted — the only caller passing one is settings.js, changed in
  the same commit.
- `goalArchivePauseMessage(paused)`: picks `one` / `many` the same way.
- `settings.js`: `UNDO_PAUSE_TAIL = {one: "It resumes …", many: "They resume …"}`.

## 4. Tests

- Jest: every n=1 expectation in both helper files moves to the "It" text;
  n=2 and n=7 keep "They"; add a malformed-tail case (string / missing key →
  project pair).
- e2e: the three describes build the expected tail from the count they
  create (each fixture pauses exactly one template → "It resumes …").

## 5. Out of scope

Nothing else found. The Help page (`templates/docs.html:1528,2190`) talks
about templates in general ("Unarchiving resumes them") — still correct.
No server, template, CSS or SW change; copy only, in three static JS files
(so `CACHE_VERSION` bumps).
