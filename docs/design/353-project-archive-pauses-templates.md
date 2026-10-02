# Spec #353 — Archiving a project pauses its repeating tasks

**Filed:** 2026-10-01 (found while shipping #352)
**Status:** specced, not yet built
**Unblocked by:** #355 (shipped 2026-10-01, `6f2f268`). Preserving
`Task.project_id` on archive is only safe now that the detail panel
stops silently nulling an archived link.
**Backend changes:** one column + migration (with a data backfill), a
shared service-layer cascade, and removal of the task-detach in
`delete_project` (reverses PR63 #129, so it needs an ADR).

---

## 1. Problem

Archiving a project does not stop its repeating tasks. A template
(`RecurringTask`) carries its own `project_id`, nothing on the archive
path touches it, and `spawn_today_tasks` only checks the template's own
`is_active`. So a template keeps creating fresh tasks inside a project
the user has put away.

**Live on prod:** two templates sit on the archived "Community of
Practice" project. *"menti survey for april cop session"* is still
active and still spawning. *"check CoP survey new participants"* is
already inactive.

The sweep that #353's row asked for found that the problem is wider than
one forgotten table. **The two archive paths don't agree with each other
either:**

| Path | Call | Sets `is_active=False` | Detaches tasks | Touches templates |
|---|---|---|---|---|
| Detail panel **Archive** | `PATCH /api/projects/<id>` → `update_project` | yes | **no** | no |
| Bulk **Archive** | `PATCH /api/projects/bulk` → `update_project` per row | yes | **no** | no |
| Bulk **Delete** | `DELETE /api/projects/bulk` → `delete_project` per row | yes | **yes** (PR63 #129) | no |
| Single `DELETE` (API only; the UI has no button) | `delete_project` | yes | **yes** | no |
| Reflection proposal (update / delete) | `reflection_service.py:1830-1862` → `update_project` / `delete_project` | yes | depends on which | no |

So the button actually labelled **Archive** cascades *less* than the
Delete beside it. That is why prod has 270 tasks still pointing at 8
archived projects: they were archived through the button, which never
detached anything.

## 2. Goal

One rule, applied identically by every path that archives or unarchives
a project:

1. **Archiving pauses the project's currently-active templates** and
   remembers which ones it paused.
2. **Unarchiving resumes exactly those**, and never a template the user
   had paused or deleted themselves.
3. **Archiving leaves task links alone**, on every path. Tasks keep
   `project_id` (and `goal_id`, as today).
4. Before archiving from `/projects`, **the user is told which
   repeating tasks will pause**, but only when there are any.

## 3. Affected surfaces (the complete list)

**Server: where the rule lives**

| # | Surface | File | Change |
|---|---|---|---|
| S1 | `update_project` `is_active` branch | `project_service.py:279-282` | call the shared cascade on an actual transition |
| S2 | `delete_project` | `project_service.py:300-325` | call the shared cascade; **remove** the task-detach |
| S3 | `bulk_update_projects` / `bulk_delete_projects` | `project_service.py:328-370` | none. They reuse S1/S2 per row |
| S4 | Reflection apply path | `reflection_service.py:1830-1862` | none. Calls S1/S2, so it inherits the cascade |
| S5 | `update_recurring` | `recurring_service.py:307-392` | flag hygiene (§4.3) |
| S6 | `delete_recurring` | `recurring_service.py:395-402` | flag hygiene (§4.3) |
| S7 | Recurring bulk patch / delete | `recurring_api.py:124-195` | none. They reuse S5/S6 per row |

**Schema**

| # | Surface | Change |
|---|---|---|
| M1 | `RecurringTask` model (`models.py:314`) | new `paused_by_project_archive: bool`, NOT NULL, default False |
| M2 | Alembic migration, parent `q6e7f8a9b0c1` | add column + backfill (§4.5) |

**Client: where the user is told** (all on `/projects`)

| # | Surface | File | Change |
|---|---|---|---|
| C1 | Detail panel Archive toggle | `projectDetailToggleArchive`, `static/projects.js:789` | confirm before archiving, only if templates would pause. No confirm on unarchive |
| C2 | Bulk **Archive** | `static/projects.js:937-942` | fold the template names into the existing confirm |
| C3 | Bulk **Delete** | `static/projects.js:944-957` | fold the template names into the existing confirm |

The pure logic (which templates a given set of projects will pause, and
the confirm text) goes in a new dual-export helper,
`static/project_archive_helpers.js` (anti-pattern #3).

**Verified to need no change** (task links are preserved, so every
reader that resolves `project_id` to a name had to be checked):

- Board badge: resolves against active-only `allProjects`
  (`static/app.js:1345`), so an archived project renders no badge. This
  is the guard that fixed PR63's "phantom label" half.
- Board filter: `_sweepStaleFilterIds` (`static/app.js:142`) drops dead
  ids. This fixed PR63's "ghost filter entry" half.
- Detail-panel pickers: #355 renders an archived link as a disabled
  `(archived)` option and keeps it on save.
- Digest: guards `t.project.is_active` (`digest_service.py:211`).
- Reflection, weekly planner, weekly focus, inbox categorize: all
  build their project lookup from `select(Project).where(is_active)`
  (`reflection_service.py:112`, `:161-162`; `weekly_planner_service.py:292`;
  `weekly_focus_service.py:478`; `inbox_categorize_service.py:153`), so an
  archived id finds no name.

## 4. Design

### 4.1 One shared cascade

```python
# project_service.py
def _set_project_active(project: Project, active: bool) -> None:
    """The ONLY place a project's is_active changes. Pauses/resumes its
    templates on an actual transition; a no-op write does nothing."""
    if project.is_active == active:
        return
    project.is_active = active
    if not active:
        # Pause only what is running now, and remember we did it.
        RecurringTask.query.filter_by(
            project_id=project.id, is_active=True,
        ).update(
            {"is_active": False, "paused_by_project_archive": True},
            synchronize_session=False,
        )
    else:
        # Resume only what WE paused.
        RecurringTask.query.filter_by(
            project_id=project.id, paused_by_project_archive=True,
        ).update(
            {"is_active": True, "paused_by_project_archive": False},
            synchronize_session=False,
        )
```

`update_project` (when `is_active` is in the payload, after its bool
validation) and `delete_project` both call it. The function doesn't
commit; its callers already do.

**Only on an actual transition.** The same rule as #350's goal cascade.
A PATCH that re-sends `is_active: false` for an already-archived project
must not re-pause a template the user resumed by hand after archiving.

### 4.2 `delete_project` stops detaching tasks

`delete_project` becomes `_set_project_active(project, False)` plus a
commit, which makes it identical to the Archive button. The PR63 #129
detach is removed. Its two symptoms are fixed on the read side (§3,
"verified to need no change"). Keeping it would mean:

- the two archive paths keep disagreeing, and
- unarchiving through Delete can never be undone. The tasks are gone
  from the project for good, while the same project archived through the
  button gets its tasks back.

Reversing an audit fix on purpose gets an ADR: **ADR-038**, "Archiving a
project preserves task links". It records the PR63 rationale, why both
symptoms no longer depend on the detach, and the prod evidence (270
tasks already preserved by the button path, with no reported phantom
labels).

### 4.3 Flag hygiene

`paused_by_project_archive` means exactly one thing: *"this template is
paused only because its project was archived, and should resume when
the project comes back."* Anything the user does that overrides that
intent clears the flag:

| Event | Where | Flag |
|---|---|---|
| Archive pauses it | `_set_project_active(False)` | set True |
| Unarchive resumes it | `_set_project_active(True)` | cleared |
| `is_active` **actually changes** via `update_recurring` (Resume, or bulk Pause/Resume) | S5 | cleared |
| `project_id` **actually changes** via `update_recurring` | S5 | cleared. It stays paused; the user resumes it on its new project themselves |
| Template deleted | `delete_recurring` (S6) | cleared **unconditionally**. Delete writes the same `is_active=False` as Pause, so without this, unarchiving would resurrect a template the user deleted |

The "actually changes" guard matters for the same reason as §4.1: if a
save that re-sends the current value counted as an override, it would
silently cancel the resume.

### 4.4 Telling the user (C1–C3)

The helper takes the active templates and a set of project ids, and
returns the templates that will pause plus a confirm message:

- **0 templates → no extra text.** C1 then asks nothing at all, which
  matches today's behavior and #351's "the quiet case stays quiet".
  C2/C3 keep their existing confirm unchanged.
- **1+ templates →** the names, and the promise:
  *"This will pause N repeating task(s): "A", "B". They resume when
  you unarchive the project."* Long lists are capped with "and N more".
- **Unarchive → no confirm.** Resuming restores a prior state; it is
  not a decision.

Data source: `GET /api/recurring` (default = active only, which is
exactly the set the cascade will pause), fetched when the user clicks,
not on page load. **If the fetch fails, the archive proceeds** with the
plain confirm (or none, for C1). The server cascade is the control; the
message is only information, and a network blip mustn't block archiving.

### 4.5 Migration + backfill (fixes the prod templates)

One Alembic revision on top of `q6e7f8a9b0c1`:

1. Add `recurring_tasks.paused_by_project_archive BOOLEAN NOT NULL
   DEFAULT false`.
2. Backfill: every **active** template whose project is **archived** is
   paused with the flag set, exactly as if the cascade had run when its
   project was archived:
   ```sql
   UPDATE recurring_tasks SET is_active = false,
          paused_by_project_archive = true
   WHERE is_active = true
     AND project_id IN (SELECT id FROM projects WHERE is_active = false)
   ```
   This stops *"menti survey…"* firing on the deploy itself, with no
   manual prod step. *"check CoP survey…"* is already inactive, so it is
   left alone and stays unflagged: we can't know who paused it.
3. Downgrade drops the column and does **not** resume anything. A
   rollback shouldn't restart tasks the user has been told are paused.

## 5. Testing plan (all written RED first)

**pytest: cascade (`tests/test_project_archive_templates.py`, new)**

1. PATCH archive pauses an active template on the project and sets the flag.
2. PATCH archive leaves an already-paused template paused **and unflagged**.
3. PATCH unarchive resumes flagged templates only; a manually paused one stays paused.
4. DELETE archives with the same template effect as PATCH (parity test, run both ways).
5. Bulk PATCH and bulk DELETE both cascade per row.
6. A no-op PATCH (`is_active: false` on an archived project) doesn't re-pause a template the user resumed.
7. Templates on *other* projects are untouched.
8. Reflection apply path (`update` with `is_active: false`, and `delete`) pauses templates. This guards the service-layer placement.
9. Archive preserves `Task.project_id` and `Task.goal_id` on both paths.

**pytest: hygiene**

10. Resume via `update_recurring` clears the flag; the next unarchive doesn't touch it.
11. Moving a paused-by-archive template to another project clears the flag; unarchiving the old project doesn't resume it.
12. Deleting a paused-by-archive template clears the flag; unarchiving doesn't resurrect it.
13. Re-sending the same `is_active` / `project_id` does **not** clear the flag.

**pytest: migration**

14. Backfill pauses + flags an active template on an archived project; leaves inactive ones and active-project ones alone. There is no existing migration-data test pattern in the repo, so this ship sets one up: the migration exposes its UPDATE as a module-level `BACKFILL_SQL` constant, and the test loads the revision file with `importlib` and runs that exact string against seeded rows in the SQLite test DB. The same text runs on Postgres. It uses only `true`/`false` literals and a subquery, both of which SQLite ≥ 3.23 accepts. This tests the shipped SQL, not a copy of it.

**Updated (they assert the PR63 behavior being reversed)**

- `tests/test_projects_api.py:499` → asserts tasks **keep** `project_id`.
- `tests/test_project_goal_cascade.py:267` → asserts `project_id`
  preserved, `goal_id` still preserved.

**Jest: `tests/js/unit/project_archive_helpers.test.js` (new)**

- Filters to templates on the given projects; ignores other projects
  and null `project_id`.
- 0 → no message; 1 → singular wording; N → plural; >cap → "and N more".
- Template titles that need no escaping still render verbatim (output
  goes to `confirm()`, which is plain text, so no HTML is involved).
- Multiple projects (bulk) aggregate correctly.

**Playwright (`tests/e2e/pages.spec.js`)**

- Archive a project with a template: the confirm names it; accept →
  template inactive; unarchive → active again.
- Archive a project without templates: **no dialog**.

**Phase 6 (desktop + mobile):** C1/C2/C3 dialogs, the unarchive
round-trip, the 0-template silent case, viewport parity. Add the rows to
CLAUDE.md's regression checklist and report template.

## 6. Cascade touch-points

| CLAUDE.md row | Action |
|---|---|
| New column on an existing model | `_SCHEMA_DESCRIPTIONS["recurring_tasks"]` entry; ARCHITECTURE.md PostgreSQL box |
| New static asset | `sw.js` `APP_SHELL`, `health.py` `EXPECTED_STATIC_FILES`, `CACHE_VERSION` bump, `<script>` in `projects.html` |
| User-visible behavior | `templates/docs.html`: the Projects section (`:2114`, "Archiving a project does not…") and the Recurring section. Fact-check table at review |
| Security-sensitive / reversed decision | ADR-038 (reverses PR63 #129) |
| UI change | Phase 6 both viewports; new checklist rows |

## 7. Out of scope (filed, not absorbed)

- **#363 (new)**: `/recurring` can't show a paused template.
  `recurring.js:137` asks for `?active_only=false`; the API reads only
  `?all=1` (`recurring_api.py:69`), so the page has listed active
  templates only since #63. Pause makes a template vanish and Resume is
  unreachable. It is entangled with a second defect, which is why it is
  not a one-character fix here: `delete_recurring` writes the **same**
  `is_active=False` as Pause, so correcting the param would surface
  every deleted template as "PAUSED". It needs a real deleted state.
  **Consequence for #353:** a template paused by archive also vanishes
  from `/recurring` until the project is unarchived. That is acceptable
  because the confirm says so ("they resume when you unarchive the
  project"), and it is how a manual Pause behaves today.
- **#364 (new)**: the reflection-proposal list doesn't say a proposed
  project archive/delete will pause templates. The **cascade** reaches
  that path (S4, test 8). Only the *message* doesn't, because the label
  is built from Claude's proposal text and would need server-side
  enrichment at analysis time. The user still confirms every proposal
  by checkbox + Apply.
- **#356 (existing)**: `recycle_service.undo_batch` / `restore_batch`
  archive and restore imported projects by writing `is_active` directly,
  bypassing `_set_project_active`, and they also null task links.
  Routing them through the cascade is #356's "apply whichever rule #353
  settles to all three recycle paths". Deliberately a second ship.
- **#357 (existing)**: projects have no permanent delete or
  `/references` endpoint.
- A spawn-time guard ("skip templates whose project is archived") was
  considered and **rejected**. It would create a second rule that makes
  a template look active while never firing, and it would hide exactly
  the cascade-bypass bugs #356 is about.

## 8. Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Archive **pauses** templates; it doesn't detach them | user decision 2026-10-01. A detached template still fires |
| 2 | Track with a boolean flag, not a `paused_by_project_id` FK | the template's own `project_id` already names the project; hygiene clears the flag whenever that changes |
| 3 | The cascade lives in the service layer, in one function | the reflection apply path calls the service directly and would bypass a route-level cascade |
| 4 | Fires on an actual transition only | the same rule as #350; a re-sent value mustn't undo a manual resume |
| 5 | Remove the task-detach from `delete_project` | the two paths must agree, and the detach makes Delete-then-unarchive lossy; ADR-038 |
| 6 | Confirm only when templates would pause; never on unarchive | the quiet case stays quiet (#351) |
| 7 | A failed impact fetch doesn't block the archive | the server cascade is the control; the dialog is information |
| 8 | Backfill in the migration, not a manual script | no prod action for the user; runs exactly once on deploy |
| 9 | Downgrade doesn't resume | a rollback shouldn't restart work the user was told is paused |
| 10 | Reflection-path *messaging* is out (#364); the reflection-path *cascade* is in | the original shape said "a confirm on all four call sites". The fourth one (reflection) has no dialog to extend, and its human gate already exists |
