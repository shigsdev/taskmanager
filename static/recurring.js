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
        // #147 (2026-05-02): show sunrise date when set. Pair-symmetric
        // with end_date below; both can coexist ("from X until Y").
        if (rt.start_date) base += " (from " + rt.start_date + ")";
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
        // #266: click the row body to edit the template — unless we're in
        // bulk-select mode, where a click toggles the checkbox instead.
        info.style.cursor = "pointer";
        info.addEventListener("click", function () {
            if (row.classList.contains("select-mode")) {
                cb.checked = !cb.checked;
                updateToolbar();
            } else {
                openEditor(rt);
            }
        });
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
        // PR67 #132: window.apiFetch (auto-retry + recovery)
        var [tpls, projs, gls] = await Promise.all([
            window.apiFetch("/api/recurring?active_only=false"),
            window.apiFetch("/api/projects"),
            window.apiFetch("/api/goals"),
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
        try {
            // PR67 #132: window.apiFetch (auto-retry + recovery)
            var data = await window.apiFetch("/api/recurring/bulk", {
                method: "PATCH",
                body: JSON.stringify({ template_ids: ids, updates: updates }),
            });
            if (data && data.errors && data.errors.length) {
                alert("Updated " + data.updated + " — " + data.errors.length + " error(s): " +
                    data.errors.map(function (e) { return e.error; }).join(", "));
            }
        } catch (err) {
            alert("Bulk update failed: " + err.message);
        }
        await load();
    }

    async function bulkDelete() {
        var ids = getSelectedIds();
        if (!ids.length) return;
        if (!confirm("Delete " + ids.length + " template(s)? They stop spawning new tasks.")) return;
        try {
            // PR67 #132: window.apiFetch (auto-retry + recovery)
            await window.apiFetch("/api/recurring/bulk", {
                method: "DELETE",
                body: JSON.stringify({ template_ids: ids }),
            });
        } catch (err) {
            alert("Bulk delete failed: " + err.message);
        }
        await load();
    }

    // ====================================================================
    // #266 — per-template editor (dedicated panel, task-detail-panel look).
    // ====================================================================

    var _editId = null;

    function _el(id) { return document.getElementById(id); }

    function _populateEditorDropdowns() {
        // Day-of-month options 1–31 (built once).
        var dom = _el("recurEditDayOfMonth");
        if (dom && dom.options.length === 0) {
            for (var d = 1; d <= 31; d++) {
                var o = document.createElement("option");
                o.value = String(d); o.textContent = String(d);
                dom.appendChild(o);
            }
        }
        // Project + Goal dropdowns (all projects/goals; — None — first).
        var proj = _el("recurEditProject");
        var goal = _el("recurEditGoal");
        proj.length = 1; goal.length = 1;  // keep the "— None —" option
        allProjects.forEach(function (p) {
            var o = document.createElement("option");
            o.value = p.id; o.textContent = p.name;
            proj.appendChild(o);
        });
        allGoals.forEach(function (g) {
            var o = document.createElement("option");
            o.value = g.id; o.textContent = g.title + " (" + g.category + ")";
            goal.appendChild(o);
        });
    }

    function recurEditFreqChanged() {
        var f = _el("recurEditFrequency").value;
        _el("recurEditWeeklyField").style.display = f === "weekly" ? "" : "none";
        _el("recurEditMultiDayField").style.display = f === "multi_day_of_week" ? "" : "none";
        _el("recurEditMonthlyDateField").style.display = f === "monthly_date" ? "" : "none";
        _el("recurEditMonthlyNthField").style.display = f === "monthly_nth_weekday" ? "" : "none";
    }

    function openEditor(rt) {
        _populateEditorDropdowns();
        _editId = rt.id;
        _el("recurEditId").value = rt.id;
        _el("recurEditTitle").value = rt.title || "";
        _el("recurEditFrequency").value = rt.frequency;
        _el("recurEditType").value = rt.type;
        _el("recurEditProject").value = rt.project_id || "";
        _el("recurEditGoal").value = rt.goal_id || "";
        _el("recurEditUrl").value = rt.url || "";
        _el("recurEditEndDate").value = rt.end_date || "";
        _el("recurEditNotes").value = rt.notes || "";
        // Frequency-specific fields.
        if (rt.day_of_week != null) {
            _el("recurEditDay").value = String(rt.day_of_week);
            _el("recurEditNthDay").value = String(rt.day_of_week);
        }
        if (rt.day_of_month != null) _el("recurEditDayOfMonth").value = String(rt.day_of_month);
        if (rt.week_of_month != null) _el("recurEditWeekOfMonth").value = String(rt.week_of_month);
        // Multi-day chips.
        document.querySelectorAll("#recurEditDays input[type=checkbox]")
            .forEach(function (c) { c.checked = false; });
        (rt.days_of_week || []).forEach(function (d) {
            var c = document.querySelector('#recurEditDays input[value="' + d + '"]');
            if (c) c.checked = true;
        });
        // Pause/Resume button reflects current state.
        _el("recurEditPause").textContent = rt.is_active ? "Pause" : "Resume";
        _el("recurEditPause").dataset.next = rt.is_active ? "false" : "true";
        _el("recurEditResult").textContent = "";
        recurEditFreqChanged();
        _el("recurEditOverlay").style.display = "";
    }

    function closeEditor() {
        _el("recurEditOverlay").style.display = "none";
        _editId = null;
    }

    function collectEditor() {
        var f = _el("recurEditFrequency").value;
        // Gather raw DOM values; the pure payload shaping (frequency
        // branching + stale-field clearing) lives in recurring_helpers.js
        // so it's Jest-tested (#266 / anti-pattern #3).
        return window.recurringHelpers.buildRecurringEditPayload({
            title: _el("recurEditTitle").value,
            frequency: f,
            type: _el("recurEditType").value,
            projectId: _el("recurEditProject").value,
            goalId: _el("recurEditGoal").value,
            url: _el("recurEditUrl").value,
            notes: _el("recurEditNotes").value,
            endDate: _el("recurEditEndDate").value,
            dayOfWeek: f === "monthly_nth_weekday"
                ? parseInt(_el("recurEditNthDay").value, 10)
                : parseInt(_el("recurEditDay").value, 10),
            daysOfWeek: Array.from(
                document.querySelectorAll("#recurEditDays input[type=checkbox]:checked"),
            ).map(function (c) { return parseInt(c.value, 10); }),
            dayOfMonth: parseInt(_el("recurEditDayOfMonth").value, 10),
            weekOfMonth: parseInt(_el("recurEditWeekOfMonth").value, 10),
        });
    }

    async function saveEditor(e) {
        if (e) e.preventDefault();
        if (!_editId) return;
        var resultEl = _el("recurEditResult");
        try {
            await window.apiFetch("/api/recurring/" + _editId, {
                method: "PATCH",
                body: JSON.stringify(collectEditor()),
            });
            closeEditor();
            await load();
        } catch (err) {
            resultEl.textContent = "Save failed: " + (err.message || err);
            resultEl.classList.add("utility-result-err");
        }
    }

    async function togglePauseEditor() {
        if (!_editId) return;
        var next = _el("recurEditPause").dataset.next === "true";
        try {
            await window.apiFetch("/api/recurring/" + _editId, {
                method: "PATCH",
                body: JSON.stringify({ is_active: next }),
            });
            closeEditor();
            await load();
        } catch (err) {
            _el("recurEditResult").textContent = "Failed: " + (err.message || err);
        }
    }

    async function deleteEditor() {
        if (!_editId) return;
        if (!window.confirm("Delete this recurring template? Existing spawned tasks are kept.")) return;
        try {
            await window.apiFetch("/api/recurring/" + _editId, { method: "DELETE" });
            closeEditor();
            await load();
        } catch (err) {
            _el("recurEditResult").textContent = "Delete failed: " + (err.message || err);
        }
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

        // #266: editor wiring.
        _el("recurEditFrequency").addEventListener("change", recurEditFreqChanged);
        _el("recurEditForm").addEventListener("submit", saveEditor);
        _el("recurEditClose").addEventListener("click", closeEditor);
        _el("recurEditPause").addEventListener("click", togglePauseEditor);
        _el("recurEditDelete").addEventListener("click", deleteEditor);
        _el("recurEditOverlay").addEventListener("click", function (e) {
            if (e.target === _el("recurEditOverlay")) closeEditor();  // backdrop click closes
        });

        load();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
