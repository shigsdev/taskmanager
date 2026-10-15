# #475 — Project and goal links on a write are checked

Split from #447 (deep review §B10).

## What happens

A `project_id` / `goal_id` on a write is only parsed as a uuid. Nothing looks
it up:

| Id on a write | Today |
|---|---|
| Doesn't exist | Postgres: the foreign key fails → 422 "Database error — full detail is in the server logs". SQLite (tests): saves a dangling link. |
| Archived project / goal | Saves. The task only shows under an "(archived)" group (#434); the "all" board view shows no badge. |
| Project of the other type (work task → personal project) | Saves. The task disappears from its own type's board view and shows under the other type's project header; the panel shows the project as "(unavailable)". |

And changing a task's Type never looks at its project: the detail panel keeps
the old project selected as "(unavailable)" and Save writes the mismatch
(`app.js` `taskDetailToggleProject`, `task_service.update_task` type branch).
Same for bulk Type, 💡 Auto-categorize and a template's Type.

## Decisions (user, 2026-10-15)

1. **A NEW link to an archived project or goal is refused** — "unarchive it
   first". Links already there keep saving, and inherited links (a subtask
   from its parent, a task's goal from its project) are not new links.
2. **A task's (or template's) project must be its own type.** Picking a
   project of the other type is refused. Changing the Type takes the task off
   a project of the other type, exactly as picking "(no project)" would (#427:
   a goal set by hand stays, the goal that came from the project goes).
   Tasks already mismatched keep saving while neither the type nor the project
   changes.

## Change

New `link_service.py` (models + utils only, so every service can import it):

- `check_project_link(project_id, *, item_type=None, field="project_id")` →
  the `Project`, or `ValidationError`:
  - missing: "That project no longer exists — pick another."
  - archived: `The project "<name>" is archived — unarchive it first.`
  - wrong type: `"<name>" is a personal project and this is a work task — pick
    a work project or none.` (template: "… this is a work template …")
- `check_goal_link(goal_id, field="goal_id")` → the `Goal`, or
  "That goal no longer exists — pick another." /
  `The goal "<title>" is archived — unarchive it first.`
- `project_type_matches(project, item_type)`.

Checked only on a CHANGE (every editor re-sends the stored links on Save):

| Write | Project | Goal |
|---|---|---|
| `task_service.create_task` | caller's id, unless it is the parent's (subtask) | caller's id, unless it is the parent's or the project's goal |
| `task_service.update_task` (+ bulk, reflection, plan, auto-categorize) | new id ≠ stored | new id ≠ stored and ≠ the project's goal |
| `recurring_service.create_recurring` (+ task panel Repeat, voice "make recurring") | caller's id | caller's id, unless it is the project's goal |
| `recurring_service.update_recurring` (+ bulk) | new id ≠ stored | new id ≠ stored and ≠ the project's goal |
| `project_service.create_project` / `update_project` (+ bulk) | — | new id ≠ stored |

Type change (`update_task`, `update_recurring`): when the type actually
changes, the project is not being changed in the same write (absent or
re-sent), and the project is of the other type → `project_id = None`, and the
goal is cleared if it is that project's goal and the write doesn't change the
goal itself (#427). Subtasks are not touched (their type didn't change).

Capture bar `@project` (`tasks_api.create` → `resolve_project_hint`): a hint
prefers the task's own type. One match of that type → used. Only a match of the
other type → no project, warning
`"@<hint>" matches <name>, a personal project — task created without a project.`

Task detail panel: changing Type clears Project when the selected project
(live or archived) is of the other type, through the same handler as picking
"(no project)", so the goal follows #427 in the form before Save. Pure logic in
`filter_helpers.projectAfterTypeChange` (Jest). Opening a task never clears
anything (a stored mismatch stays visible as "(unavailable)").

💡 Auto-categorize review (found by the gate: its #427 test flipped Type and
expected the work project to stay): a row's Type flip clears a project of the
other type the same way (`inbox_categorize.js`, same two helpers), so the row
shows what Apply will save. The #427 test and CLAUDE.md line now expect a
hand-set goal to stay and the other-type project to clear.

Where refusals surface (unchanged plumbing): the panel / recurring editor /
project panel save message, `/goals` "Add linked task" alert, bulk per-row
errors (#430 messages), reflection per-row errors (#437). Voice "make
recurring" swallows the error into its skipped count — its project list is
already type-filtered and active-only.

## Out of scope → new rows

- **#481** Batch creators write links straight to the row with no check
  (`import_service` tasks + projects, `scan_service.create_tasks_from_candidates`
  for scan / voice / reflection): a dangling id fails the whole batch on
  Postgres, a voice hint can pick a project of the other type. Fix: same
  checks, but drop the link and say so instead of failing the batch (#447's
  "fit what comes in a batch").
- **#482** Changing a PROJECT's type (panel, /projects bulk) leaves all its
  tasks and templates of the old type on it — every one becomes a mismatch.
- **#483** Pickers that offer projects of the other type, now refused on Save:
  the /recurring editor and recurring bulk, the import review, ✨ Plan, and the
  board bulk toolbar in the "all" view. Filter them by type.

## Tests

pytest (`tests/test_link_checks.py`): for task create / update / bulk,
recurring create / update / task-panel Repeat, project create / update — a
missing id, an archived project or goal, and an other-type project are each
422 with the message, and nothing changes; a re-sent archived or mismatched
link still saves (the quiet case); a subtask on an archived parent project is
created; a project whose goal is archived cascades it onto a new task;
changing Type unlinks an other-type project and clears (only) its goal, a
same-type project stays; capture hint prefers own type and warns on
other-type-only. Jest: `projectAfterTypeChange`. Playwright: panel Type change
clears Project and Save keeps the hand-set goal.
