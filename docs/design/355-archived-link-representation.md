# Spec #355 — An archived project/goal link must stay representable

**Filed:** 2026-10-01 (found during #353's asymmetry sweep)
**Status:** specced, not yet built
**Blocks:** #353 (archiving a project pauses its templates)
**Ships before:** #353
**Backend changes:** none. No migration, no new route, no schema change.

---

## 1. Problem

Every select that restores a stored `project_id` / `goal_id` is populated
from an **active-only** list. When the stored value is archived, no
`<option>` matches it, `selectedIndex` goes to `-1`, and the select reads
back `""`. The code then treats "not in my option list" as **"the user
cleared this field"** and writes the clearing to the database.

Proven against the shipped `task_detail_payload.js` under jsdom — not
inferred from reading:

```
project options    : [ '', 'live-1', 'live-2' ]
assigned           : archived-cop
reads back as      : ""  (selectedIndex -1)
user changed nothing. detailFormDiffersFromSnapshot -> true
payload: { "project_id": null, "goal_id": "goal-ai", "status": "active", ... }
```

Two consequences, both on a save where the user edited nothing:

1. **The project link is destroyed.** `project_id: null` →
   `task_service.update_task` nulls the column.
2. **A completed task is resurrected onto the active board.** The phantom
   `project_id` diff makes `detailFormDiffersFromSnapshot` return true,
   which trips the #148 revival branch and sends `status: "active"`. This
   is exactly the case #148's own comment says it exists to prevent:
   *"No-op saves on completed tasks (no field changes) leave status alone
   — preserves the case where a user just opens a completed task and
   clicks Save absent-mindedly."*

The goal link survives, but only by accident of statement order:
`task_service.py:696` nulls `goal_id` when the project goes null, and
`:699` then re-asserts it from the payload. It dies only when the goal is
archived too.

**Prod exposure:** 270 tasks across 8 archived projects (262 of them also
carrying a `goal_id`). All 270 are completed, so every one is also a
resurrection candidate. Plus 2 recurring templates on an archived project.

This is the #57 bug class — a stale assumption in a dropdown silently
dropping `project_id` — with "archived" substituted for "cross-type".

## 2. Goal

A stored link to an archived row must **round-trip** through the editor
untouched: populate → set → read → save leaves the column as it was. The
user should be able to *see* that the link points at something archived,
and should not be able to newly assign to it.

## 3. Affected surfaces (the complete list)

Five selects across three files. Each restores a stored value from an
active-only list.

| File | Select | Stored value | Prod exposure |
|---|---|---|---|
| `static/app.js:2865` | `detailProject` | `Task.project_id` | **270 tasks** |
| `static/app.js:2803` | `detailGoal` | `Task.goal_id` | ≤1 task |
| `static/recurring.js:219` | `recurEditProject` | `RecurringTask.project_id` | **2 templates** |
| `static/recurring.js:219` | `recurEditGoal` | `RecurringTask.goal_id` | 0 |
| `static/projects.js:639` | `projectGoalId` | `Project.goal_id` | 0 |

`detailGoal` is the least broken of the five, and understanding *why it
still breaks* is what pins the fix down. `taskDetailOpen` already passes
`task.goal_id` into the #272 `keep` set (`:2510`), so the right id is
in hand. But `keep` is unioned into a filter over `allGoals`
(`goalFilterHelpers.goalsForDropdown(allGoals, filterType, keep)`), and
`allGoals` is active-only — there is no row to keep. **The helper needs
the archived row, not just its id**, because it also has to render a
label. That is the difference between #272's fix and this one.

Both functions already end with the same restore guard:

```js
if (currentValue && filtered.some((x) => x.id === currentValue)) {
    sel.value = currentValue;
}
```

So the lever is small: get the archived row into the list that loop
renders, and the existing guard re-applies the value on its own.

**Explicitly NOT in scope — eight chooser surfaces** that read the same
active-only lists but never restore a stored value (they build a pick-list
from scratch, so active-only is correct): `import.js`,
`inbox_categorize.js`, `plan.js`, `voice_memo.js`, `utilities.js`,
`weekly_focus.js`, `goals.js`, and `projects.js`'s bulk-edit menus.

## 4. Design

### 4.1 One pure helper

New `static/archived_option_helpers.js`, dual-export (`window.` +
`module.exports`) per anti-pattern #3.

The helper decides **which rows and in what state** — never how they are
labelled. That split matters: the five selects do not share a label
format (projects render `p.name`, goals render `` `${g.title} (${g.category})` ``),
so a helper that owned labels would have to grow a format parameter per
caller and would stop being pure logic.

```js
optionRowsPreservingValue({ live, archived, currentId })
  -> [{ row, state }]      // state: "live" | "archived" | "missing"
```

- Returns every `live` row first, `state: "live"`, in the order given.
- **Only if** `currentId` is truthy and absent from `live`, appends one
  entry for it:
  - found in `archived` → `{ row: <the archived row>, state: "archived" }`
  - in neither list → `{ row: { id: currentId }, state: "missing" }`
    (a genuinely dangling id; prod has 0, but collapsing it to `null`
    would be the same data loss this spec exists to stop)
- No `currentId`, or `currentId` already live → no appended entry, so the
  common path produces exactly today's list.
- The appended entry **bypasses the caller's type filter** deliberately:
  the point is to represent what is stored, and a stored cross-type
  archived value is still stored.

Each caller then renders its own label and appends the suffix:

| `state` | Label | `disabled` |
|---|---|---|
| `live` | caller's existing format, unchanged | no |
| `archived` | caller's format + `" (archived)"` | yes |
| `missing` | `"(unavailable)"` | yes |

Callers keep doing their own type filtering on `live` before calling.
The helper knows nothing about types, names, or categories — which is
what makes its five Jest cases cheap to write and read.

### 4.2 Disabled, not enabled

The injected option is `disabled`. A disabled `<option>` still accepts a
programmatic `select.value` and survives sibling re-renders — probed under
jsdom before committing to this design:

```
A. disabled option, value set programmatically
   selectedIndex : 2
   value         : "archived-cop"
   survives      : true
   after sibling churn: "archived-cop"
```

So the value round-trips while the user cannot newly assign to an
archived row. **This is a judgment call worth flagging:** it means moving
a task back onto an archived project requires unarchiving the project
first. That seems right — archived means out of play, and the "— None —"
option stays enabled so deliberately clearing the link is still possible
— but it is the one decision here that could reasonably go the other way.

### 4.3 Getting the archived rows client-side

No new endpoint. `?is_active=all` already returns both on
`/api/projects` and `/api/goals` (`projects_api.py:48-54`,
`goals_api.py:74-80`).

- **`app.js`** — change the two loads at `:154` / `:167` to fetch
  `?is_active=all` and split, rather than adding round trips:
  ```js
  const all = await apiFetch(PROJECTS_API + "?is_active=all");
  allProjects = all.filter((p) => p.is_active);      // unchanged meaning
  archivedProjects = all.filter((p) => !p.is_active);
  ```
  `allProjects` **must** keep its active-only meaning. It has **nine**
  reader sites (`:137`, `:782`, `:1320`, `:1584`, `:1745`, `:2653`,
  `:2819`, `:2872`, `:3430`, `:3538`), three of which are the independent
  halves of the PR63 #129 fix — `_sweepStaleFilterIds` (`:137`), the task
  badge (`:1320`) and the filter bar (`:1584`). Widening the variable
  would silently change all nine and reintroduce #129's phantom badges
  and ghost filters. Adding a second variable changes exactly the two
  call sites that opt in.
- **`recurring.js`** — the three loads are one `Promise.all` at
  `:113-120`; add `?is_active=all` to the projects and goals legs and
  split the same way.
- **`projects.js`** — nothing to fetch: `:61-62` already loads **both**
  `/api/projects?is_active=all` and `/api/goals?is_active=all`, and
  `populateGoalDropdown` throws the archived goals away at `:643`.
  Cheapest of the three.

### 4.4 Wiring: six call sites, one rule

`taskDetailPopulate{Projects,Goals}` are called from six places, and they
differ in whether the select already holds the value:

| Call site | Context | Where the current id comes from |
|---|---|---|
| `:161` / `:174` | background refresh after load | `sel.value` — panel may be open, value already set |
| `:2503` / `:2510` | `taskDetailOpen` | **must be passed in** — the select is empty; the value is set afterwards at `:2504` / `:2511` |
| `:2616` / `:2618` | type-change handler | `sel.value` |
| `:2650` | project-change handler | `sel.value` |

One rule covers all six: `const currentId = explicitCurrentId || sel.value`.

`taskDetailPopulateGoals` already receives `task.goal_id` (as
`extraKeepIds`) so it only needs the row lookup. **`taskDetailPopulateProjects`
takes only `filterType` — that missing parameter is the hole**, and
`taskDetailOpen` must start passing `task.project_id`. `extraKeepIds`
stays as-is; it is the #272 cross-type concern, not this one.

One more spot: `:2819-2820` builds the project→goal keep by searching
only `allProjects`, so an archived project yields `undefined` and its
linked goal is never kept. It degrades quietly today; once
`archivedProjects` exists the lookup should cover both.

### 4.5 One incidental cleanup

`projects.js:642` builds the dropdown with `innerHTML`. The fix touches
that function, and the repo's PreToolUse hook blocks any edit containing
`innerHTML`, so it converts to `replaceChildren` + `createElement` as part
of this change. Not scope creep — it is unavoidable to edit the line.

## 5. Testing plan

**Jest on the helper** — assert OUTPUTS, never source strings
(anti-pattern #3):

- current value is live → no injection; option list identical to `live`
- current value archived → one appended option, `disabled`, label carries
  `(archived)`
- current value dangling → one appended option, `disabled`, `(unavailable)`
- no current value → no injection
- archived current value of the *wrong type* → still injected (the type
  filter must not hide it)

**Jest on the round-trip** — the regression that would have caught this:

- populate from an active-only list → set the value to an archived id →
  read it back → assert it is the archived id, **not** `""`
- the same round-trip driven the *other* way — populate with the id
  passed in as an argument (the `taskDetailOpen` ordering, where the
  select is still empty) — because those are two different code paths
  through the same function and only one of them existed before
- a re-populate with no argument (the `:161` / `:174` background-refresh
  shape) must not drop a value the select already holds
- feed the resulting form state to the real `detailFormDiffersFromSnapshot`
  and assert **false** — this is the assertion that pins the
  completed-task resurrection shut, and it fails today

**Playwright local** — open a task on an archived project, save without
editing, assert `project_id` is unchanged and `status` is still completed.

**Phase 6** at desktop 1280×800 and mobile 375×812 on `/completed` (a
real archived-project task), `/recurring` (the CoP template) and
`/projects` (project detail goal select): the archived option renders,
reads as archived, cannot be picked, and a no-op save changes nothing.
Viewport parity row at both.

## 6. Cascade touch-points

Walked against CLAUDE.md's table:

| Row | Action |
|---|---|
| New static asset | `static/sw.js` `APP_SHELL` + `health.py` `EXPECTED_STATIC_FILES` + **`CACHE_VERSION` v257 → v258** |
| New static asset | `<script>` tag on every template that loads `app.js`'s detail panel — calendar, completed, docs, goals, index, projects, recurring, tier (8, matching `task_detail_payload.js`) |
| User-visible behavior | `templates/docs.html` — an archived project/goal now shows as "X (archived)" and cannot be newly assigned. Needs the fact-check table (claim → `file:line`) |
| New column / model / route / env var / job | **none triggered** — no backend change |
| Security-sensitive refactor | not triggered |

`ARCHITECTURE.md` gets one line next to the `goal_archive_helpers.js`
note at `:606` (#349's, the nearest precedent).
`scripts/arch_sync_check.py` does not gate static helper filenames, so
this is for the reader, not the gate.

**Verified against code, not memory** — every line number above was
re-checked before this spec was finalised. Three were wrong on the first
pass: `recurring.js`'s loads are at `:113-120` (not `:115-116`),
`_sweepStaleFilterIds` reads `allProjects` at `:137` (not `:134`), and
`allProjects` has nine readers rather than the three I first cited. The
third one is the reason §4.3 adds a variable instead of widening one.

## 7. Out of scope (filed, not absorbed)

The sweep that found this found more. None of it ships here:

- **#353** — archiving a project pauses its recurring templates. Ships
  immediately after; this spec is its prerequisite.
- **#356** — `recycle_service.undo_batch` nulls `Task.project_id` for the
  projects it archives but not `Task.goal_id` for the goals.
- **#357** — projects have no `/references` endpoint and no permanent
  delete; #349's guard pattern stopped at the goal.
- **No backfill.** There is nothing to repair: the 270 task rows and 2
  template rows are *correct* under the preserve-links rule. This is a
  representation fix, not a data fix. That is the whole reason it ships
  before #353 rather than after.

Four more surfaced *while implementing this spec*, after the list above
was written. Also filed, also not absorbed — each would have turned this
one row into several:

- **#358** — `/completed` renders an empty list, because `init()`'s
  `isBoard` gate (#270) returns before `loadCompletedTasks()`. Hit while
  writing the Playwright test, which could not find its card. The test
  was retargeted to the board's Completed section — the surface the user
  actually reaches these tasks through — rather than fixing the page here.
- **#359** — nothing stops two `static/*.js` files declaring the same
  top-level identifier. Hit for real: this spec's own helper ended with
  `const _api`, colliding with `inbox_categorize_helpers.js`'s `var _api`
  and killing that file on `/` with a SyntaxError. The collision is fixed
  here (no intermediate top-level binding, following
  `goal_archive_helpers.js`); the row is the missing **gate** plus the
  surviving `dueDateForTier` duplicate.
- **#360** — the pytest gate can report red with every test passing, on a
  Windows teardown `PermissionError` that fires before the coverage
  summary. Cost two full suite runs here. Workaround documented in
  CLAUDE.md in this commit; the row is the permanent fix.
- **#361** — the *read-only* surfaces disagree with each other on how an
  archived link is shown. This spec gave the five selects one rule;
  `/recurring`'s row meta hand-rolls the same `" (archived)"` suffix with
  its own fallback (`recurring.js:32-45`), and `/projects`' card goal line
  (`projects.js:503`) applies no marker at all — so a card can read
  `Goal: Ship the 2026 reorg comms` while the select beside it reads
  `Ship the 2026 reorg comms (archived)`. Found in this spec's own Phase 6.
  Pre-existing (`projectsGoals` was already `is_active=all`), no data at
  risk, and out of scope by decision 5 below — selects, not labels.

## 8. Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Pause-vs-detach for templates is **#353's** call, not this spec's | this spec only makes the stored value survive editing, whatever it is |
| 2 | Injected option is `disabled` | archived means out of play; probed to confirm the value still round-trips |
| 3 | Dangling ids render `(unavailable)` and are preserved | collapsing them to `null` is the bug being fixed |
| 4 | `allProjects` / `allGoals` stay active-only | they feed the three readers that fix PR63 #129 |
| 5 | Fix the five restoring selects, not the eight choosers | a chooser has no stored value to lose |
