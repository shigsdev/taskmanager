# #447 — Text that's too long for its column

Filed by the deep review (§B10) as one row with seven findings. This ship takes
the one that loses work on prod — **values longer than their column** — and
files the other five as their own rows (below).

## What happens

Prod is Postgres: a value longer than its `String(n)` column raises
`StringDataRightTruncation` → `DataError` → `errors.py` answers 422 "Database
error — full detail is in the server logs". Tests run on SQLite, which ignores
widths, so no test has ever seen it.

A sweep of every write path (28) found only `Task.url` rejected cleanly; a few
paths truncate silently; most don't check at all. Worst cases are batches — one
long line fails the whole batch:

| Batch | Columns | Today |
|---|---|---|
| /import confirm (tasks, goals, projects) | titles, name, quarter, url, `ImportLog.source` | one commit — all rows lost |
| voice memo / scan confirm | task titles (re-sent from the edited review), goal/project | whole step lost |
| /reflection apply (creates) | task/goal titles, project name, quarter | all creates of that kind lost |
| recurring spawn (subtask copies) | `Task.title` from the JSON snapshot | every subtask that day lost |
| bulk edit (tasks, projects, recurring) | title, name, quarter, reason | first row fails, nothing applies |

Also: `Project.color` accepts `#RRGGBBAA` (9 chars) into `String(7)`;
`AppLog.request_id` (36) takes a client `X-Request-ID` up to 64 chars and
`AppLog.route` (200) takes the raw path — both lose the log row.

## Decision (user, 2026-10-14)

**Reject what you type; fit what comes in a batch.**

- Your own edits — task / goal / project / recurring create and update, bulk
  edits, the cancel reason — are refused with
  `Title is too long: 523 characters, the limit is 500.` (422, field named).
  The panel stays open with the text (#430's "didn't save: <reason>").
  The inputs get `maxlength` so typing stops at the limit.
- Batches — import, voice memo, scan, reflection creates, recurring subtask
  copies, `ImportLog.source` — cut that one value to fit, ending in `…`, so the
  rest of the batch saves. A URL can't be cut and still work, so an over-long
  URL in a batch is dropped (the task keeps its title and notes).

## Change

- `utils.py`: `check_length(value, max_len, field, label)` → the value, or
  ValidationError; `fit_length(value, max_len)` → the value cut to fit with `…`.
  Limits read from the model columns (`Task.__table__.c.title.type.length`),
  never retyped.
- Reject at: `task_service` create/update title, cancellation reason (update +
  `cancel_parent_task`); `goal_service` create/update title, quarter;
  `project_service` create/update name, quarter (bulk goes through update);
  `recurring_service` create/update title, url.
- Fit at: `import_service` tasks / goals / projects (+ `ImportLog.source`, url
  dropped), `scan_service.create_tasks_from_candidates` (voice + scan +
  reflection tasks), voice recurring template title, recurring spawn subtask
  copies.
- `project_service._HEX_COLOR_RE`: #RGB and #RRGGBB only.
- `logging_service`: request id kept only if ≤ 36 chars; route cut to 200.
- Templates: `maxlength` on the task, goal, project and recurring title / name
  and quarter inputs that lack it.
- **Test guard:** `tests/conftest.py` adds a `before_flush` listener that
  raises when any `String(n)` attribute is longer than `n` — SQLite now fails
  like Postgres, so the whole suite checks every path, today's and future.

## Out of scope (filed)

- **#474** complete / cancel don't check the current status — completing a
  DELETED task revives it (`task_service.py` `complete_parent_task` /
  `cancel_parent_task`).
- **#475** project / goal ids aren't checked for existing, active and same
  type.
- **#476** value coercion: recurring `is_active: "false"` resumes
  (`bool()`), a null project `type`/`status` hits NOT NULL, non-object JSON
  bodies and non-string titles 500, `Infinity` overflows int coercions.
- **#477** /utilities audits run up to 2×120 s synchronously with no rate
  limit.
- Voice confirm's recurring step catches `Exception` without a rollback
  (`recurring_service.py` ~960) — added to **#470** (voice confirm not atomic).

## Tests

- pytest: each reject path → 422 with the message (create + update, tasks,
  goals, projects, recurring, bulk, cancel reason); each batch path → the long
  value is cut with `…` and the other rows save; 8-digit colour → 422;
  long request id / route don't lose the log row; the flush guard itself.
- Jest: none (no client logic beyond `maxlength`).
- Playwright: a 501-character title typed into the task panel stops at 500
  (`maxlength`); a 501-character title sent by API → the panel-style message.
