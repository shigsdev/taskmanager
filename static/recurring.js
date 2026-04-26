/**
 * /recurring page — list + multi-select + bulk-edit toolbar for
 * recurring templates (#63, 2026-04-26).
 *
 * Loads templates via GET /api/recurring (active_only=false), renders
 * one row per template with a checkbox, name, frequency summary,
 * type, project + goal labels. Toolbar fires bulk actions via the
 * new PATCH /api/recurring/bulk and DELETE /api/recurring/bulk
 * endpoints.
 */
(function () {
    "use strict";

    var allTemplates = [];
    var allProjects = [];
    var allGoals = [];

    function _projectName(id) {
        var p = allProjects.find(function (x) { return x.id === id; });
        return p ? p.name : "(none)";
    }
    function _goalTitle(id) {
        var g = allGoals.find(function (x) { return x.id === id; });
        return g ? g.title : "(none)";
    }
    function _freqSummary(rt) {
        var base;
        if (rt.frequency === "weekly" || rt.frequency === "day_of_week") {
            var days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
            base = rt.frequency.replace("_", " ") + " — " + (days[rt.day_of_week] || "?");
        } else if (rt.frequency === "multi_day_of_week") {
            var dnames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
            var picked = (rt.days_of_week || []).map(function (i) { return dnames[i] || "?"; });
            base = "multi day — " + picked.join(", ");
        } else if (rt.frequency === "monthly_date") {
            base = "monthly — day " + rt.day_of_month;
        } else if (rt.frequency === "monthly_nth_weekday") {
            base = "monthly — wk " + rt.week_of_month + " day " + rt.day_of_week;
        } else {
            base = rt.frequency;
        }
        // #101 (PR30): show sunset date when set.
        if (rt.end_date) base += " (until " + rt.end_date + ")";
        return base;
    }

    function getSelectedIds() {
        return Array.from(document.querySelectorAll(".recurring-row input[type=checkbox]:checked"))
            .map(function (cb) { return cb.dataset.id; });
    }

    function updateToolbar() {
        var n = getSelectedIds().length;
        var counter = document.getElementById("recurringSelectedCount");
        var actions = document.getElementById("recurringBulkActions");
        if (n > 0) {
            counter.textContent = n + " selected";
            counter.style.display = "";
            actions.style.display = "";
        } else {
            counter.style.display = "none";
            actions.style.display = "none";
        }
    }

    function renderRow(rt) {
        var row = document.createElement("div");
        row.className = "recurring-row" + (rt.is_active ? "" : " recurring-row-inactive");

        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.dataset.id = rt.id;
        cb.addEventListener("change", updateToolbar);
        row.appendChild(cb);

        var info = document.createElement("div");
        info.className = "recurring-row-info";
        info.innerHTML =
            "<div class='recurring-row-title'>" + escapeHtml(rt.title) + "</div>" +
            "<div class='recurring-row-meta'>" +
                escapeHtml(_freqSummary(rt)) + " · " + escapeHtml(rt.type) +
                " · proj: " + escapeHtml(_projectName(rt.project_id)) +
                " · goal: " + escapeHtml(_goalTitle(rt.goal_id)) +
                (rt.is_active ? "" : " · <strong>PAUSED</strong>") +
            "</div>";
        row.appendChild(info);
        return row;
    }

    function escapeHtml(s) {
        if (s === null || s === undefined) return "";
        var d = document.createElement("div");
        d.textContent = String(s);
        return d.innerHTML;
    }

    async function load() {
        var [tpls, projs, gls] = await Promise.all([
            fetch("/api/recurring?active_only=false").then(function (r) { return r.json(); }),
            fetch("/api/projects").then(function (r) { return r.json(); }),
            fetch("/api/goals").then(function (r) { return r.json(); }),
        ]);
        allTemplates = Array.isArray(tpls) ? tpls : [];
        allProjects = Array.isArray(projs) ? projs : [];
        allGoals = Array.isArray(gls) ? gls : [];
        render();
    }

    function render() {
        var list = document.getElementById("recurringList");
        list.innerHTML = "";
        if (allTemplates.length === 0) {
            list.innerHTML = "<p class='empty-goals'>No recurring templates yet.</p>";
            return;
        }
        for (var i = 0; i < allTemplates.length; i++) {
            list.appendChild(renderRow(allTemplates[i]));
        }
        updateToolbar();
    }

    function showDropdown(anchor, items) {
        document.querySelectorAll(".bulk-dropdown").forEach(function (d) { d.remove(); });
        var dd = document.createElement("div");
        dd.className = "bulk-dropdown";
        dd.style.position = "fixed";
        var rect = anchor.getBoundingClientRect();
        dd.style.top = (rect.bottom + 4) + "px";
        dd.style.left = rect.left + "px";
        items.forEach(function (item) {
            var b = document.createElement("button");
            b.type = "button";
            b.textContent = item.label;
            b.addEventListener("click", function () {
                dd.remove();
                item.onClick();
            });
            dd.appendChild(b);
        });
        document.body.appendChild(dd);
        setTimeout(function () {
            document.addEventListener("click", function close(e) {
                if (!dd.contains(e.target) && e.target !== anchor) {
                    dd.remove();
                    document.removeEventListener("click", close);
                }
            });
        }, 0);
    }

    async function bulkPatch(updates) {
        var ids = getSelectedIds();
        if (!ids.length) return;
        var resp = await fetch("/api/recurring/bulk", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ template_ids: ids, updates: updates }),
        });
        var data = await resp.json();
        if (data.errors && data.errors.length) {
            alert("Updated " + data.updated + " — " + data.errors.length + " error(s): " +
                data.errors.map(function (e) { return e.error; }).join(", "));
        }
        await load();
    }

    async function bulkDelete() {
        var ids = getSelectedIds();
        if (!ids.length) return;
        if (!confirm("Delete " + ids.length + " template(s)? They stop spawning new tasks.")) return;
        await fetch("/api/recurring/bulk", {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ template_ids: ids }),
        });
        await load();
    }

    function init() {
        document.getElementById("recurringSelectToggle").addEventListener("click", function () {
            var rows = document.querySelectorAll(".recurring-row");
            for (var i = 0; i < rows.length; i++) rows[i].classList.toggle("select-mode");
        });
        document.getElementById("recurringBulkType").addEventListener("click", function (e) {
            showDropdown(e.currentTarget, [
                { label: "Work", onClick: function () { bulkPatch({ type: "work" }); } },
                { label: "Personal", onClick: function () { bulkPatch({ type: "personal" }); } },
            ]);
        });
        document.getElementById("recurringBulkFrequency").addEventListener("click", function (e) {
            showDropdown(e.currentTarget, [
                { label: "Daily", onClick: function () { bulkPatch({ frequency: "daily" }); } },
                { label: "Weekdays", onClick: function () { bulkPatch({ frequency: "weekdays" }); } },
            ]);
        });
        document.getElementById("recurringBulkProject").addEventListener("click", function (e) {
            var items = [{ label: "(none)", onClick: function () { bulkPatch({ project_id: null }); } }];
            allProjects.forEach(function (p) {
                items.push({ label: p.name, onClick: function () { bulkPatch({ project_id: p.id }); } });
            });
            showDropdown(e.currentTarget, items);
        });
        document.getElementById("recurringBulkGoal").addEventListener("click", function (e) {
            var items = [{ label: "(none)", onClick: function () { bulkPatch({ goal_id: null }); } }];
            allGoals.forEach(function (g) {
                items.push({ label: g.title, onClick: function () { bulkPatch({ goal_id: g.id }); } });
            });
            showDropdown(e.currentTarget, items);
        });
        document.getElementById("recurringBulkActive").addEventListener("click", function (e) {
            showDropdown(e.currentTarget, [
                { label: "Resume (active)", onClick: function () { bulkPatch({ is_active: true }); } },
                { label: "Pause (inactive)", onClick: function () { bulkPatch({ is_active: false }); } },
            ]);
        });
        document.getElementById("recurringBulkDelete").addEventListener("click", bulkDelete);

        load();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
