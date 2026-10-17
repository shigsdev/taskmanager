# #501 — Set and change a repeating task's start date

User request 2026-10-17: "For recurring task i want to be able to set and
modify start dates."

## What exists

- `RecurringTask.start_date` (#147). `_template_fires_on` skips any day
  before it, so neither the spawn cron nor the previews make anything
  earlier. It never changes which weekday or day of the month a template
  fires on.
- `_apply_repeat` sets it from the task's due date when a repeat is first
  added (#147). Since #426, `_update_repeat` changes it only when the
  request carries a truthy `repeat.start_date`. That means a client could
  set it but never clear it.
- `POST` / `PATCH /api/recurring` already accept `start_date` (null
  clears it), and `start_date > end_date` is a 422.
- No screen shows or edits it. The task panel's Repeat section and the
  /recurring editor have only "Stop after (optional)"; the /recurring row
  shows "(from …)" read-only.

## This ship

1. **Task panel:**
   - a "Start on (optional)" date next to Stop after, shown for any
     frequency;
   - `_serialize_repeat` exposes `start_date` so the field shows the
     template's date;
   - picking a frequency on a task with no repeat yet fills it with the
     due date (#147's default made visible).
2. **The task API's repeat (`task_service`):**
   - On an existing template, a present `start_date` key sets it; null
     clears it, meaning start right away.
   - A missing key keeps it. Older tabs and the capture bar don't send it
     (#426's protection stays).
   - On a new repeat, a present key wins; a missing key falls back to the
     due date.
   - The panel leaves the key out for a new repeat whose field is blank.
   - The rules are pure functions with Jest tests:
     `repeatStartDateForSave` and `repeatStartDatePrefill` in
     `static/task_detail_payload.js`.
3. **/recurring editor:** a "Start on (optional)" field, blank for a new
   template. `recurring_helpers.buildRecurringEditPayload` always sends
   `start_date`, with blank sent as null.
4. **Error message:** the start-after-stop 422 now reads "The start date
   must be on or before the Stop after date." (`field` stays `end_date`).

## Decided (conventional, no question needed)

- Changing the start date never touches tasks already made. A past date
  doesn't make missed occurrences, because the spawn only ever makes
  today's tasks.
- A blank Start on means "start right away", on both screens.

## Not in this ship

- Bulk-set start date from the /recurring Select toolbar (not asked for).
