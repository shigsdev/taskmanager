# ADR-045: The MCP token can list, create and edit goals and projects (amends ADR-044)

Date: 2026-11-15

Status: ACCEPTED (#530, user request 2026-11-15 "allow for creating and
updating projects and goals"; design calls approved with PR #25's merge)

Amends: ADR-044 (scoped MCP connector token). Its token format, salt,
lifetime, header-only transport, `/mcp`-only scope, per-jti denylist, rate
limit, Origin check and kill-switches are unchanged. This ADR widens what the
token can **do**: six tools beside the five task tools.

## Context

ADR-044 kept the claude.ai connector to tasks ("nothing outside tasks"). The
user wants Claude to set up and maintain goals and projects too, in the same
chats. Claude can't see either today: a project is only reachable by its exact
name, as a task field.

`goal_service` and `project_service` already hold every rule (#447 lengths,
#475 a project can only link a live goal, #509 goal validation before any
write). Two project edits change other rows, and the app asks first:

- **A new type** re-types every task on the project, their subtasks, and its
  repeating tasks (#482).
- **A new goal** is written onto every task and repeating task on the project
  (#350, #352). The app confirms only when that can't be taken back: goals
  cleared from tasks, or tasks spread over several goals collapsed onto one
  (#351). A one-goal move, and adding a goal where there was none, ask nothing.

## Decision

1. **Six tools** in `mcp_tools.py`: `list_goals`, `create_goal`,
   `update_goal`, `list_projects`, `create_project`, `update_project`. Each
   passes only its own keys to the service, so every app rule applies. Goals
   and projects are named by id (from the list tools); a project's goal is a
   `goal_id`.
2. **No archive, no delete.** Neither tool takes `is_active`. Archiving pauses
   repeating tasks (#353, #368) and both stay in the app, as task delete and
   cancel do (ADR-044). Archived goals and projects can be listed
   (`archived: true`) but not edited.
3. **The app's confirms become a second call.** When `update_project` would
   re-type tasks, or clear or flatten their goals, it changes nothing and
   returns an error saying what would change (counts and goal titles). It runs
   only when called again with `apply_to_tasks: true`. The server instructions
   tell Claude to relay that to the user and pass the flag only once they
   agree. The quiet cases stay quiet: same rule as the app, computed on the
   server over the rows the cascade actually touches.
4. **No twin project names.** `create_project` and a rename refuse a name an
   active project of the same type already has (case and outer spaces
   ignored). The task tools find a project by name, and a twin makes both
   unusable there. The app itself still allows twins.
5. **Audit lines** as before: `mcp: created goal <id>`,
   `mcp: updated project <id> (status, goal_id)`. Never a title, name or notes.

## Consequences

- **A leaked token can do more.** On top of ADR-044's task actions, a holder
  can read every goal and project (titles, actions, notes, task counts), add
  goals and projects, and edit active ones, including re-typing a project's
  tasks or moving them all to another goal. It still can't archive or delete
  anything, or reach recurring templates (beyond the cascade above), settings,
  exports or auth. Every change is visible in the app. Status, priority,
  quarter, type and goal edits can be set back; an overwritten title, actions
  or notes can't, and a flattened goal spread can't (there is no history).
- **`apply_to_tasks` is a speed bump, not a lock.** A token holder (or a
  prompt-injected Claude) can pass it on the first call. The real controls are
  unchanged: claude.ai's per-call confirmation unless "Always allow", the
  revocable token, and the app showing every change.
- **More of the user's planning text reaches Claude chats.** Goal actions and
  project notes are now readable, the same trade ADR-044 made for task notes.

## Alternatives considered

- **Archive / unarchive tools.** Rejected for now: archive pauses repeating
  tasks and is the closest thing to delete these entities have. Easy to add
  later behind its own ask.
- **Refuse cascading edits outright** (no type or goal change via MCP).
  Rejected: re-homing a project under a goal is a core planning move. The
  second call keeps it possible and keeps the user in the loop.
- **Always require `apply_to_tasks` for any type or goal change.** Rejected:
  the app deliberately asks nothing for a one-goal move or an empty project
  (#351's "the quiet case is easy to regress into a nag").
- **Name goals by title**, as tasks name projects. Rejected: goal titles run to
  500 characters and are often near-duplicates; ids from `list_goals` are exact.
