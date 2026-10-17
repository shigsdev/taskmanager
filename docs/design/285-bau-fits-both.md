# #285 — BAU goals fit both work and personal

User-reported 2026-06-04 ("stale entries on this utility for BAU"). The root
cause was found on 2026-10-01. The direction was decided by the user on
2026-10-17: **BAU fits both.**

## What was wrong

#142 split the five goal categories in two so a task's type (work /
personal) could pick which goals are relevant:

- work + bau → work-side
- health + relationships + personal_growth → personal-side

BAU ("business as usual" upkeep) isn't work-only, though. The user keeps a
goal called **"Personal BAU"** with category `bau`. Because `bau` counted as
work-side:

- the /utilities project→goal cleanup card (#273) flagged every personal
  project under it as a "cross-side" link. Those are the "stale BAU
  entries" in the report: real, but wrongly flagged;
- the goal pickers on a personal task (the task panel, 💡 Auto-categorize)
  left BAU goals out unless the task already pointed at one;
- a voice memo or scan item routed to a goal with type personal had its
  `bau` category forced to `personal_growth`.

## The rule

`bau` is **neutral**: it fits a work item and a personal item. Every other
category keeps its side. One table holds it, `goal_filter_helpers.js`
`_CATEGORY_TO_TYPE`, where `bau: "both"`, and one predicate,
`categoryFitsType(category, type)`. Python mirrors it in `scan_service`.

## The surface (every place the split is used)

| Where | Was | Now |
|---|---|---|
| `goalFilterHelpers.filterGoalsByType` → task panel goal picker (`app.js` `goalsForDropdown`), 💡 Auto-categorize goal picker (`inbox_categorize.js`) | BAU goals only for work | BAU goals for both |
| `goalFilterHelpers.auditProjectGoalLinks` → /utilities cleanup card | personal project + BAU goal = cross-side | never cross-side |
| `scan_service` voice/scan item check (`_VOICE_WORK_CATEGORIES`) | personal + bau → personal_growth | personal + bau kept |
| `scan_service` voice prompt (category↔type rule) | personal → health / personal_growth / relationships | adds bau to both lists |
| `typeForCategory` | bau → "work" | bau → "both" (its only callers are the two helpers above and tests) |

Not affected: goals carry no type, so no server-side link check pairs a
goal with a task's type (#475's checks are project-type only). `/goals`
filters by category, not side.

## This ship

- `goal_filter_helpers.js`: the table, `categoryFitsType`, the three
  helpers using it.
- `scan_service.py`: `_VOICE_NEUTRAL_CATEGORIES = {"bau"}`; the check and
  the prompt text.
- Help: the goal-category explanation, if one states the split (checked
  against `docs.html`).
- CACHE_VERSION bump.

## Tests

- Jest `goal_filter_helpers` (red before): `bau` → "both"; a BAU goal is in
  both `filterGoalsByType(…, "work")` and `(…, "personal")`; a personal
  project on a BAU goal isn't cross-side, while a personal project on a work
  goal still is (the quiet case).
- pytest voice normalisation (red before): personal + bau stays bau; work
  + health still becomes work; personal + work still becomes personal_growth.
- e2e: a personal task's goal picker lists a BAU goal; the /utilities card
  doesn't flag a personal project on a BAU goal.
