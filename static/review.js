/**
 * Weekly Review flow — step through stale tasks one at a time.
 *
 * How it works:
 * 1. On page load, fetch all stale tasks from GET /api/review
 * 2. Show one task at a time with action buttons (Keep, Freeze, Snooze, Delete)
 * 3. When the user picks an action, POST /api/review/<id> with the action
 * 4. Move to the next task and update the progress bar
 * 5. After all tasks are reviewed, show a summary (kept: X, frozen: Y, etc.)
 */

(function () {
    "use strict";

    const API = "/api/review";

    let tasks = [];       // all stale tasks loaded from the API
    let currentIndex = 0; // which task we're currently showing
    let summary = { keep: 0, freeze: 0, snooze: 0, delete: 0 };

    // --- DOM refs ---------------------------------------------------------------

    const loadingEl = document.getElementById("reviewLoading");
    const emptyEl = document.getElementById("reviewEmpty");
    const cardEl = document.getElementById("reviewCard");
    const summaryEl = document.getElementById("reviewSummary");

    const progressFill = document.getElementById("reviewProgressFill");
    const progressText = document.getElementById("reviewProgressText");

    const titleEl = document.getElementById("reviewTaskTitle");
    const metaEl = document.getElementById("reviewTaskMeta");
    const notesEl = document.getElementById("reviewTaskNotes");
    const checklistEl = document.getElementById("reviewTaskChecklist");
    const statsEl = document.getElementById("reviewSummaryStats");

    // --- Helpers ----------------------------------------------------------------

    async function apiFetch(url, opts) {
        const resp = await fetch(url, {
            headers: { "Content-Type": "application/json" },
            ...opts,
        });
        if (!resp.ok) {
            const body = await resp.json().catch(() => ({}));
            throw new Error(body.error || resp.statusText);
        }
        return resp.json();
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    // --- Rendering --------------------------------------------------------------

    function showSection(section) {
        loadingEl.style.display = "none";
        emptyEl.style.display = "none";
        cardEl.style.display = "none";
        summaryEl.style.display = "none";
        section.style.display = "";
    }

    function updateProgress() {
        const total = tasks.length;
        const done = currentIndex;
        const pct = total > 0 ? Math.round((done / total) * 100) : 0;
        progressFill.style.width = pct + "%";
        progressText.textContent = done + " of " + total + " reviewed";
    }

    function renderTask(task) {
        titleEl.textContent = task.title;

        // Meta badges (tier, type, due date)
        let metaHtml = "";
        metaHtml += '<span class="badge badge-' + escapeHtml(task.type) + '">' +
                    escapeHtml(task.type) + "</span> ";
        metaHtml += '<span class="badge">' + escapeHtml(task.tier) + "</span> ";
        if (task.due_date) {
            metaHtml += '<span class="badge badge-due">' +
                        escapeHtml(task.due_date) + "</span> ";
        }
        if (task.last_reviewed) {
            metaHtml += '<span class="badge">reviewed: ' +
                        escapeHtml(task.last_reviewed) + "</span>";
        } else {
            metaHtml += '<span class="badge">never reviewed</span>';
        }
        metaEl.innerHTML = metaHtml;

        // Notes
        if (task.notes) {
            notesEl.style.display = "";
            notesEl.textContent = task.notes;
        } else {
            notesEl.style.display = "none";
        }

        // Checklist
        if (task.checklist && task.checklist.length > 0) {
            checklistEl.style.display = "";
            const done = task.checklist.filter(function (c) { return c.checked; }).length;
            let clHtml = "<strong>Checklist (" + done + "/" + task.checklist.length + ")</strong><ul>";
            for (const item of task.checklist) {
                const icon = item.checked ? "&#9745;" : "&#9744;";
                clHtml += "<li>" + icon + " " + escapeHtml(item.text) + "</li>";
            }
            clHtml += "</ul>";
            checklistEl.innerHTML = clHtml;
        } else {
            checklistEl.style.display = "none";
        }

        updateProgress();
    }

    function showCurrentTask() {
        if (currentIndex >= tasks.length) {
            showSummary();
            return;
        }
        showSection(cardEl);
        renderTask(tasks[currentIndex]);
    }

    function showSummary() {
        showSection(summaryEl);

        let html = "<ul>";
        if (summary.keep > 0) html += "<li><strong>" + summary.keep + "</strong> kept</li>";
        if (summary.freeze > 0) html += "<li><strong>" + summary.freeze + "</strong> frozen</li>";
        if (summary.snooze > 0) html += "<li><strong>" + summary.snooze + "</strong> snoozed</li>";
        if (summary.delete > 0) html += "<li><strong>" + summary.delete + "</strong> deleted</li>";
        html += "</ul>";
        html += "<p>Total reviewed: <strong>" + tasks.length + "</strong></p>";
        statsEl.innerHTML = html;
    }

    // --- Actions ----------------------------------------------------------------

    async function handleAction(action) {
        const task = tasks[currentIndex];
        try {
            await apiFetch(API + "/" + task.id, {
                method: "POST",
                body: JSON.stringify({ action: action }),
            });
            summary[action]++;
            currentIndex++;
            showCurrentTask();
        } catch (err) {
            alert("Review action failed: " + err.message);
        }
    }

    // --- Init -------------------------------------------------------------------

    async function init() {
        // #12 — fetch triage suggestions in parallel with stale tasks.
        // Independent surfaces, so race them; the suggestions panel
        // renders even if /api/review fails (and vice versa).
        loadTriageSuggestions().catch(function (err) {
            console.warn("triage suggestions failed:", err);
        });

        try {
            tasks = await apiFetch(API);
        } catch (err) {
            loadingEl.innerHTML = "<h2>Failed to load review items</h2><p>" +
                                  escapeHtml(err.message) + "</p>";
            return;
        }

        if (tasks.length === 0) {
            showSection(emptyEl);
            return;
        }

        currentIndex = 0;
        summary = { keep: 0, freeze: 0, snooze: 0, delete: 0 };
        showCurrentTask();
    }

    // --- #12 Triage suggestions -----------------------------------------------

    async function loadTriageSuggestions() {
        var section = document.getElementById("triageSuggestions");
        var list = document.getElementById("triageList");
        var countEl = document.getElementById("triageCount");
        if (!section || !list) { return; }

        var suggestions;
        try {
            suggestions = await apiFetch("/api/triage/suggestions");
        } catch (err) {
            return;  // silent — non-critical surface
        }
        if (!Array.isArray(suggestions) || suggestions.length === 0) { return; }

        countEl.textContent = "(" + suggestions.length + ")";
        list.innerHTML = "";
        suggestions.forEach(function (s) { list.appendChild(renderTriageRow(s)); });
        section.style.display = "";
    }

    function renderTriageRow(s) {
        var li = document.createElement("li");
        li.className = "triage-row";
        li.dataset.taskId = s.task_id;

        var actionLabel;
        if (s.suggested_action === "delete") {
            actionLabel = "Delete";
        } else {
            actionLabel = "→ " + tierLabel(s.suggested_tier);
        }

        li.innerHTML =
            '<div class="triage-row-main">' +
                '<span class="triage-title"></span>' +
                '<span class="triage-meta">' +
                    '<span class="triage-tier"></span>' +
                    ' · <span class="triage-reason"></span>' +
                '</span>' +
            '</div>' +
            '<div class="triage-row-actions">' +
                '<button class="btn btn-sm triage-apply" type="button"></button>' +
                '<button class="btn btn-sm triage-dismiss" type="button" title="Hide for now">Dismiss</button>' +
            '</div>';

        li.querySelector(".triage-title").textContent = s.title;
        li.querySelector(".triage-tier").textContent = tierLabel(s.current_tier);
        li.querySelector(".triage-reason").textContent = s.reason;
        var applyBtn = li.querySelector(".triage-apply");
        applyBtn.textContent = actionLabel;
        applyBtn.addEventListener("click", function () { applySuggestion(s, li); });
        li.querySelector(".triage-dismiss").addEventListener("click", function () {
            li.remove();
            updateTriageCount();
        });
        return li;
    }

    function tierLabel(tier) {
        // Match user-facing labels used elsewhere in the app.
        var map = {
            inbox: "Inbox",
            today: "Today",
            tomorrow: "Tomorrow",
            this_week: "This Week",
            next_week: "Next Week",
            backlog: "Backlog",
            freezer: "Freezer",
        };
        return map[tier] || tier;
    }

    async function applySuggestion(s, rowEl) {
        var applyBtn = rowEl.querySelector(".triage-apply");
        applyBtn.disabled = true;
        applyBtn.textContent = "…";
        try {
            if (s.suggested_action === "delete") {
                await apiFetch("/api/tasks/" + s.task_id, { method: "DELETE" });
            } else {
                await apiFetch("/api/tasks/" + s.task_id, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ tier: s.suggested_tier }),
                });
            }
            rowEl.remove();
            updateTriageCount();
        } catch (err) {
            applyBtn.disabled = false;
            applyBtn.textContent = "Retry";
            console.error("triage apply failed:", err);
        }
    }

    function updateTriageCount() {
        var section = document.getElementById("triageSuggestions");
        var list = document.getElementById("triageList");
        var countEl = document.getElementById("triageCount");
        if (!section || !list) { return; }
        var n = list.children.length;
        if (n === 0) {
            section.style.display = "none";
        } else {
            countEl.textContent = "(" + n + ")";
        }
    }

    // Bind action buttons
    document.querySelectorAll(".review-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
            handleAction(btn.dataset.action);
        });
    });

    document.addEventListener("DOMContentLoaded", init);
})();
