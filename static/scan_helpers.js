/**
 * Pure helpers for /scan (#488).
 *
 * The review screen's heading, hint and Add buttons were fixed copy —
 * "Review Task Candidates", "Add All to Inbox" — whatever you scanned as.
 * Goals go to /goals and projects to /projects, so the review now words
 * itself by the kind the scan came back as.
 *
 * Dual-export: window.scanHelpers in the browser, module.exports in Jest.
 */
(function () {
    "use strict";

    var COPY = {
        tasks: {
            heading: "Review Task Candidates",
            hint: "Edit, include, or exclude each candidate before adding to inbox.",
            addAll: "Add All to Inbox",
            addSelected: "Add Selected to Inbox",
        },
        goals: {
            heading: "Review Goal Candidates",
            hint: "Edit, include, or exclude each candidate before adding to your goals.",
            addAll: "Add All to Goals",
            addSelected: "Add Selected to Goals",
        },
        projects: {
            heading: "Review Project Candidates",
            hint: "Edit, include, or exclude each candidate before adding to your projects.",
            addAll: "Add All to Projects",
            addSelected: "Add Selected to Projects",
        },
    };

    /** The review screen's copy for a scan kind (anything unknown reads as tasks). */
    function scanReviewCopy(kind) {
        return Object.prototype.hasOwnProperty.call(COPY, kind) ? COPY[kind] : COPY.tasks;
    }

    var api = { scanReviewCopy: scanReviewCopy };
    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    }
    if (typeof window !== "undefined") {
        window.scanHelpers = api;
    }
})();
