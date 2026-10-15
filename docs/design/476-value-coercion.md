# #476 — Values of the wrong kind on a write

Split from #447 (deep review §B10).

## What happens

The server turns request values into booleans, numbers and text with
Python's built-ins, which bend or crash on the wrong kind of value:

| Input | Where | Today |
|---|---|---|
| `"false"` (a string) for a yes/no | recurring `is_active` (`bool()`), `/complete` `complete_subtasks`, `/cancel` `cancel_subtasks`, planner `ignore` | read as **true**: resumes a paused template, closes every open subtask, ignores the task |
| `null` project `type` / `status` | `project_service.update_project` (+ bulk) | NULL into a NOT NULL column → 422 "Database error" |
| a list / string / number body | optional-body routes (`/complete`, `/cancel`, planner weekly + ignore, Strength Forge session + flare, weekly focus slot + slot count, Shortcut move) | `.get` on a non-dict → 500 |
| a number as an id in a bulk id list | `/api/projects/reorder`, recurring bulk patch / delete | 500 |
| a number / list / object as text | task / goal / recurring title, project name, quarters, actions, notes, recurring URL, cancel reason, `@project` hint, reflection text, milestone label, Strength Forge plan / phase | `.strip()` / `len()` → 500 (notes: a list or object → 500 "Database error") |
| `Infinity`, `true`, `2.5`, `10**30` as a whole number | `parse_int` (sort / priority order, priority rank), recurring day fields, weekly focus slot count, Strength Forge reps / set number | `Infinity` → 500; `true` → 1, `2.5` → 2 silently; `10**30` → "Database error" |
| a non-object `repeat`, non-object checklist items | `PATCH /api/tasks/<id>` | `repeat` → 500; items stored as-is |

Flask parses `Infinity` / `NaN` literals, so a JSON client can send them.

## Change

New helpers in `utils.py`:

- `strict_int(value)` — `int()` that raises (TypeError / ValueError, like
  `int()`) on `True`/`False`, a fraction, `Infinity` / `NaN`. Every int
  coercion above uses it, keeping each caller's own message and range.
- `parse_int` — via `strict_int`, plus the Postgres `integer` range
  (±2 147 483 647): `"<field> is too large"`.
- `parse_bool(value, field)` — only `true` / `false`;
  `"<field> must be true or false"`. A missing optional flag stays false.
- `parse_text(value, field)` — `None` → `""`, a string as is, anything else
  `"<field> must be text"`.
- `@optional_json_body` — the optional-body twin of `@validate_json_body`: no
  body → `{}`, an object → itself, anything else → 400
  `"JSON body must be an object"`.

Behaviour, all 422 unless noted, before anything changes:

- Yes/no: the four flags above go through `parse_bool`.
- `null` project `type` / `status` keeps the current value — the rule tasks,
  goals and templates already follow.
- Optional-body routes use `@optional_json_body` (400).
- Bulk id lists: a non-string id gets each route's existing "must be a UUID"
  message.
- Text: every field listed goes through `parse_text`. Notes / actions keep
  "empty means none".
- Numbers: as above. Strength Forge's per-set rows stay forgiving (a bad reps
  value is dropped, a numeric resistance like `25` is kept as "25"); a
  reflection segment's non-finite duration / cost is dropped.
- `repeat` must be an object or null; checklist items must be objects.
- Scan / voice confirm `kind` that isn't text means "tasks" (its default).

Test parity: `tests/conftest.py`'s flush guard also refuses an `Integer`
outside its Postgres range with the same `DataError` (it already does for
`String(n)` widths, #447).

## Out of scope → new row

- **#484** Batch candidates of the wrong shape: import / scan / voice rows that
  aren't objects, `included: "false"` (any non-empty string counts as
  included), number titles / dates in import rows — each fails or bends the
  whole batch. Same rule as #481: fit or drop the row and say so.

## Tests

pytest `tests/test_value_coercion.py`: every row of the table → the 422 / 400
with its message and nothing changed; the quiet cases (real booleans, no
body, `2.0`, strings for numbers where accepted, numeric resistance) still
work; the flush guard raises on an out-of-range Integer.
