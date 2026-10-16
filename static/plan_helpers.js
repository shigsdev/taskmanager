/**
 * #436: the PATCH body for one /plan suggestion row.
 *
 * A "move" row with no date (none suggested, none typed) used to send
 * `due_date: null`, which wiped the task's date and skipped the server's
 * Today / Tomorrow date rules. Now a date is sent only when there is one.
 *
 * `fields` holds the row's override controls, null when blank or absent:
 *   { tier, due_date, project, goal }
 *
 * Exports (dual pattern, like the other static helpers):
 *   Browser: window.planHelpers
 *   Node:    module.exports  (tests/js/unit/plan_helpers.test.js)
 */
(function () {
    "use strict";

    function planRowPayload(suggestion, fields) {
        var payload = {};
        if (suggestion.action === "move") {
            var tier = fields.tier || suggestion.suggested_tier;
            if (tier) payload.tier = tier;
            var due = fields.due_date || suggestion.suggested_due_date;
            if (due) payload.due_date = due;
        } else if (suggestion.action === "freeze") {
            payload.tier = "freezer";
        } else if (suggestion.action === "delete") {
            // Delete goes out as a DELETE request, not a PATCH.
            payload._delete = true;
        }
        // A blank project / goal control leaves the task's own link alone.
        if (fields.project) payload.project_id = fields.project;
        if (fields.goal) payload.goal_id = fields.goal;
        return payload;
    }

    /**
     * hasPendingRows - #473: is any suggestion still undecided?
     * rowState maps task id -> "pending" | "accepted" | "ignored". While one
     * is pending a deploy reload would throw the plan (a paid call) away;
     * once every row is decided there is nothing left to lose.
     */
    function hasPendingRows(rowState) {
        if (!rowState) return false;
        return Object.keys(rowState).some(function (k) {
            return rowState[k] === "pending";
        });
    }

    var api = { planRowPayload: planRowPayload, hasPendingRows: hasPendingRows };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    if (typeof window !== "undefined") window.planHelpers = api;
})();
