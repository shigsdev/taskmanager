/**
 * #441: the Weekly Focus slots' decisions, kept pure so Jest can test them.
 *
 * A slot's save answers while the user may already be typing in the next
 * slot (or in this one again). The panel updates the slots in place, and
 * these say what each input should show and whether a blur sends anything.
 *
 * Exports (dual pattern, like the other static helpers):
 *   Browser: window.weeklyFocusHelpers
 *   Node:    module.exports  (tests/js/unit/weekly_focus_helpers.test.js)
 */
(function () {
    "use strict";

    // What a slot's input should show once the server answers.
    //   value      — what the input holds now
    //   synced     — what it held when last drawn or sent to the server
    //   serverText — the slot's text in the answer ("" for an empty slot)
    //   focused    — the input has focus (the user may be typing)
    // The user's own typing is never replaced: an input with focus, or one
    // changed since it was last synced, keeps its value (its save is queued).
    function slotInputValue(opts) {
        var value = opts.value || "";
        var serverText = opts.serverText || "";
        if (opts.focused) return value;
        if (value === (opts.synced || "")) return serverText;
        if (value.trim() === serverText) return serverText;
        return value;
    }

    // What a blur has to send for one slot.
    //   row    — the slot's saved row ({text, goal_id}) or null when empty
    //   text   — the input's text, trimmed
    //   goalId — the goal picker's value, or null
    // Returns "save", "clear" (empty input over a saved slot) or "none".
    function slotNeedsSave(row, text, goalId) {
        if (!text) return row ? "clear" : "none";
        if (!row) return "save";
        if (row.text !== text) return "save";
        var was = row.goal_id == null ? "" : String(row.goal_id);
        var now = goalId == null ? "" : String(goalId);
        return was === now ? "none" : "save";
    }

    var api = { slotInputValue: slotInputValue, slotNeedsSave: slotNeedsSave };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    if (typeof window !== "undefined") window.weeklyFocusHelpers = api;
})();
