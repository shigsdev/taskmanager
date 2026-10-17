# #293 — /calendar: a "+" to add a task straight into a section

User-flagged 2026-06-21: "add a button next to the title of the panel (for
example, tomorrow) to be able to create a task that automatically goes into
that day or time period."

## What's already done

- **Day cells.** #454 (2026-10-14) gave every day cell a visible "+"
  (`.calendar-cell-add`) that opens a new task dated that day. That is the
  "day" half of this row. Tomorrow is a day cell on the grid, so the user's
  own example is covered.
- **Section headers.** #292 / #296 / #309 later split the Unscheduled side
  panel into four always-present sections: Inbox, This Week · no day, Next
  Week · no day, Backlog & Freezer. The row's "time period" half is about
  these sections, and they had no add button.

## This ship

- Each Unscheduled section header gets a "+" (`.calendar-group-add`, which
  shares the day cell's `.calendar-cell-add` look and its 44px mobile size).
  Its name is "Add a task to <section>".
- It calls `taskDetailOpenNew("", "work", "", group.dropTier)`. That is a
  new optional fourth argument, `prefillSection`, and the panel's Section
  starts on it with no date. Backlog & Freezer uses its drop tier, Backlog,
  the same section a drop there files into. A pre-filled date still wins and
  picks its own section (#386), so the day "+" is unchanged.
- The header is a flex row with the "+" on the right, like a day cell's.
- Help → Calendar: one sentence. CACHE_VERSION bump.

## Not in scope

The #445 "Later · after <date>" group is not a section and isn't a drop
target, so it gets no "+".

## Tests

`tests/e2e/calendar_group_add.spec.js`, red before the fix (2 of 3; the 3rd
is the quiet case), at both viewports:
- Next Week's "+" opens a task with Section = Next Week and no date; Save
  files it there undated (checked through the API) and it shows in the
  section;
- all four sections' "+" pick their section (Backlog for Backlog & Freezer);
- a day's "+" still dates the task.

`keyboard_open.spec.js` (#454) and `mobile_tap_targets.spec.js` still pass.
