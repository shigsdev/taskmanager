# #432 — Import: a late parse after Back no longer imports as goals; Parse buttons work again

Filed 2026-10-11 by the deep review (§A9).

## 1. Surface

`static/import.js` has eight Parse buttons, each its own handler with the
same shape: disable the button → `await apiFetch(parse)` → (sometimes
`await loadImportLookups()`) → render the review and show it.

| Mode button | Parse button | Endpoint | Mode / source |
|---|---|---|---|
| Paste tasks | `#importParseTasksBtn` | `/api/import/tasks/parse` | tasks |
| Word (.docx) | `#importParseDocxBtn` | `/api/import/tasks/upload` | tasks |
| Tasks Excel | `#importParseTasksExcelBtn` | `/api/import/tasks/upload-xlsx` | tasks |
| Transcript paste | `#importParseTranscriptBtn` | `/api/import/transcript/parse` | tasks / `transcript_import` |
| Transcript file | `#importParseTranscriptUploadBtn` | `/api/import/transcript/upload` | tasks / `transcript_import` |
| Projects paste | `#importParseProjectsTextBtn` | `/api/import/projects/parse` | projects |
| Projects Excel | `#importParseProjectsExcelBtn` | `/api/import/projects/upload` | projects |
| Goals Excel | `#importParseGoalsBtn` | `/api/import/goals/parse` | goals |

Problems:

| # | Step | Code | Problem |
|---|---|---|---|
| 1 | Parse, then Back before it answers | `resetAll` (`:127-155`) | Sets `currentMode = null` but nothing drops the in-flight parse. The answer lands anyway: the review appears over the mode list (or over another mode the user has since opened) |
| 2 | Import all / selected on that review | `executeImport` (`:1066-1069`) | `currentMode` is null → the `else` sends the TASK candidates to `/api/import/goals/confirm`. The done text says "goal(s)" |
| 3 | A late parse that FAILS | each `catch` | Writes "Parse failed" into the hidden mode's status and re-enables its button; next visit shows a stale error |
| 4 | Start Over / Import More / Back after a successful parse | `resetAll` | The three paste-mode Parse buttons (tasks, projects, transcript) are only re-enabled on failure — after a success they stay disabled until reload |
| 5 | Same, for the file modes | `resetAll` | Clears goals/docx/transcript file inputs, but NOT tasks-Excel or projects-Excel: their old file name stays shown, the button stays disabled, and picking the same file again fires no `change`, so it can't be re-enabled |
| 6 | Same | `resetAll` | Leaves the tasks-Excel / projects-paste / projects-Excel status lines and the projects textarea as they were |
| 7 | Cancel while "Importing…" | `executeImport` | Reads `currentMode` after the await; `resetAll` has nulled it → "N goal(s) imported" for tasks (the import itself did happen, so showing Done is truthful; only the noun is wrong) |

## 2. This ship

1. One shared `createRequestGuard()` (#418's helper) for parses. Each Parse
   handler takes a token before its request; after every await (the parse,
   the lookups, and in `catch`) it stops if the token is no longer current.
   `resetAll` cancels it. A newer parse supersedes an older one.
2. The mode and source are set when a parse's review is SHOWN (one shared
   `importShowReview`), not when the mode button is clicked, so the review's
   mode always matches its candidates.
3. New `static/import_helpers.js` (dual export, Jest-tested):
   `importConfirmUrl(mode)` returns null for anything but tasks / projects /
   goals (no fall-through to goals), `importNoun(mode)`. `executeImport`
   snapshots the mode before awaiting and refuses (alert, no request) when
   there's no URL.
4. `resetAll` re-enables the three paste Parse buttons, and for all five
   file modes clears the input, the shown file name and disables the button;
   hides every status line; clears the projects textarea.
5. Playwright × 2 viewports (red on the old page): a tasks parse answered
   after Back → Projects stays on Projects, no review, no confirm request;
   Parse works after Start Over and after Import More; a projects-Excel file
   name is cleared by Start Over.
6. Cascade: new asset → `sw.js` APP_SHELL + `health.py` + CACHE_VERSION;
   `import.html` loads `request_guard_helpers.js` + `import_helpers.js`;
   CLAUDE.md Phase 6 line + row.

No Help text change: Help doesn't describe Back / Start Over behaviour.

## 3. Out of scope

Nothing new found beyond the rows above; the "Importing…" Cancel race is
truthful (the import ran) and its noun is fixed by item 3.
