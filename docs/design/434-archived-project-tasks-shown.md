# #434 — The Work / Personal board shows tasks on archived projects

Filed 2026-10-11 by the deep review (§A11).

## 1. Surface

In the Work or Personal view with no project filter, every section (on the
board and on `/tier/<name>`) is drawn by `renderTierGroupedByProject`
(`static/app.js:801`). It walks `allProjects`, which holds active projects
only (#355 keeps that list active-only on purpose), then a "No project"
group. A task whose project is anywhere else is drawn nowhere:

| Task's project | Today |
|---|---|
| active | its project's group |
| none | "No project" |
| **archived** (since #353, archiving keeps the task's link) | **missing** |
| **not in either list** (projects failed to load, or a stale id) | **missing** |

The section's count is `tasks.length` (`app.js:772`), so it still counts
them: "Inbox 7" over 4 cards. The All view and a project filter are not
affected (no grouping, or the filter bar only offers active projects).
This is the only place tasks are grouped by project.

## 2. This ship

1. New pure `filterHelpers.groupTasksByProject(tasks, activeProjects,
   archivedProjects)` (Jest) returns ordered groups `{key, label, color,
   archived, tasks}`. The order is: active projects (in `allProjects`
   order), then archived ones labelled "<name> (archived)", then "Unknown
   project", then "No project". It puts every task in exactly one group,
   so the cards always add up to the count.
2. `renderTierGroupedByProject` draws those groups. An archived group's
   header gets `project-group-header-archived` (muted, like other archived
   UI).
3. Playwright × 2 viewports (red on the old page): a task on an archived
   work project shows in Work view under "<name> (archived)", and the
   section count equals the cards shown.
4. CACHE_VERSION; CLAUDE.md Phase 6 line + rows. No Help change: Help
   doesn't describe the per-project grouping in Work / Personal view.

## 3. Out of scope

None found. The card's own project badge still hides an archived project
(#129's deliberate choice); the group header now names it.
