/**
 * Auto-categorize Inbox flow.
 *
 * Click the "💡 Auto-categorize" button on the Inbox tier header → POST
 * /api/inbox/categorize → review modal opens with one row per task,
 * each row pre-populated with Claude's suggested tier / project / goal
 * / due_date / type. User can override any cell, then Apply per row
 * or Apply all.
 *
 * Apply routes through PATCH /api/tasks/<id> — same canonical
 * mutation surface as the rest of the app, no separate write path.
 */
(function () {
    "use strict";

    var modal, table, rowsEl, loadingEl, errorEl, hintEl;
    var applyAllBtn, cancelBtn, closeBtn;
    var availableProjects = [];
    var availableGoals = [];
    var pendingSuggestions = [];

    document.addEventListener("DOMContentLoaded", function () {
        modal = document.getElementById("autoCategorizeModal");
        table = document.getElementById("autoCategorizeTable");
        rowsEl = document.getElementById("autoCategorizeRows");
        loadingEl = document.getElementById("autoCategorizeLoading");
        errorEl = document.getElementById("autoCategorizeError");
        hintEl = document.getElementById("autoCategorizeHint");
        applyAllBtn = document.getElementById("autoCategorizeApplyAll");
        cancelBtn = document.getElementById("autoCategorizeCancel");
        closeBtn = document.getElementById("autoCategorizeClose");
        var openBtn = document.getElementById("autoCategorizeBtn");
        if (!modal || !openBtn) { return; }

        openBtn.addEventListener("click", openModal);
        cancelBtn.addEventListener("click", closeModal);
        closeBtn.addEventListener("click", closeModal);
        applyAllBtn.addEventListener("click", applyAll);
        // Tap-outside-to-dismiss via the backdrop element.
        var backdrop = modal.querySelector(".auto-categorize-backdrop");
        if (backdrop) { backdrop.addEventListener("click", closeModal); }
    });

    // app.js calls this when the board renders so the button toggles
    // with the inbox cohort. Exposed on window so app.js can call
    // it without an import boundary.
    window.updateAutoCategorizeBtn = function () {
        var btn = document.getElementById("autoCategorizeBtn");
        if (!btn) { return; }
        var inboxCards = document.querySelectorAll('.tier[data-tier="inbox"] .task-card');
        btn.style.display = inboxCards.length > 0 ? "" : "none";
    };

    async function openModal() {
        modal.style.display = "";
        loadingEl.style.display = "";
        errorEl.style.display = "none";
        table.style.display = "none";
        applyAllBtn.style.display = "none";
        rowsEl.innerHTML = "";

        // Fetch the projects + goals lists so the dropdowns can offer
        // overrides even when Claude's suggested ID matches one of them.
        try {
            var [projects, goals] = await Promise.all([
                window.apiFetch("/api/projects").catch(function () { return []; }),
                window.apiFetch("/api/goals").catch(function () { return []; }),
            ]);
            availableProjects = Array.isArray(projects) ? projects : [];
            availableGoals = Array.isArray(goals) ? goals : [];
        } catch (e) {
            availableProjects = [];
            availableGoals = [];
        }

        var result;
        try {
            result = await window.apiFetch("/api/inbox/categorize", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({}),
            });
        } catch (err) {
            loadingEl.style.display = "none";
            errorEl.style.display = "";
            errorEl.textContent =
                "Couldn't reach the categorizer: " + (err.message || err);
            return;
        }

        loadingEl.style.display = "none";
        var suggestions = (result && result.suggestions) || [];
        if (suggestions.length === 0) {
            hintEl.textContent = "Inbox is empty — nothing to categorize.";
            return;
        }
        if (result.capped) {
            hintEl.textContent =
                "Showing the first " + suggestions.length +
                " inbox tasks (cap reached). Apply these, then re-run for the rest.";
        }
        pendingSuggestions = suggestions;
        renderRows(suggestions);
        table.style.display = "";
        applyAllBtn.style.display = "";
        applyAllBtn.textContent = "Apply all (" + suggestions.length + ")";
    }

    function closeModal() {
        modal.style.display = "none";
        rowsEl.innerHTML = "";
        pendingSuggestions = [];
    }

    function renderRows(suggestions) {
        rowsEl.innerHTML = "";
        suggestions.forEach(function (s) {
            rowsEl.appendChild(renderRow(s));
        });
    }

    function renderRow(s) {
        var tr = document.createElement("tr");
        tr.dataset.taskId = s.task_id;
        tr.appendChild(td(textNode(s.title), "auto-categorize-title", s.reason));
        tr.appendChild(td(tierSelect(s.suggested_tier), "auto-categorize-tier"));
        tr.appendChild(td(projectSelect(s.suggested_project_id, s.suggested_type), "auto-categorize-project"));
        tr.appendChild(td(goalSelect(s.suggested_goal_id), "auto-categorize-goal"));
        tr.appendChild(td(dueInput(s.suggested_due_date), "auto-categorize-due"));
        tr.appendChild(td(typeSelect(s.suggested_type), "auto-categorize-type"));
        tr.appendChild(td(rowApplyBtn(), "auto-categorize-actions"));
        return tr;
    }

    function td(child, cls, titleAttr) {
        var el = document.createElement("td");
        if (cls) { el.className = cls; }
        if (titleAttr) { el.title = titleAttr; }
        el.appendChild(child);
        return el;
    }

    function textNode(text) {
        var span = document.createElement("span");
        span.textContent = text;
        return span;
    }

    function tierSelect(current) {
        return makeSelect([
            ["today", "Today"],
            ["tomorrow", "Tomorrow"],
            ["this_week", "This Week"],
            ["next_week", "Next Week"],
            ["backlog", "Backlog"],
            ["freezer", "Freezer"],
        ], current, "tier");
    }

    function typeSelect(current) {
        return makeSelect([
            ["work", "Work"],
            ["personal", "Personal"],
        ], current, "type");
    }

    function projectSelect(current, type) {
        var options = [["", "— None —"]];
        availableProjects.forEach(function (p) {
            if (!p.is_active && p.is_active !== undefined) { return; }
            // Type-scope per #98 if type known.
            if (type && p.type && p.type !== type) { return; }
            options.push([p.id, p.title]);
        });
        return makeSelect(options, current || "", "project");
    }

    function goalSelect(current) {
        var options = [["", "— None —"]];
        availableGoals.forEach(function (g) {
            options.push([g.id, g.title]);
        });
        return makeSelect(options, current || "", "goal");
    }

    function dueInput(current) {
        var input = document.createElement("input");
        input.type = "date";
        input.dataset.field = "due_date";
        if (current) { input.value = current; }
        return input;
    }

    function makeSelect(options, current, field) {
        var sel = document.createElement("select");
        sel.dataset.field = field;
        options.forEach(function (pair) {
            var opt = document.createElement("option");
            opt.value = pair[0];
            opt.textContent = pair[1];
            if (pair[0] === current) { opt.selected = true; }
            sel.appendChild(opt);
        });
        return sel;
    }

    function rowApplyBtn() {
        var btn = document.createElement("button");
        btn.className = "btn btn-sm";
        btn.type = "button";
        btn.textContent = "Apply";
        btn.addEventListener("click", function () { applyRow(btn.closest("tr")); });
        return btn;
    }

    async function applyRow(tr) {
        var btn = tr.querySelector("button");
        btn.disabled = true;
        btn.textContent = "…";
        var payload = readRow(tr);
        try {
            await window.apiFetch("/api/tasks/" + tr.dataset.taskId, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            tr.remove();
            updateAfterRowChange();
        } catch (err) {
            btn.disabled = false;
            btn.textContent = "Retry";
            console.error("auto-categorize apply failed:", err);
        }
    }

    async function applyAll() {
        applyAllBtn.disabled = true;
        applyAllBtn.textContent = "Applying…";
        var rows = Array.from(rowsEl.querySelectorAll("tr"));
        var failed = 0;
        for (var i = 0; i < rows.length; i++) {
            var tr = rows[i];
            try {
                await window.apiFetch("/api/tasks/" + tr.dataset.taskId, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(readRow(tr)),
                });
                tr.remove();
            } catch (err) {
                failed++;
                tr.classList.add("auto-categorize-row-failed");
            }
        }
        applyAllBtn.disabled = false;
        if (failed === 0) {
            closeModal();
            // Re-fetch the board so the categorized tasks render in
            // their new tiers without a hard refresh.
            if (typeof window.loadTasks === "function") { window.loadTasks(); }
        } else {
            applyAllBtn.textContent = "Apply remaining (" + failed + " failed)";
        }
    }

    function readRow(tr) {
        var get = function (field) {
            var el = tr.querySelector('[data-field="' + field + '"]');
            return el ? (el.value || null) : null;
        };
        var payload = {
            tier: get("tier"),
            type: get("type"),
        };
        var project = get("project");
        var goal = get("goal");
        var due = get("due_date");
        // Server treats "" as no-change; null clears. Client policy:
        // empty selects mean "leave null on the server".
        payload.project_id = project || null;
        payload.goal_id = goal || null;
        payload.due_date = due || null;
        return payload;
    }

    function updateAfterRowChange() {
        var remaining = rowsEl.querySelectorAll("tr").length;
        if (remaining === 0) {
            closeModal();
            if (typeof window.loadTasks === "function") { window.loadTasks(); }
        } else {
            applyAllBtn.textContent = "Apply all (" + remaining + ")";
        }
    }
})();
