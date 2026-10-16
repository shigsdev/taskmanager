# #461 — Goal cascade edge cases left by #427

Filed 2026-10-11 from `docs/design/427-goal-links-wiped.md` §3. Checked
2026-10-15 against `task_service.update_task` and
`filter_helpers.goalAfterProjectChange`.

## What was wrong

1. **Subtasks didn't follow a goal that came from a project change.** The
   subtask cascade keyed on `"goal_id" in data`. Assigning the parent a
   project with a goal (or dropping an inherited goal) moved the subtasks'
   project but left them on the old goal — a subtask on project P3 with
   P1's goal.
2. **Three answers to "move to a project with no goal".** The task panel
   drops a goal that came from the old project (user report 2026-05-04,
   kept by #427, `goalAfterProjectChange`). A drag onto a project card, a
   bulk edit and any other PATCH kept it (`update_task`), and Help said it
   keeps.

## The rule (no new decision needed)

The panel's rule is already the user's choice (2026-05-04: "I changed
project … and the goal didn't change with it"), and since #427 the server
uses the same test for "No project": drop the goal only if it equals the
old project's goal; a goal set by hand stays (the PR24 audit's
silent-data-loss finding). This ship makes "a project with no goal" the
same case as "no project", so the panel, drag, bulk edit and Help agree.

## This ship

- `update_task`: assigning a project with a goal → that goal (unchanged);
  a project without one, or none → drop the goal only when it came from the
  old project.
- The subtask cascade fires when the goal changed and the payload carried
  `goal_id` or `project_id`. A goal changed by a type change (#475's
  unlink) still doesn't cascade.
- Help: "Goal cascade onto linked tasks" and Subtasks → Rules corrected.

## Tests

- pytest (`TestProjectGoalCascade`): inherited goal dropped on a single
  PATCH and in bulk; a hand-set goal kept; an explicit goal still wins;
  subtasks follow a project-derived goal and a dropped one; a subtask on its
  own goal is left alone. The PR24 BUG-2 test (no old project) still passes.
- Playwright (#344 block): drop on a goalless project card drops an
  inherited goal and keeps a hand-set one. Red on the old code.
