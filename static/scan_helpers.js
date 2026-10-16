/**
 * Pure helpers for /scan (#488).
 *
 * The review screen's heading, hint and Add buttons were fixed copy —
 * "Review Task Candidates", "Add All to Inbox" — whatever you scanned as.
 * Goals go to /goals and projects to /projects, so the review now words
 * itself by the kind the scan came back as.
 *
 * #490: the confirm payload is built here too, so Jest can check each
 * kind against the keys the server reads (it was mapped inline).
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

    /**
     * The rows /api/scan/confirm gets for a scan's reviewed candidates
     * (#490). Each kind sends the keys its server creator reads:
     *   tasks    → scan_service.create_tasks_from_candidates: title, type
     *   goals    → scan_service.create_goals_from_candidates: title,
     *              category, priority, target_quarter, actions
     *   projects → import_service.create_projects_from_import: name (the
     *              review edits it as `title`), type, target_quarter
     * `allIncluded` (Add All) sends every row; otherwise a row is left out
     * only when it was unticked.
     */
    function scanConfirmPayload(kind, candidates, allIncluded) {
        return (candidates || []).map(function (c) {
            var row = { included: allIncluded ? true : c.included !== false };
            if (kind === "projects") {
                row.name = c.title;
                row.type = c.type || "work";
                row.target_quarter = c.target_quarter || "";
            } else if (kind === "goals") {
                row.title = c.title;
                row.category = c.category || "personal_growth";
                row.priority = c.priority || "need_more_info";
                row.target_quarter = c.target_quarter || "";
                row.actions = c.actions || "";
            } else {
                row.title = c.title;
                row.type = c.type || "work";
            }
            return row;
        });
    }

    var api = { scanReviewCopy: scanReviewCopy, scanConfirmPayload: scanConfirmPayload };
    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    }
    if (typeof window !== "undefined") {
        window.scanHelpers = api;
    }
})();
