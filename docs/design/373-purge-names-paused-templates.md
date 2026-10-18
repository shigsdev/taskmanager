# #373 — Purge and Empty Bin name the repeating tasks that stay paused

Status: building 2026-10-17 on `fix/373`.

## 1. What's left of the row

#373 had two halves. The project counts (Restore / Purge / Empty and the
page totals) shipped in #478 (`6d0d282`). This ship is the other half:
Purge doesn't say that a repeating task the undo paused stays paused for
good once its project or goal is hard-deleted. Help already says it
("purging never turns one back on"); the dialog doesn't.

## 2. What purge does today (`recycle_service.purge_batch`)

- Clears `paused_by_project_archive` on templates whose `project_id` is in
  the batch, and `paused_by_goal_archive` on templates whose `goal_id` is
  in the batch. `is_active` is left alone.
- The DB's `ON DELETE SET NULL` then clears the template's `project_id` /
  `goal_id`.
- A template that still carries the OTHER marker (its goal or project is
  archived somewhere else) keeps it, so it still resumes when that one is
  unarchived.

So a template "stays paused" after the purge when:

- it is paused (`is_active` false) and not deleted (`deleted_at` NULL),
- it carries a marker for a project/goal being purged, and
- once those markers are cleared, it carries no marker at all.

A template the user paused by hand has no marker, so purge doesn't change
it and it isn't named. A deleted template isn't named either.

## 3. Change

Server (`recycle_service.py`):
- `templates_left_paused_by_purge(project_ids, goal_ids)` returns those
  templates by title (read-only).
- `list_bin()` gives each batch `stays_paused: [{id, title}]` over its own
  projects and goals (for Purge).
- `bin_summary()` gives `stays_paused` over every batch in the bin (for
  Empty Bin). Templates are judged over the union, so one waiting on two
  batches' parents is named on Empty but not on either Purge alone.

Client:
- `recycleBinHelpers.staysPausedPhrase(list, scope)`: `""` for none (the
  quiet case asks nothing new); otherwise names up to 5, the same as #369's
  confirm (`project_archive_helpers` MAX_NAMED):
  - one: `1 repeating task on it stays paused: "Water plants". Resume it on
    Recurring if you still want it.`
  - many: `2 repeating tasks on it stay paused: "A", "B". Resume them on
    Recurring if you still want them.`
  - scope `"empty"` reads "on them" in place of "on it".
- `recycle_bin.js` puts it before "This cannot be undone." in Purge and
  Empty.
- Help, "Recycle bin and undo": one sentence saying the dialogs name them.

No new route, no migration, no behaviour change: message only.

## 4. Tests (red first)

- pytest: `list_bin` / `bin_summary` `stays_paused` covering a template
  paused by the undo (named), one paused by hand (not named), a deleted one
  (not named), and one also waiting on another archived parent (not named
  on Purge; named on Empty when both are in the bin).
- Jest: `staysPausedPhrase` one / many / >5 / none / empty scope.
- e2e: import a project with a template, undo, Purge → the dialog names it;
  a batch without one reads exactly as before.

## 5. Not in this ship

Nothing else was found. The row's deep-review note (§A12) is all #478.
