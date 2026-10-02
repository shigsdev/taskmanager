# Spec #368 — Archiving a goal pauses its repeating tasks

**Filed:** 2026-10-02 (from #356's spec §7; user: "yes, the goals should
get the same treatment")
**Status:** specced, not yet built
**Builds on:** #353 / ADR-038 (`40451d0`), #356 (`5ac39eb`)
**Approach:** A — a second marker, `paused_by_goal_archive`, beside
`paused_by_project_archive` (user-approved 2026-10-02)
**Backend changes:** one new column + migration, one shared helper,
`goal_service`, `project_service`, `recurring_service`, `recycle_service`.
**Frontend:** the `/goals` Archive confirm names the templates it pauses.
**Prod exposure today (read-only check 2026-10-02):** 20 goals (7
archived), 26 templates (16 active). **0 templates point at an archived
goal**, so the backfill changes nothing on prod today; it ships anyway
for the window between this check and the deploy.

---

## 1. Problem

Since #353, archiving a **project** pauses its running repeating
templates and flags them `paused_by_project_archive`; unarchiving resumes
exactly the flagged ones. Archiving a **goal** does nothing to templates.
A template whose `goal_id` points at an archived goal keeps firing, and
`spawn_today_tasks` (`recurring_service.py:692`) stamps the archived goal
onto every new task.

A template can belong to a project **and** a goal. With only one marker,
unarchiving one of them would wake a template whose other parent is still
archived. That overlap is the design problem this spec settles.

## 2. Goal

- Archiving a goal, by any path, pauses the goal's running templates.
- Unarchiving it resumes exactly those, and only once **neither** the
  goal **nor** the project is still archived.
- Nothing the user paused, deleted or moved by hand is ever resumed.
- The `/goals` Archive confirm names the templates it will pause, like
  `/projects` does since #353. No templates means no dialog.

## 3. Affected surfaces (the complete list)

Every writer of `Goal.is_active`, found by grep on 2026-10-02:

| Path | Today | After |
|---|---|---|
| `goal_service.update_goal` (`goal_service.py:133-136`) — `PATCH /api/goals/<id>`, reflection apply (`reflection_service.py:1830`) | direct write | `_set_goal_active` |
| `goal_service.delete_goal` (`:146-160`) — `DELETE /api/goals/<id>` (the Archive button), reflection apply (`reflection_service.py:1858`) | direct write | `_set_goal_active` |
| `recycle_service.undo_batch` (`recycle_service.py:266-268`) | direct write | `_set_goal_active(goal, False)` |
| `recycle_service.restore_batch` (`:311-315`) | direct write | `_set_goal_active(goal, True)` |

Every writer of a template's `goal_id` (the marker's hygiene):

| Path | After |
|---|---|
| `recurring_service.update_recurring` `goal_id` branch (`:351-352`) | clears `paused_by_goal_archive` on an **actual** change only |
| `project_service.update_project` #352 cascade (`:271-277`) — moving a project re-points its templates' `goal_id` | clears `paused_by_goal_archive` on the moved templates |
| `recycle_service.purge_batch` — a purged goal's templates get `goal_id = NULL` from `ON DELETE SET NULL` | clears `paused_by_goal_archive` on templates of purged goals |
| `goal_service.hard_delete_goal` | **no change**: it refuses while any template references the goal (`_GOAL_REFERRERS`, `:171-176`), so it never strands a marker |

Also touched: `project_service._set_project_active` (`:300-337`), which
must learn the second marker (§4.2).

## 4. Design

### 4.1 The two markers

`RecurringTask` gets `paused_by_goal_archive` (Boolean, not null,
`server_default` false), the twin of `paused_by_project_archive`.

Each marker means: **this parent is archived, and that is part of why
the template is paused.** A template restarts only when it has no marker
left.

### 4.2 One shared helper, used by both parents

New `recurring_service.cascade_parent_archive(parent: str, parent_id,
archived: bool) -> None`, where `parent` is `"project"` or `"goal"`. It
picks the matching column (`project_id` / `goal_id`), this parent's
marker, and the other parent's marker. Bulk updates, no commit (callers
commit), same as `_set_project_active` today.

- **Archive** (`archived=True`), two updates on templates of this parent:
  1. `is_active = True` → `is_active = False`, set this marker.
  2. Already carrying the **other** marker → also set this marker. (Paused
     by the other parent's archive; without this, unarchiving the other
     parent would wake it while this one is still archived.)

  A template paused by the user (inactive, no marker) is untouched.
- **Unarchive** (`archived=False`), two updates, in this order:
  1. Carrying this marker and **not** the other → `is_active = True`,
     clear this marker.
  2. Carrying this marker (and so the other too) → clear this marker
     only; it stays paused until the other parent comes back.

`project_service._set_project_active` keeps its transition guard and
calls `cascade_parent_archive("project", ...)` in place of its two inline
updates. New `goal_service._set_goal_active(goal, active)` mirrors it: the
only writer of `Goal.is_active`, transition-guarded (a re-sent
`is_active: false` must not re-pause a template the user resumed by
hand), doesn't commit.

`recurring_service` imports neither `project_service` nor `goal_service`,
so the helper creates no import cycle.

### 4.3 Marker hygiene (what clears it)

| Event | `paused_by_project_archive` | `paused_by_goal_archive` |
|---|---|---|
| User changes `is_active` (actual change) | clear | clear |
| User deletes the template | clear | clear |
| `project_id` actually changes | clear | — |
| `goal_id` actually changes (editor or #352 project move) | — | clear |
| Recycle-bin purge of its project | clear (#356) | — |
| Recycle-bin purge of its goal | — | clear |

Clearing a marker never resumes a template on its own. That is #353's
and #356's rule ("purging never turns one back on") and it holds here.
One consequence, accepted: moving a project away from an archived goal
clears its templates' goal marker, and they stay paused; resuming is
the user's call. Same as moving a template between projects since #353.

The purge rule gets simpler than #356's: each purge clears only its own
marker, so a template whose other parent is still archived keeps that
marker and still resumes when that parent comes back.

### 4.4 Migration and backfill

New revision after `r7f8a9b0c1d2`. Adds the column, then a backfill that
applies the rule retroactively, as #353's did:

1. Active templates whose goal is archived → `is_active = false`,
   `paused_by_goal_archive = true`.
2. Templates with `paused_by_project_archive = true` whose goal is
   archived → `paused_by_goal_archive = true`.

`BACKFILL_SQL` stays a module constant (a tuple of the two statements) so
the tests run the exact SQL that ships. Downgrade drops the column and
resumes nothing. Expected prod effect: 0 rows.

### 4.5 The `/goals` Archive confirm

`goalDetailToggleArchive` (`static/goals.js:448`), archive branch only:
fetch `/api/recurring` (active templates), pick those whose `goal_id` is
this goal, and `confirm()` a message naming them. Same wording as
`/projects`, with the tail "They resume when you unarchive the goal." No
templates → no dialog. If the lookup fails → archive without a dialog
(#353's ruling: never block an archive on a confirm lookup). Unarchive
asks nothing.

The pure logic goes in `static/goal_archive_helpers.js` (already loaded on
`/goals`), as `templatesPausedByGoal(templates, goalIds)` and
`goalArchivePauseMessage(paused)`, Jest-tested. It does not reuse
`project_archive_helpers.js`, so `/goals` doesn't load a projects-page
file; the duplicated message builder is about 10 lines.

Templates already paused by their project's archive aren't listed. They
are inactive, so the archive doesn't pause them; it only adds the second
marker.

## 5. Testing plan (all written RED first)

Service tests (`tests/test_goal_archive_templates.py`):

- archive a goal → its active template pauses + gets the goal marker;
  unarchive → resumes, marker cleared
- user-paused template on the goal: untouched by archive and unarchive
- re-sent `is_active: false` doesn't re-pause a template resumed by hand
- `delete_goal`, `update_goal(is_active=False)` and reflection apply all
  take the same path
- **overlap, both orders:** project + goal archived → unarchive either
  one → still paused; unarchive the other → resumes
- overlap where the goal was archived first (template carries only the
  goal marker), then the project → project marker added
- manual resume while both are archived clears both markers; unarchiving
  either parent later leaves it alone
- `goal_id` change clears only the goal marker; re-sending the same
  `goal_id` keeps it
- #352 project move clears the goal marker on moved templates
- delete clears both markers
- recycle undo/restore of an import that created a goal pauses/resumes
  its templates; purge clears only the goal marker and resumes nothing;
  purge with the project still archived keeps the project marker
- backfill SQL: both statements, on SQLite, including a template paused
  by the user (left alone)
- existing #353 / #356 tests stay green unchanged (the project path keeps
  its behavior when no goal is involved)

Jest: `templatesPausedByGoal` (active only, goal match, bad input) and
`goalArchivePauseMessage` (one, several, more than 5, none).

Playwright (`tests/e2e/pages.spec.js`): archive a goal with an active
template → confirm names it → template paused; archive a goal with none
→ no dialog.

## 6. Cascade touch-points

- New column → `architecture_schemas.py` description; `ARCHITECTURE.md`
  PostgreSQL box + the #353 bullet.
- User-visible behavior → `templates/docs.html`: the "Archiving a goal"
  section and the recurring "When its project is archived" section
  (renamed to cover both), fact-checked against code.
- `static/goals.js` + `static/goal_archive_helpers.js` changed →
  `CACHE_VERSION` bump in `static/sw.js` (the push will reload open tabs).
- ADR-038 → consequences extended to goals (an amendment, not a new ADR:
  same decision, second parent).
- CLAUDE.md Phase 6 step 7 + the Regression Report → add "Goals: archive
  pauses template" and "Goals: no-template archive quiet".

## 7. Out of scope (filed, not absorbed)

- **#364** (reflection proposal list doesn't say an archive pauses
  repeating tasks) → note added that goal archives apply too.
- **#369** (import-undo confirm doesn't warn) → note added: goals too.
- Assigning a template to an **already archived** goal or project via the
  `/recurring` editor leaves it running. That's how projects behave today
  too; if it should change, it changes for both, in its own row.

## 8. Decisions

1. Two markers, not one renamed marker (approach A, user 2026-10-02).
2. Clearing a marker never resumes (inherited from #353 / #356).
3. One shared helper in `recurring_service`, so the two parents can't
   drift apart.
4. The goal confirm gets its own helpers in `goal_archive_helpers.js`
   rather than loading the projects page's file on `/goals`.
5. `hard_delete_goal` needs no hygiene: it refuses while templates
   reference the goal.
