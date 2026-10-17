# #361 — One rule for an archived project/goal link, everywhere it's shown

Found 2026-10-01 during #355's Phase 6.

## What was wrong

#355 gave every picker one rule: a link to an archived project or goal
renders as its name plus `" (archived)"`. The read-only places that show the
same link didn't follow it, and there were three conventions for one fact:

- **Shown as if live.** The `/projects` card's linked-goal line
  (`projects.js`) reads `Goal: <title>` for an archived goal, while the
  panel's picker beside it reads `<title> (archived)`.
- **Hidden.** A board card's project and goal badges (`app.js taskCardEl`)
  look the link up in the active lists only, so an archived link just
  disappears. The digest email does the same on purpose (PR62 audit #14,
  "dead label").
- **Marked, but by hand.** `/recurring`'s `_projectName` / `_goalTitle` and
  the board's Work-view group header (`filterHelpers.groupTasksByProject`,
  #434) each append their own `" (archived)"` string.

## The rule

**A link that is stored is shown. An archived target reads
`<name> (archived)`.** Nothing is hidden and nothing pretends to be live.
That is the rule #355 set for pickers and #434 set for the Work view; this
applies it to the rest. (The PR62 "dead label" worry was a name you couldn't
tell from a live one; the marker answers it.)

**Not in scope:** lists of a parent's children (`/goals`' "Projects (N)" is
active projects only, by #24's decision, and archived ones are managed on
`/projects`); filter chips (a filter on an archived id is swept by
`_sweepStaleFilterIds`); bulk "move to" menus (choices, not links).

**The digest email keeps its own rule.** It drops an archived project's
name and a DONE goal's title from a task line on purpose (PR62 audit #14),
and `tests/test_digest.py::TestDigestInactiveProjectAndDoneGoalFiltered`
pins that. An email is a summary of what's live, read away from the app,
with no picker beside it to disagree with — so the "two answers on one
screen" problem this row is about can't happen there. Reversing an
explicit earlier decision is not this ship's to make; left as is.

## This ship

- `archivedOptionHelpers.linkLabel(id, rows, textOf)`: `null` for no id or
  an unknown id; `textOf(row)` for a live row; `textOf(row) + ARCHIVED_SUFFIX`
  for `is_active === false`. The one definition; Jest-tested.
- Callers: `projects.js` goal line, `app.js` card project + goal badges,
  `recurring.js` `_projectName` / `_goalTitle`, `filterHelpers`'s group label
  uses `ARCHIVED_SUFFIX`.
- A board badge for an archived link gets `.badge-archived-link` (muted).
- CACHE_VERSION bump.
