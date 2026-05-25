/**
 * /calendar page pure-logic helpers, extracted from calendar.js so they
 * can be unit-tested from Jest (#231 — closes the gap that let two bugs
 * ship together: subtasks rendered as top-level rows on the grid AND
 * Unscheduled items had no click affordance).
 *
 * Dual-export pattern, same as filter_helpers / api_helpers / etc.:
 * in the browser, the helpers are attached to `window.calendarBucketHelpers`
 * via the `<script>` load; in Node.js (Jest) they are require()-able
 * via `module.exports`.
 *
 * What lives here vs. calendar.js:
 *   - bucketTasks() — the pure function that decides which day cell
 *     a task lands in vs. the Unscheduled aside, AND filters out
 *     subtasks (#231 fix). Pure: takes args, returns a value, no DOM.
 *   - DOM mutation (rendering cells, attaching listeners) stays in
 *     calendar.js (covered by Phase 6 + local Playwright).
 *
 * Filter rule (#231): tasks with `parent_id !== null` are subtasks and
 * are EXCLUDED from the calendar render. They appear nested under the
 * parent's detail card on the main board; rendering them as their own
 * top-level rows on /calendar created the visual duplicate the user
 * reported on 2026-05-24 ("I still see Subtasks listed on unscheduled
 * and the day i put them on").
 *
 * Tier fallback (#100 / PR29): tasks with no `due_date` but with a
 * tier of TODAY or TOMORROW bucket to today / tomorrow's cell. Other
 * tiers (THIS_WEEK / NEXT_WEEK span multiple days; BACKLOG / FREEZER
 * are intentionally undated) fall through to Unscheduled.
 */
"use strict";

/**
 * Bucket the API task list into `{ byDate: {iso: [task,...]}, unscheduled: [task,...] }`.
 *
 * @param {Array<{id, title, parent_id, due_date, tier, ...}>} tasks - raw /api/tasks rows
 * @param {string} todayIso - "YYYY-MM-DD" for "today" (caller computes from local clock)
 * @param {string} tomorrowIso - "YYYY-MM-DD" for "tomorrow"
 * @returns {{ byDate: Object<string, Array>, unscheduled: Array }}
 */
function bucketTasks(tasks, todayIso, tomorrowIso) {
    const byDate = {};
    const unscheduled = [];
    // #231: subtasks belong with their parent on the main board, not as
    // their own top-level rows on the calendar.
    const topLevel = tasks.filter(function (t) { return !t.parent_id; });
    for (const t of topLevel) {
        let cellDate = t.due_date;
        if (!cellDate) {
            if (t.tier === "today") cellDate = todayIso;
            else if (t.tier === "tomorrow") cellDate = tomorrowIso;
        }
        if (cellDate) {
            if (!byDate[cellDate]) byDate[cellDate] = [];
            byDate[cellDate].push(t);
        } else {
            unscheduled.push(t);
        }
    }
    return { byDate: byDate, unscheduled: unscheduled };
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = { bucketTasks };
} else if (typeof window !== "undefined") {
    window.calendarBucketHelpers = { bucketTasks };
}
