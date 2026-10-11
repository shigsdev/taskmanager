# #426 — Saving a recurring task no longer moves its template's start date

Filed 2026-10-11 by the deep review (§A3).

## 1. Surface

| Step | Code | Problem |
|---|---|---|
| Panel save | `static/task_detail_payload.js` `buildTaskDetailPayload` | Always sends `repeat` (from `_serialize_repeat`, which carries no `start_date`) — fine |
| Server update | `task_service.py` `_update_repeat` (~443-451) | Sends `start_date = repeat.start_date or task.due_date` to `update_recurring` on **every** save, so the template's start date becomes this occurrence's due date |
| Spawn / previews | `recurring_service.py` `_template_fires_on` (~529) | Won't fire before `start_date` — push Monday's spawn to next Tuesday and next Monday never spawns |
| Window check | `recurring_service.py` `update_recurring` → `_validate_date_window` (~417) | Push an occurrence past the template's `end_date` and the whole task save 422s |
| Create path | `task_service.py` `_apply_repeat` (~383-391) | Backfills from `task.due_date` when a repeat is first set — correct (#147), unchanged |
| /recurring editor | `recurring_api.py` → `update_recurring` | Sends `start_date` explicitly — unchanged |

The update-path backfill was added on 2026-05-02 (#147 follow-up) so a
template created **before** #147 picked up a start date when its task was
next saved. Prod on 2026-10-11 has 17 active templates; the 2 with a NULL
start date were both created after #147 (2026-05-30, 2026-09-22) and are
already firing, so the migration has nothing left to do — and on either one,
"backfill only when NULL" (the fix as filed) would still skip occurrences the
first time a pushed occurrence is saved.

## 2. This ship

1. `_update_repeat`: send `start_date` to `update_recurring` only when the
   repeat payload carries one explicitly. Never derive it from the task's
   due date on this path. Moving one occurrence moves only that task.
2. pytest (red on the old code), through `PATCH /api/tasks/<id>`:
   - pushing a spawned weekly task a week and a day later leaves the
     template's start date alone and it still fires next week;
   - pushing it past the template's end date saves (200), and the template
     is unchanged;
   - a NULL start date stays NULL;
   - an explicit `repeat.start_date` still sets it.
   The old `test_update_repeat_path_also_backfills_start_date` asserted the
   removed behaviour; it is rewritten to the NULL-stays-NULL case.
3. Help: one sentence under "When tasks spawn" — moving a spawned task to
   another day moves only that task; the template keeps its schedule.
4. `architecture_schemas.py` start_date note: say it is set when a repeat is
   first added, not on later saves.

## 3. Out of scope

- The panel also writes title / notes / checklist / url / project / goal
  back to the template on every save — deliberate (the series follows the
  task you edit), not changed.
- No CACHE_VERSION bump: no static asset changes.
