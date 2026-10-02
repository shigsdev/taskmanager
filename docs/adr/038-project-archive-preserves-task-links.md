# ADR-038: Archiving a project preserves task links and pauses its repeating tasks

Date: 2026-10-01

Status: ACCEPTED (user-approved 2026-10-01 via the #353 spec,
`docs/design/353-project-archive-pauses-templates.md`)

Supersedes: the task-detach in `project_service.delete_project` added by
PR63 audit fix #129. That was an audit fix, not an ADR, so this is the
first written record of the decision in either direction.

## Context

A project can be archived through two service functions, and they
disagreed:

| Path | Function | Detached tasks? |
|---|---|---|
| Detail panel **Archive**, bulk **Archive**, reflection `update` | `update_project(is_active=False)` | no |
| Bulk **Delete**, `DELETE /api/projects/<id>`, reflection `delete` | `delete_project` | **yes**, nulled `Task.project_id` (PR63 #129) |

So the button actually labelled Archive cascaded less than the Delete
beside it. Prod shows which one the user really uses: 270 tasks still
point at 8 archived projects, all archived through the button, with no
phantom-label reports.

Neither path touched `RecurringTask`, so a template on an archived
project kept spawning tasks into it (#353; one live case on prod, on the
archived "Community of Practice" project).

PR63 detached tasks to fix two symptoms: phantom project labels on task
cards, and ghost entries in the project filter. Both are now fixed where
they're displayed:

- The board badge resolves `task.project_id` against `allProjects`,
  which is active-only (`static/app.js:1345`), so an archived project
  renders no badge.
- `_sweepStaleFilterIds` (`static/app.js:142`) drops a dead project id
  from the saved filter after every load.
- The detail-panel pickers render an archived link as a disabled
  `(archived)` option and keep it on save (#355).
- Every server reader that turns a `project_id` into a name builds its
  lookup from active projects only: the digest
  (`digest_service.py:211`), reflection (`reflection_service.py:112`,
  `:161-162`), the weekly planner (`weekly_planner_service.py:292`),
  weekly focus (`weekly_focus_service.py:478`) and inbox categorize
  (`inbox_categorize_service.py:153`).

## Decision

1. **One function changes a project's `is_active`:**
   `project_service._set_project_active(project, active)`. Both
   `update_project` and `delete_project` call it, and so does everything
   built on them: bulk edit, bulk delete, and the reflection apply path.
2. **Archiving keeps task links.** The PR63 detach is removed, so Delete
   is now exactly the Archive button.
3. **Archiving pauses the project's currently-active templates** and
   sets `RecurringTask.paused_by_project_archive`. **Unarchiving resumes
   only flagged templates.** Any user override clears the flag: an
   actual `is_active` change (in practice a resume, since a paused
   template is already inactive), a move to another project, or a
   delete. Saving a spawned task doesn't count: its detail panel shows
   an inactive template as Repeat "none", so `_update_repeat` keeps the
   link to an inactive template rather than reading that echo as a
   choice.
4. **Only on an actual transition.** A re-sent `is_active` value is a
   no-op, so it can't undo a manual resume.
5. A data migration (`r7f8a9b0c1d2`) applies rule 3 retroactively to
   active templates already sitting on archived projects.

## Consequences

- Delete-then-unarchive is lossless. Before, it permanently stripped
  every task's project link, while the same project archived through
  the button got its tasks back.
- An archived project's tasks still carry its id. Any NEW reader that
  displays a project name must resolve against active projects (or show
  an explicit archived marker, as #355 does). #361 tracks making that
  one shared rule.
- A paused template disappears from `/recurring` until the project is
  unarchived. That is a pre-existing limitation of that page (#363), not
  caused by this decision; the archive confirm says the templates will
  resume.
- The recycle bin follows this rule too (#356, 2026-10-02):
  `recycle_service.undo_batch` / `restore_batch` archive and unarchive an
  imported project through `_set_project_active`, and undo no longer
  nulls task links. `purge_batch` clears `paused_by_project_archive` on
  templates of the projects it hard-deletes, because that promise can't
  be kept once the project is gone; it leaves them paused rather than
  firing into no project. Spec: `docs/design/356-recycle-paths-follow-archive-rule.md`.
- Goals follow the same rule (#368, 2026-10-02). `goal_service._set_goal_active`
  is the one writer of `Goal.is_active` (`update_goal`, `delete_goal`, the
  reflection apply path, recycle undo/restore). A template can sit on an
  archived project AND an archived goal, so each parent has its own marker
  (`paused_by_project_archive`, `paused_by_goal_archive`) and the pause /
  resume rule lives once, in `recurring_service.cascade_parent_archive`:
  archiving pauses running templates and adds its marker to ones the other
  parent already paused; unarchiving clears its marker and resumes only a
  template with no marker left. Each override or purge clears only the
  marker it concerns, and clearing never resumes. `/goals` names the
  templates in its Archive confirm. Spec:
  `docs/design/368-goal-archive-pauses-templates.md`.

## Alternatives considered

- **Detach templates (`project_id = None`), mirroring the old task
  rule.** Rejected: a detached template still fires. It just fires into
  no project.
- **Keep the task detach and only add the template pause.** Rejected:
  the two archive paths would keep disagreeing, and Delete would stay
  lossy for no remaining benefit, since every PR63 symptom is fixed on
  the read side.
- **Skip archived projects at spawn time instead of pausing.**
  Rejected: a template would look active and never fire, and it would
  hide exactly the cascade-bypass bugs #356 is about.
- **Track the pausing project with a `paused_by_project_id` FK instead
  of a boolean.** Rejected: the template's own `project_id` already
  names the project, and the flag is cleared whenever that changes.

## Regression tests

- `tests/test_project_archive_templates.py`: the cascade on every path,
  link preservation, flag hygiene, the backfill SQL, and the recycle-bin
  paths (#356: undo pauses, restore resumes, purge clears the flag).
- `tests/test_goal_archive_templates.py` (#368): the goal cascade on every
  path, both overlap orders, per-marker hygiene, the backfill SQL, and the
  goal recycle-bin paths.
- `tests/test_projects_api.py::test_delete_preserves_task_project_fk`
  and `tests/test_project_goal_cascade.py::test_deleting_a_project_preserves_task_project_and_goal`:
  the two former PR63 tests, rewritten to the new rule.
