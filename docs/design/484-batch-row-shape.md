# #484 — A batch row of the wrong shape is skipped (and said), not fatal

Split from #476 on 2026-10-15. Checked 2026-10-16 against the confirm
endpoints (`import_api` tasks / goals / projects, `scan_api`, `voice_api`)
and the creators they call (`import_service`, `scan_service`).

## What was wrong

The confirm endpoints check only that `candidates` is a list. Each row
then goes straight to `.get(...)` and `(… or "").strip()`:

- **A row that isn't an object** (a string, a number, null) → `.get` on
  it raises → 500 for the whole batch (voice already skips these).
- **A number where text belongs** — a title `5`, a due date `20261020`,
  a goal's `target_quarter` `2026` → `.strip()` / `fit_length` raise →
  500 for every row.
- **`included: "false"`** (or any non-empty string) counts as included,
  so a row the sender meant to leave out is created.

The review pages always send well-formed rows; this is the API's own
robustness (a hand-built request, an older client, a Shortcut).

## This ship

New `batch_input.py` (no app imports, pure):

- `row_included(row)` — missing / `true` → included; `false`, `0`,
  `"false"`, `"no"`, `"0"`, `""` → left out (case-insensitive).
- `clean_row(row)` — `None` for a row that isn't an object; otherwise a
  copy whose text fields (title, name, type, tier, due_date, project_id,
  goal_id, linked_goal, linked_project, notes, url, category, priority,
  status, actions, target_quarter, color) are strings: a number becomes
  its digits, anything else (list, object, bool) is dropped as if
  missing. Other keys (`repeat`, `route`, …) pass through. `included`
  becomes a real boolean.
- `clean_rows(candidates)` → `(rows, skipped)`; `skipped_warning(n)` →
  "1 row couldn't be read and was skipped." / "N rows couldn't be read and
  were skipped." or None.

The five confirm endpoints run `clean_rows` first and add the skip
sentence to their `warning` (joined with #481's link warning and voice's
own). The pages already show `warning` (#425 voice, #481 import / scan).

Out of scope: the reflection apply path builds its own rows from Claude's
proposal fields (separate shape rules, #437) — unchanged.
