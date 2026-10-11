# #427 — Goal links silently wiped

Filed 2026-10-11 by the deep review (§A5); probable cause of #146 ("goal reset
to None on save", deferred since 2026-05-03 for lack of a repro).

**The rule this ship makes true everywhere:** when a task's project changes,
a goal that came from the old project goes with it, and a goal you set
yourself stays. "Came from the old project" = the task's goal equals the old
project's goal.

## 1. Surface — every path that changes a task's project

| Path | Code | Problem |
|---|---|---|
| Server, project cleared | `task_service.py` `update_task` (~733-753) | `project_id: null` always clears `goal_id`, even a goal set directly on a task that never had a project |
| Bulk toolbar "No project" | `tasks_api.bulk_update` → `bulk_update_tasks` → `update_task` | Same — every selected task loses its goal |
| Task panel, Project changed | `static/app.js` `taskDetailProjectChanged` (~2711) | Always resets the Goal select to the new project's goal or "— None —" (2026-05-04 UX fix), so picking "(no project)", or a project with no goal, blanks a goal you set yourself; Save then sends `goal_id: null` |
| 💡 Auto-categorize, seeding | `inbox_categorize_service.py` (prompt ~131-186, `categorize_inbox`) + `static/inbox_categorize.js` `renderRow` (~141-148) | Claude sees only id + title; the row's Project / Goal / Type / Due start from Claude's suggestion, never the task's own values. A task captured with `@project` (and its goal) shows "— None —" |
| Auto-categorize, Project/Goal selects | `inbox_categorize.js` `projectSelect` / `goalSelect` (~302-330) | Filtered by the row's type and active-only; a current project/goal outside that list renders blank |
| Auto-categorize, Apply | `inbox_categorize.js` `readRow` (~444-475) | Always sends `type`, `project_id`, `goal_id` — blank selects become `null`, wiping the links; Work can flip to Personal (prompt: "Default personal if ambiguous") |
| Auto-categorize, project cascade | `inbox_categorize.js` `_wireProjectCascade` (~248) | Same always-reset as the panel |
| Server, new project with no goal | `update_task` | Keeps the goal — already right, unchanged |
| Voice memo review | `voice_memo.js` (~598-615) | New candidates, no prior goal — out of scope |

## 2. This ship

1. **Server** `update_task`: on `project_id: null`, clear the goal only when it
   equals the old project's goal.
2. **Shared pure helper** `goalAfterProjectChange(oldProjectId, newProjectId,
   currentGoalId, allProjects, allowedGoalIds)` in `static/filter_helpers.js`:
   the new project's goal if it has one (existing cascade); otherwise `null`
   if the current goal came from the old project, else the current goal.
   Used by the task panel and Auto-categorize. The panel remembers the
   project selected before each change.
3. **Auto-categorize, server**: each suggestion carries the task's
   `current_type`, `current_project_id` (+ name), `current_goal_id` (+ title)
   and `current_due_date`. A task's own project, goal and due date win over
   Claude's (Claude fills blanks); a task already filed under a project or goal
   keeps its type. The prompt shows each task's current type and asks Claude to
   keep it unless the title clearly says otherwise.
4. **Auto-categorize, client**: selects always include the row's current
   project/goal (named) even when the type filter or archive would hide it.
   Apply (`categorizeApplyPayload` in `inbox_categorize_helpers.js`) sends
   `type` / `project_id` / `goal_id` only when they differ from the task's
   current values, and sends `goal_id` whenever it sends `project_id` so the
   server cascade can't override what the row shows.
5. Tests, red on the old code: pytest (server clear rule incl. bulk; the
   categorize merge), Jest (both helpers), Playwright (panel "(no project)"
   keeps a direct goal; Auto-categorize with a stubbed suggestion leaves a
   captured task's project and goal alone).
6. Help: "Removing a task's project" sentence; Auto-categorize "What it
   suggests" (existing values kept). CACHE_VERSION bump.
7. #146: closed with a pointer here — reopen with a PATCH body if it recurs.

## 3. Out of scope (filed as #461)

- Subtasks don't follow a goal change that comes from a project change
  (`update_task` subtask cascade keys on `"goal_id" in data`).
- Moving a task to a project with no goal: the panel drops a goal inherited
  from the old project, a drag or bulk edit keeps it (Help says "keeps").
