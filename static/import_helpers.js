/**
 * #432: which confirm endpoint an import goes to, and what to call its rows.
 *
 * The import page's confirm step used to choose with if / else-if / else, and
 * the last branch was goals — so a review with no mode (shown after Back)
 * posted task candidates to the goals endpoint. Now an unknown mode has no
 * endpoint, and the caller sends nothing.
 *
 * Exports (dual pattern, like the other static helpers):
 *   Browser: window.importHelpers
 *   Node:    module.exports  (tests/js/unit/import_helpers.test.js)
 */
(function () {
    "use strict";

    var CONFIRM_URLS = {
        tasks: "/api/import/tasks/confirm",
        projects: "/api/import/projects/confirm",
        goals: "/api/import/goals/confirm",
    };
    var NOUNS = { tasks: "task(s)", projects: "project(s)", goals: "goal(s)" };

    function own(table, key) {
        return Object.prototype.hasOwnProperty.call(table, key) ? table[key] : null;
    }

    function importConfirmUrl(mode) {
        return own(CONFIRM_URLS, mode);
    }

    function importNoun(mode) {
        return own(NOUNS, mode) || "item(s)";
    }

    var api = { importConfirmUrl: importConfirmUrl, importNoun: importNoun };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    if (typeof window !== "undefined") window.importHelpers = api;
})();
