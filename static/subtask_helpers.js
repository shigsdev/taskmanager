/**
 * #433: what closing or deleting tasks does to their open subtasks, in words.
 *
 * Completing or cancelling a parent closes its open subtasks with it (once
 * the user agrees); a task from a repeating template keeps them open
 * (#230). Deleting a parent takes them to the Recycle Bin, and restoring it
 * brings them back. The confirms that say so are built here so every path
 * (bulk menu, multi-drag onto Completed, panel / swipe Delete, bulk
 * Delete) words it the same way.
 *
 * Exports (dual pattern, like the other static helpers):
 *   Browser: window.subtaskHelpers
 *   Node:    module.exports  (tests/js/unit/subtask_helpers.test.js)
 */
(function () {
    "use strict";

    /**
     * Open subtasks across `tasks` (rows from /api/tasks, full view).
     * Subtasks themselves never count; repeating tasks only when asked
     * (delete takes their subtasks along, complete / cancel doesn't).
     *
     * @param {Array<object>} tasks
     * @param {{includeRepeating?: boolean}} [opts]
     * @returns {{parents: number, open: number}}
     */
    function openSubtaskSummary(tasks, opts) {
        var includeRepeating = Boolean(opts && opts.includeRepeating);
        var parents = 0;
        var open = 0;
        (Array.isArray(tasks) ? tasks : []).forEach(function (t) {
            if (!t || t.parent_id) return;
            if (t.recurring_task_id && !includeRepeating) return;
            var n = (t.subtask_count || 0) - (t.subtask_done || 0);
            if (n > 0) {
                parents += 1;
                open += n;
            }
        });
        return { parents: parents, open: open };
    }

    var ENDINGS = {
        complete: { one: "which will be completed too.", many: "which will be completed too." },
        cancel: { one: "which will be cancelled too.", many: "which will be cancelled too." },
        delete: {
            one: "which go to the Recycle Bin with it and come back when you restore it.",
            many: "which go to the Recycle Bin with them and come back when you restore them.",
        },
    };

    /**
     * The sentence a confirm adds when subtasks are affected, or "".
     *
     * @param {"complete"|"cancel"|"delete"} action
     * @param {{parents: number, open: number}} summary
     * @param {number} total — tasks the action covers (1 = a single task)
     * @returns {string}
     */
    function subtaskCloseNote(action, summary, total) {
        if (!summary || !summary.open || !ENDINGS[action]) return "";
        var subs = summary.open + " open subtask" + (summary.open === 1 ? "" : "s");
        var ending = ENDINGS[action][summary.parents === 1 ? "one" : "many"];
        if (total === 1) return "It has " + subs + ", " + ending;
        return summary.parents + " of them " + (summary.parents === 1 ? "has " : "have ") +
            subs + ", " + ending;
    }

    var api = { openSubtaskSummary: openSubtaskSummary, subtaskCloseNote: subtaskCloseNote };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    if (typeof window !== "undefined") window.subtaskHelpers = api;
})();
