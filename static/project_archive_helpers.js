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
    // The closing sentence, by count (#374: one task "resumes", not "They").
    var TAIL = {
        one: "It resumes when you unarchive the project.",
        many: "They resume when you unarchive the project.",
    };

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
     * `tail` (optional) replaces the closing sentence: a `{one, many}` pair,
     * picked by count (#374). #369's Settings import-undo confirm passes its
     * own; /projects uses the default, as does anything that isn't a pair.
     */
    function archiveConfirmMessage(paused, tail) {
        if (!Array.isArray(paused) || paused.length === 0) return "";
        var n = paused.length;
        var names = paused.slice(0, MAX_NAMED).map(function (t) {
            return "\"" + t.title + "\"";
        }).join(", ");
        var more = n > MAX_NAMED ? " and " + (n - MAX_NAMED) + " more" : "";
        var noun = n === 1 ? "repeating task" : "repeating tasks";
        var pair = tail && typeof tail.one === "string" && typeof tail.many === "string"
            ? tail : TAIL;
        var end = n === 1 ? pair.one : pair.many;
        return "This will pause " + n + " " + noun + ": " + names + more + ". " + end;
    }

    /**
     * #482: changing a project's type takes its tasks and repeating tasks
     * with it (user decision 2026-10-16; the server does it in
     * update_project). The confirm before it: how many move, e.g.
     * '4 tasks and 1 repeating task on "Kitchen" become Personal too.'
     * Tasks = the card's active + done count (task_counts, #375);
     * repeating tasks = every template on those projects, paused or not.
     * A project already of `newType` moves nothing. "" when nothing moves —
     * the quiet case asks nothing (the #351 rule).
     */
    function typeChangeMessage(projects, projectIds, newType, templates) {
        if (!Array.isArray(projects) || !Array.isArray(projectIds)) return "";
        var wanted = new Set(projectIds);
        var changing = projects.filter(function (p) {
            return p && wanted.has(p.id) && p.type !== newType;
        });
        if (!changing.length) return "";
        var ids = new Set(changing.map(function (p) { return p.id; }));
        var tasks = changing.reduce(function (n, p) {
            var c = p.task_counts || {};
            return n + (c.active || 0) + (c.done || 0);
        }, 0);
        var tmpls = (Array.isArray(templates) ? templates : []).filter(function (t) {
            return t && t.project_id && ids.has(t.project_id);
        }).length;
        if (!tasks && !tmpls) return "";
        var parts = [];
        if (tasks) parts.push(tasks + " task" + (tasks === 1 ? "" : "s"));
        if (tmpls) parts.push(tmpls + " repeating task" + (tmpls === 1 ? "" : "s"));
        var where = changing.length === 1
            ? "\"" + changing[0].name + "\""
            : changing.length + " projects";
        var verb = tasks + tmpls === 1 ? "becomes" : "become";
        var label = newType === "personal" ? "Personal" : "Work";
        return parts.join(" and ") + " on " + where + " " + verb + " " + label + " too.";
    }

    var api = {
        templatesPausedBy: templatesPausedBy,
        archiveConfirmMessage: archiveConfirmMessage,
        typeChangeMessage: typeChangeMessage,
        MAX_NAMED: MAX_NAMED,
    };

    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    } else if (typeof window !== "undefined") {
        window.projectArchiveHelpers = api;
    }
})();
