# #488 — The /scan review words itself by kind

Found in #487's Phase 6 on 2026-10-15.

## What was wrong

`templates/scan.html`'s review screen was fixed copy — "Review Task
Candidates", "…before adding to inbox.", "Add All to Inbox", "Add Selected
to Inbox" — whatever was picked under *Parse as*. Goals go to /goals and
projects to /projects (the done message already said so, `scan.js`).

## This ship

- New `static/scan_helpers.js` (dual export, `window.scanHelpers`):
  `scanReviewCopy(kind)` → `{heading, hint, addAll, addSelected}` for
  `tasks` / `goals` / `projects`; anything else reads as tasks.
- `scan.js` sets the heading, hint and both Add buttons from it each time
  a scan's review shows, so a later scan of another kind re-words it.
- Tasks keep the exact old wording (the quiet case).
- Help → Image scan: the pipeline names the buttons by kind, and says
  candidates become Tasks, Goals **or Projects** (it said "Tasks (or
  Goals)").
- `sw.js` APP_SHELL + `health.py` EXPECTED_STATIC_FILES list the new file;
  CACHE_VERSION v343.

## Tests

`tests/js/unit/scan_helpers.test.js` (copy per kind, unknown → tasks);
`tests/e2e/scan_review_copy.spec.js` (upload stubbed: goals, projects, and
goals → Scan Another → tasks) — red before.
