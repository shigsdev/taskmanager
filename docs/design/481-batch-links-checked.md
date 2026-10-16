# #481 — Batch creators drop a bad project / goal link and say so

Split from #475 on 2026-10-15. Checked 2026-10-16 against
`import_service.create_tasks_from_import`,
`import_service.create_projects_from_import`,
`scan_service.create_tasks_from_candidates` and their callers
(`import_api` tasks confirm, `scan_api` confirm, `voice_api` confirm,
`reflection_service` apply).

## What was wrong

#475 checks every link a single task write sets (`link_service`), but the
batch creators set `project_id` / `goal_id` straight on the new rows:

- **A dangling id fails the whole batch.** The review screens send the
  ids the user picked; if that project or goal was deleted meanwhile (or
  the id is stale), Postgres refuses the foreign key at commit and every
  row is lost with "Database error" (SQLite in dev doesn't enforce it, so
  it only shows on Railway).
- **An archived project / goal is linked silently**, which #475 refuses
  everywhere else.
- **A task can land on a project of the other type.** Import's Excel
  `linked_project`, a voice `@project` hint and a reflection
  `project_hint` resolve against active projects of either type, and the
  review screens let you pick any project for a row.

`create_projects_from_import` is already safe: its goal comes only from a
name lookup over ACTIVE goals, so it can't dangle or be archived.

## This ship

- `link_service.fit_batch_links(project_id, goal_id, *, item_type)` →
  `(project_id, goal_id, reasons)`: a project that doesn't exist, is
  archived or is the other type is dropped; a goal that doesn't exist or
  is archived is dropped; each drop gives a reason in the #475 wording
  ("its project no longer exists", 'the project "X" is archived',
  '"X" is a personal project and this is a work task', …). The row itself
  is still created (#447's "fit what comes in a batch").
- `create_tasks_from_import` and `create_tasks_from_candidates` run every
  row through it and take an optional `link_notes` list they append
  `"<title>" — <reason>` to.
- `link_service.batch_link_warning(notes)` turns them into one sentence:
  `Added without a link: "A" — …; "B" — ….` (the first three, then
  "and N more").
- Callers: import (tasks) and scan (tasks) confirm answer `warning`;
  voice Add All adds it to its existing `warning` (#425); a reflection
  apply puts the notes in `summary.notes`.
- Pages: /import's and /scan's done message append the warning (as the
  voice memo page already does); /reflection's done screen lists the notes
  under the summary.

The quiet case: a batch whose links are all fine answers no `warning` /
`notes` and the pages read exactly as before.

Note: the /scan page sends no project / goal for task rows today, so the
scan endpoint's check (and its page's warning line) only matters for an
API caller — kept so every batch creator behaves the same.

Help → Import: a "A project or goal that doesn't fit" paragraph, and the
"What the parser does NOT do" line no longer says links can't be set
during import (the review screen has had per-row Project / Goal pickers
since #76).
