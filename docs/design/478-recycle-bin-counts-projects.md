# #478 — The Recycle Bin counts projects

Filed 2026-10-14 by the #448 Help check. Checked 2026-10-16 against
`recycle_service.list_bin` / `bin_summary`, `static/recycle_bin.js` and
`static/settings.js` `loadBinCount`.

## What was wrong

The server already counts projects (`project_count` in both `list_bin` and
`bin_summary`, PR66 #131), but the pages never read it:

- /recycle-bin's summary adds `task_count + goal_count`, so a bin holding
  only undone project imports reads "No undone imports." and **Empty Bin is
  disabled** — those batches can't be emptied in one step.
- Each batch row lists only tasks and goals; a projects-only batch reads
  "0 items".
- Restore / Purge / Empty Bin dialogs say "N tasks and M goals" and never
  mention the projects they restore or delete.
- Settings → "Recycle Bin (N)" leaves projects out.

## This ship

- `recycle_bin_helpers.js` (Jest-tested):
  - `binItemTotal(counts)` — tasks + goals + projects.
  - `binItemPhrase(counts, keys)` — "2 tasks, 1 goal and 3 projects",
    leaving out zero kinds; "nothing" when all are zero. `keys` lets a
    caller pass `restore_goal_count` / `restore_project_count`.
- /recycle-bin: the summary, Empty Bin's enabled state, each batch row and
  the Restore / Purge / Empty Bin dialogs use them, so projects count
  everywhere.
- `list_bin` gains `restore_project_count` — the projects Restore will
  actually bring back (the ones the undo archived; a legacy batch with no
  snapshot brings back every inactive one), mirroring #367's
  `restore_goal_count`, so the Restore dialog doesn't over-promise.
- Settings: "Recycle Bin (N)" adds `project_count`.

The quiet cases: an empty bin still reads "No undone imports." with Empty
Bin disabled; a tasks-only batch reads exactly as before ("1 task").

## Out of scope

- #494 (subtasks you added aren't counted in these words) stays its own row.
