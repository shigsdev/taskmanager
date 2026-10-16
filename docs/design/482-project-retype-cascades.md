# #482 — Changing a project's type retypes its tasks and repeating tasks

Split from #475 on 2026-10-15. **User decision 2026-10-16: "Retype them
too"** — over refusing the change while it has tasks, or unlinking them.
Checked against `project_service.update_project` / `bulk_update_projects`,
`static/projects.js` (`projectDetailSave`, `bulkPatchProjects`) and
`static/project_archive_helpers.js`.

## What was wrong

`update_project` (the project panel's Save, and /projects bulk Type ▾,
which calls it per project) sets `project.type` and nothing else. Every
task and repeating task on the project keeps the old type, so each one is
now a mismatch that #475 refuses everywhere else (a task panel save that
re-sends the project still passes, because an unchanged link isn't
re-checked) and the tasks sit in the other view's filter from their
project.

## This ship

- `update_project`: when `type` actually changes, every task on the
  project (any status, so its history matches), the subtasks of those
  tasks, and every repeating task on it take the new type, in the same
  commit. The goal links are untouched. Bulk Type ▾ gets it for free.
- The confirm (`projectArchiveHelpers.typeChangeMessage`, Jest-tested):
  before a Save or a bulk Type ▾ that changes a project's type, the page
  asks e.g. `4 tasks and 1 repeating task on "Kitchen" become Personal
  too.` (or `on 3 projects`). Tasks = the card's active + done count
  (`task_counts`, #375); repeating tasks = `/api/recurring?all=1` on those
  projects. Cancel leaves everything as it was.
- The quiet cases: a type change on a project with no tasks or repeating
  tasks asks nothing; a Save that doesn't change the type asks nothing;
  bulk Type ▾ to the type the projects already have asks nothing.
- Help → Projects: one sentence.
