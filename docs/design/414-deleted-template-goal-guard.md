# #414 — A deleted repeating task no longer blocks its goal's hard delete

Bug (filed 2026-10-11 by the #363 spec §5): `goal_service.goal_reference_counts`
counts every `RecurringTask` row with the goal's id, deleted ones included.
A deleted template is invisible on `/recurring` and can't be edited (#363), so
a goal held only by one refused **Delete permanently** with
"1 repeating task still points …" and nothing in the UI could clear it.

## 1. Surface

- `goal_service.goal_reference_counts` feeds both `GET /api/goals/<id>/references`
  (the panel's disabled-button hint) and `hard_delete_goal` (the 409). It's the
  only reader. `static/goal_archive_helpers.js` renders the server's counts.
- `RecurringTask.goal_id` is `ON DELETE SET NULL`. Nothing else blocks.
- Other link readers already skip deleted templates or don't matter:
  - `?all=1` excludes them (#363).
  - The #352 project-move cascade re-points them harmlessly.
  - Recycle purge already relies on `SET NULL`.

## 2. This ship

1. `goal_reference_counts`: the `recurring` count skips `deleted_at IS NOT NULL`.
   Paused templates still count, because the user can see them and move or delete them.
   Tasks, projects and weekly focus are unchanged.
2. `hard_delete_goal`: once the guard passes, null `goal_id` on the goal's
   deleted templates **explicitly**, in the same commit, before deleting the
   goal. This is #349's "don't let the database quietly decide" rule. It also
   gives the same result on SQLite, where `SET NULL` isn't enforced.
3. Docstring and the `/architecture` schema notes. No user-visible copy
   changes: the hint simply stops appearing when nothing visible blocks.

Rejected: nulling links in `delete_recurring`. It loses the template's
history, and it changes every link reader to fix one.

## 3. Tests (red first)

- A goal held only by a deleted template: `/references` reports
  `recurring: 0`, the hard delete returns 200, the goal row is gone, and the
  template survives (still deleted) with `goal_id` NULL.
- A goal held by a PAUSED template still refuses (409, `recurring: 1`).
- Mixed paused + deleted: the count is 1.

## 4. Out of scope

Nothing new found.
