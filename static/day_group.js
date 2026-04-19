/**
 * Day-of-week grouping for This Week / Next Week tiers — backlog #23.
 *
 * Pure function, extracted into its own module so Jest can unit-test
 * it without having to spin up jsdom + the full app.js bootstrap.
 *
 * Consumers: static/app.js (loaded via a <script> tag before app.js
 * in base.html). Also loaded via require() in tests/js/unit/.
 */
(function (exports) {
    "use strict";

    var _DAY_NAMES = [
        "Sunday", "Monday", "Tuesday", "Wednesday",
        "Thursday", "Friday", "Saturday",
    ];

    /**
     * Group a list of tasks by the day-of-week of their due_date.
     *
     * @param {Array<{due_date: string|null}>} tasks
     * @returns {Array<{label: string, tasks: Array}>}
     *   In render order: Monday → Sunday for tasks with a due_date,
     *   then "No date" for tasks without one. Empty groups are omitted.
     *
     * Monday-first ordering (not "today-first") keeps the visual
     * structure stable — the user sees the same week shape regardless
     * of which day they're looking at the board.
     *
     * Parses due_date strings as local-time ("YYYY-MM-DD" → local
     * midnight), not UTC, so a task due 2026-04-20 shows up on Monday
     * regardless of the viewer's timezone.
     */
    function groupTasksByWeekday(tasks) {
        var dayBuckets = [[], [], [], [], [], [], []];  // Sun..Sat
        var noDate = [];
        for (var i = 0; i < tasks.length; i++) {
            var task = tasks[i];
            if (!task.due_date) {
                noDate.push(task);
                continue;
            }
            var parts = String(task.due_date).split("-");
            var y = Number(parts[0]);
            var m = Number(parts[1]);
            var d = Number(parts[2]);
            if (!isFinite(y) || !isFinite(m) || !isFinite(d)) {
                // Malformed date string — fall back to "no date"
                // bucket so the task is still rendered somewhere.
                noDate.push(task);
                continue;
            }
            var date = new Date(y, m - 1, d);
            dayBuckets[date.getDay()].push(task);
        }
        var result = [];
        var order = [1, 2, 3, 4, 5, 6, 0];  // Mon..Sun
        for (var oi = 0; oi < order.length; oi++) {
            var di = order[oi];
            if (dayBuckets[di].length > 0) {
                result.push({
                    label: _DAY_NAMES[di],
                    tasks: dayBuckets[di],
                });
            }
        }
        if (noDate.length > 0) {
            result.push({ label: "No date", tasks: noDate });
        }
        return result;
    }

    exports.groupTasksByWeekday = groupTasksByWeekday;

    // Browser: attach to window so app.js can call it without an import.
    if (typeof window !== "undefined") {
        window.groupTasksByWeekday = groupTasksByWeekday;
    }
})(typeof module !== "undefined" && module.exports ? module.exports : {});
