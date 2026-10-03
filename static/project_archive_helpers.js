/**
 * Pure helpers for #353 — archiving a project pauses its repeating tasks.
 *
 * The pause itself happens on the server (project_service._set_project_active),
 * on every archive path. This module only decides what /projects TELLS the
 * user before archiving: which active templates will pause, and the confirm
 * text. Spec: docs/design/353-project-archive-pauses-templates.md §4.4.
 * /settings also uses archiveConfirmMessage for the import-undo confirm
 * (#369), with the list computed server-side.
 *
 * - Nothing would pause → "" so the caller shows no extra text. The quiet
 *   case stays quiet (the #351 rule).
 * - A failed fetch is treated as "nothing to report". The server cascade is
 *   the control; the dialog is information, so a network blip must not
 *   block archiving.
 *
 * Same dual-export shape as reflection_helpers.js: an IIFE, so nothing here
 * lands in the global lexical scope that every static/*.js classic script
 * shares (#359). Browser: window.projectArchiveHelpers. Jest: require().
 */
(function () {
    "use strict";

    var MAX_NAMED = 5;
    var TAIL = "They resume when you unarchive the project.";

    /**
     * The templates that archiving `projectIds` will pause: active ones whose
     * project is in the set. That mirrors the server's filter exactly
     * (project_id match AND is_active), so the dialog can't promise more or
     * less than the cascade does.
     */
    function templatesPausedBy(templates, projectIds) {
        if (!Array.isArray(templates) || !Array.isArray(projectIds)) return [];
        var wanted = new Set(projectIds);
        return templates.filter(function (t) {
            return t && t.is_active && t.project_id && wanted.has(t.project_id);
        });
    }

    /**
     * Confirm text for the templates `templatesPausedBy` returned.
     * `tail` (optional) replaces the closing sentence: #369's Settings
     * import-undo confirm passes its own, /projects uses the default.
     */
    function archiveConfirmMessage(paused, tail) {
        if (!Array.isArray(paused) || paused.length === 0) return "";
        var n = paused.length;
        var names = paused.slice(0, MAX_NAMED).map(function (t) {
            return "\"" + t.title + "\"";
        }).join(", ");
        var more = n > MAX_NAMED ? " and " + (n - MAX_NAMED) + " more" : "";
        var noun = n === 1 ? "repeating task" : "repeating tasks";
        var end = typeof tail === "string" && tail ? tail : TAIL;
        return "This will pause " + n + " " + noun + ": " + names + more + ". " + end;
    }

    var api = {
        templatesPausedBy: templatesPausedBy,
        archiveConfirmMessage: archiveConfirmMessage,
        MAX_NAMED: MAX_NAMED,
    };

    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    } else if (typeof window !== "undefined") {
        window.projectArchiveHelpers = api;
    }
})();
