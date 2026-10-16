# #483 — Pickers offer only projects of the item's own type

Split from #475 on 2026-10-15. Checked 2026-10-16 against
`static/recurring.js` (editor + bulk Project), `static/import.js` (review
rows), `static/plan.js` + `weekly_planner_service.py` (✨ Plan / /plan) and
`static/app.js` (board bulk toolbar, "All" view).

## What was wrong

Since #475 the server refuses a task or repeating task on a project of the
other type, but five pickers still listed every project, so the pick
failed on Save (or, since #481, an import row was added without it):

| Picker | Lists | Should list |
|---|---|---|
| /recurring editor Project | every live project | the editor's Type |
| /recurring Select → Project ▾ | every live project | the selected templates' type |
| /import review row Project | every live project | that row's Type (re-listed when it changes) |
| /plan row Project | every live project — and the planner can SUGGEST one of the other type | the task's type |
| Board Select → Project ▾ in the **All** view | every live project | the selected tasks' type |

The task panel (`taskDetailPopulateProjects`) and the voice memo review
already filter by type; Work / Personal views of the board already do.

## This ship

- `filterHelpers.projectsForTypes(projects, types)` (Jest-tested): the
  projects matching the ONE type `types` share; `{projects, mixed}` —
  when the selection holds both types, `mixed` is true and no project
  fits (only "none" is offered, with a one-line reason).
- /recurring editor: the Project list follows the Type select (a project
  of the other type already chosen is dropped when Type changes, as the
  task panel does via `projectAfterTypeChange`); bulk Project ▾ lists the
  selected templates' type, or says they are mixed.
- /import: each task row's Project list follows its Type select.
- /plan: `weekly_planner_service` adds the task's `task_type` to every
  per-task suggestion and drops a `suggested_project_id` of the other type
  (applying it would be refused); the row's Project list follows
  `task_type`.
- Board All view: Project ▾ lists the selected tasks' type, or says they
  are mixed ("(the selected tasks are both Work and Personal — pick one
  type)").

The quiet cases: Work / Personal board views are unchanged; an archived
project already on a template still shows (labelled, #355) so editing
another field doesn't detach it.
