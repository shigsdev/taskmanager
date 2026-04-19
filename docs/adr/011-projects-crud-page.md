# ADR-011: Projects CRUD page (`/projects`)

Date: 2026-04-19
Status: ACCEPTED

## Context

Backlog #24 — until now, projects could only be created via
`POST /api/projects` (or the `seed_default_projects` endpoint). There
was no UI to add, rename, recolor, link to a goal, or archive a
project. That meant customising the app to the user's actual work and
personal areas required curl. The projects API (`projects_api.py`) was
already complete — only the UI was missing.

## Decisions

### 1. Dedicated `/projects` page, not a settings tab

Mirrors the precedent set by `/goals`. Settings is for app-level
configuration (digest schedule, encryption); Goals is the CRUD page
pattern for a domain entity. Projects fit the latter. A new top-nav
tab between Goals and Import keeps related CRUD pages adjacent.

### 2. Reuse the goals chrome (cards, category sections, detail overlay)

The `templates/goals.html` + `static/goals.js` structure was copied
into `projects.html` + `projects.js` with these adaptations:
- Cards group by `type` (work/personal) instead of category
- Filter row has type + active-state dropdowns instead of
  category/priority/status/quarter
- Card body shows a colour swatch + name + linked goal title +
  task counts (`N active / M total`) instead of progress bar
- Detail panel has name / type / colour / goal / sort_order — no
  "linked tasks" subsection (the relationship lives on the task side
  via `task.project_id`)

CSS for the card chrome is reused via the `.goal-card` /
`.goals-category-section` classes; only project-specific styles
(`.project-color-dot`, `.project-title-row`,
`.project-task-summary`) live in the new block at the bottom of
`style.css`.

### 3. No separate "Delete" button — Archive is the only destructive action

The existing `DELETE /api/projects/<id>` is a soft-delete (sets
`is_active = False`); it leaves the row in the DB so historical task
references survive. That makes it semantically identical to the
Archive action. Surfacing both in the UI would be confusing — users
would reasonably expect Delete to be permanent. Decision: expose only
Archive ⇄ Unarchive. The DELETE endpoint stays available for API
clients that don't want the row to ever resurface in `is_active=all`
listings, but the UI doesn't expose it.

(If we ever want a true hard-delete with cascading project-id removal
on linked tasks, that's a future API change with proper
"are you sure" semantics — out of scope here.)

### 4. Sort order: active-first, then `sort_order`, then name

Active projects float to the top of each type group. Within active
(or within archived), `sort_order` ascending breaks ties; alphabetical
breaks remaining ties. This matches how the task-side project chips
are likely to be picked from a dropdown, where a user-curated order
is more useful than alphabetical.

### 5. `<input type="color">` for the colour picker

Native control, works on every platform, no external dependency. The
`Project.color` column is a 7-char `String` (hex like `#2563eb`),
which is exactly what `input[type=color]` produces. Default fill
when the field is null: `#2563eb` (theme blue) — matches the
`DEFAULT_PROJECT_COLOR` constant in `projects.js`.

### 6. Goals dropdown is sourced from `/api/goals?is_active=all`

We need every goal that COULD be selected, not only active ones —
otherwise editing a project linked to an inactive goal would lose the
link silently when re-saving. Active-only filtering happens in the
JS `populateGoalDropdown` so newly-created projects can't link to
archived goals. Existing links to archived goals stay intact (the
selected `<option>` is rendered with the saved goal_id even when it's
filtered out of the active list — TODO if a user reports it).

## Consequences

**Easy:**
- No API or schema changes. The endpoint surface was complete.
- The `task.project_id` foreign key continues to be the only
  reference between tasks and projects; nothing to migrate.
- Nav-tab insertion + tier-cache bump (`v39 → v40`) +
  `EXPECTED_STATIC_FILES` update are mechanical follow-on changes
  to keep the SW + health check in sync.

**Hard / accepted trade-offs:**
- "Archive" and the `DELETE` endpoint are the same thing. A future
  developer reading the API in isolation might add a UI Delete button
  expecting hard-delete semantics. Mitigated by an inline comment in
  `projects.html` explaining the choice and a docstring update in
  `projects_api.py` could reinforce it (TODO).
- The active filter shows only active projects by default. If you
  archive a project you stop seeing it unless you switch the filter to
  "Archived" or "All". This is the right default but means archive
  feels like delete to a casual user. The badge ("Archived") on cards
  in the All view should make the distinction clear.

## Alternatives considered

- **Settings tab** — rejected. Settings is for app config; CRUD on
  domain entities belongs on its own page. Goals is precedent.
- **Inline editing on the project chips already on the board /
  tier pages** — rejected as not enough room and conflates filter UI
  with CRUD UI. Click-to-edit on the dedicated page is the cleaner
  separation.
- **Hard-delete with cascade on linked tasks** — rejected for now.
  The single-user audit-trail value of soft-delete outweighs any
  storage savings. Can be added later if real demand emerges.
- **Drag-to-reorder for sort_order** — rejected. The numeric field is
  enough for a single-user app and avoids a JS drag library. If users
  start curating long project lists, revisit.
