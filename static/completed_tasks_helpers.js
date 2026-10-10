/**
 * #375: real task counts and an on-demand "Completed (N)" section for the
 * /projects and /goals panels.
 *
 * Both pages load only ACTIVE tasks (the /api/tasks default), so the project
 * card label read `N active / N total` with the same number twice and
 * completed tasks never showed. Loading every completed task with the page
 * is not an option: prod has 1,355 completed (821 KB) vs 73 active (40 KB),
 * one project with 356 and one goal with 422. So counts come from the
 * server (projects: `task_counts`; goals: the existing `progress`), and a
 * project/goal's own completed tasks load when its Completed section is
 * first opened, newest first, 50 at a time.
 *
 * Exports (dual pattern, like the other static helpers):
 *   Browser: window.completedTasksHelpers
 *   Node:    module.exports  (tests/js/unit/completed_tasks_helpers.test.js)
 */
(function () {
    "use strict";

    var COMPLETED_PAGE_SIZE = 50;

    /** /projects card label from the server's `task_counts`. Falls back to
     *  the active count the page holds, so stale JS against a server without
     *  `task_counts` (or the reverse) never shows "undefined". */
    function projectCountLabel(taskCounts, fallbackActive) {
        var ok = taskCounts && typeof taskCounts.active === "number"
            && typeof taskCounts.done === "number";
        if (!ok) {
            var n = fallbackActive || 0;
            return n === 0 ? "No tasks linked" : n + " active";
        }
        if (taskCounts.active === 0 && taskCounts.done === 0) return "No tasks linked";
        return taskCounts.active + " active · " + taskCounts.done + " done";
    }

    function completedSummaryLabel(n) {
        return "Completed (" + n + ")";
    }

    function moreButtonLabel(remaining, step) {
        if (remaining <= step) return "Show " + remaining + " more";
        return "Show " + step + " more (" + remaining + " left)";
    }

    function _time(t) {
        var ms = t && t.updated_at ? Date.parse(t.updated_at) : NaN;
        return isNaN(ms) ? null : ms;
    }

    /** Newest first by `updated_at` (there is no completed_at; editing a done
     *  task moves it up). Ties by title; undated / unparseable last. */
    function sortCompletedNewestFirst(tasks) {
        return tasks.slice().sort(function (a, b) {
            var ta = _time(a);
            var tb = _time(b);
            if (ta !== tb) {
                if (ta === null) return 1;
                if (tb === null) return -1;
                return tb - ta;
            }
            return String(a.title || "").localeCompare(String(b.title || ""));
        });
    }

    function completedPage(tasks, shown) {
        var visible = tasks.slice(0, Math.max(0, shown));
        return { visible: visible, remaining: tasks.length - visible.length };
    }

    /** The one request a Completed section makes: that project's or goal's
     *  completed tasks — never `status=all` (it includes deleted ones). */
    function completedTasksUrl(kind, id) {
        var param = { project: "project_id", goal: "goal_id" }[kind];
        if (!param) throw new Error("completedTasksUrl: unknown kind " + kind);
        return "/api/tasks?status=archived&" + param + "=" + encodeURIComponent(id);
    }

    /**
     * Build a collapsed <details> "Completed (N)" section.
     *   opts.doc       document
     *   opts.count     completed count from the server (0 → returns null)
     *   opts.load      () => Promise<task[]>  — fetches the completed tasks
     *   opts.renderRow (task) => Element      — the page's own row builder
     *   opts.listTag   "ul" (default, for <li> rows) or "div" (for <div> rows)
     * Returns { element, refresh } or null. Loads on first open; reopening
     * reuses the rows; a failed load says so and the next open retries;
     * refresh() re-fetches if the section has been opened; a reply that a
     * newer load has superseded is dropped.
     */
    function createCompletedSection(opts) {
        if (!opts.count) return null;
        var doc = opts.doc;
        var step = opts.step || COMPLETED_PAGE_SIZE;

        var details = doc.createElement("details");
        details.className = "completed-tasks";
        var summary = doc.createElement("summary");
        summary.className = "completed-tasks-summary";
        summary.textContent = completedSummaryLabel(opts.count);
        var list = doc.createElement(opts.listTag === "div" ? "div" : "ul");
        list.className = "completed-tasks-list";
        var status = doc.createElement("p");
        status.className = "completed-tasks-status";
        status.setAttribute("role", "status");
        var more = doc.createElement("button");
        more.type = "button";
        more.className = "completed-tasks-more";
        more.hidden = true;
        details.appendChild(summary);
        details.appendChild(list);
        details.appendChild(status);
        details.appendChild(more);

        var tasks = null;     // sorted rows once loaded
        var shown = step;
        var requested = false;
        var loading = false;
        var generation = 0;

        function render() {
            var page = completedPage(tasks, shown);
            while (list.firstChild) list.removeChild(list.firstChild);
            for (var i = 0; i < page.visible.length; i++) {
                list.appendChild(opts.renderRow(page.visible[i]));
            }
            more.hidden = page.remaining === 0;
            if (page.remaining) more.textContent = moreButtonLabel(page.remaining, step);
        }

        function fetchRows() {
            requested = true;
            loading = true;
            var mine = ++generation;
            status.textContent = "Loading…";
            status.hidden = false;
            Promise.resolve().then(opts.load).then(function (rows) {
                if (mine !== generation) return; // superseded
                loading = false;
                tasks = sortCompletedNewestFirst(rows || []);
                status.textContent = "";
                status.hidden = true;
                render();
            }, function () {
                if (mine !== generation) return;
                loading = false;
                tasks = null;
                status.textContent = "Couldn't load completed tasks — close and open this again to retry.";
            });
        }

        details.addEventListener("toggle", function () {
            // One load at a time: a second open while the first is in
            // flight must not start another.
            if (details.open && tasks === null && !loading) fetchRows();
        });
        more.addEventListener("click", function () {
            shown += step;
            render();
        });

        return {
            element: details,
            refresh: function () { if (requested) fetchRows(); },
        };
    }

    var api = {
        projectCountLabel: projectCountLabel,
        completedSummaryLabel: completedSummaryLabel,
        moreButtonLabel: moreButtonLabel,
        sortCompletedNewestFirst: sortCompletedNewestFirst,
        completedPage: completedPage,
        completedTasksUrl: completedTasksUrl,
        createCompletedSection: createCompletedSection,
        COMPLETED_PAGE_SIZE: COMPLETED_PAGE_SIZE,
    };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    if (typeof window !== "undefined") window.completedTasksHelpers = api;
})();
