/**
 * Weekly planner — review-then-execute flow.
 *
 * Page-level layout (vs. modal in /inbox-categorize) because the plan
 * has more sections (day-by-day, goal hints, velocity, stale freezer)
 * than fit a modal cleanly. Same review-before-apply discipline:
 * suggestions render with editable selects + Accept / Override / Ignore
 * per row; "Apply all accepted" routes through PATCH /api/tasks/<id>
 * (or POST /api/planner/ignore for ignore-flag toggles).
 */
(function () {
    "use strict";

    var availableProjects = [];
    var availableGoals = [];
    var lastPlan = null;
    var rowState = {};  // task_id → "pending" | "accepted" | "ignored"

    function $(id) { return document.getElementById(id); }

    function nextMondayIso() {
        var d = new Date();
        var dow = d.getDay();  // 0=Sun..6=Sat
        // Convert to Mon=0..Sun=6 for symmetry with Python's weekday().
        var mon = (dow + 6) % 7;
        var daysUntilMon = (7 - mon) % 7;
        if (daysUntilMon === 0) { daysUntilMon = 7; }
        d.setDate(d.getDate() + daysUntilMon);
        return d.toISOString().slice(0, 10);
    }

    function tierLabel(tier) {
        return ({
            today: "Today", tomorrow: "Tomorrow",
            this_week: "This Week", next_week: "Next Week",
            backlog: "Backlog", freezer: "Freezer", inbox: "Inbox",
        })[tier] || tier;
    }

    function statusBadge(s) {
        return ({
            on_track: "✅ on track",
            falling_behind: "⚠ falling behind",
            no_progress: "○ no progress this week",
            ahead: "🚀 ahead of schedule",
        })[s] || s;
    }

    document.addEventListener("DOMContentLoaded", function () {
        var dateInput = $("planStartDate");
        dateInput.value = nextMondayIso();
        $("planGenerateBtn").addEventListener("click", generate);
        $("planApplyAllBtn").addEventListener("click", applyAll);
        $("planApplyAllBtn").style.display = "none";

        // Load project + goal lists once so override selects work.
        Promise.all([
            window.apiFetch("/api/projects").catch(function () { return []; }),
            window.apiFetch("/api/goals").catch(function () { return []; }),
        ]).then(function (results) {
            availableProjects = Array.isArray(results[0]) ? results[0] : [];
            availableGoals = Array.isArray(results[1]) ? results[1] : [];
        });
    });

    async function generate() {
        var startDate = $("planStartDate").value;
        if (!startDate) { return; }
        $("planLoading").style.display = "";
        $("planError").style.display = "none";
        $("planResults").style.display = "none";
        $("planApplyAllBtn").style.display = "none";
        rowState = {};

        var plan;
        try {
            plan = await window.apiFetch("/api/planner/weekly", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ start_date: startDate }),
            });
        } catch (err) {
            $("planLoading").style.display = "none";
            $("planError").style.display = "";
            $("planError").textContent = "Couldn't generate plan: " + (err.message || err);
            return;
        }
        $("planLoading").style.display = "none";
        lastPlan = plan;
        renderPlan(plan);
    }

    function renderPlan(plan) {
        $("planResults").style.display = "";

        // Summary
        $("planSummary").innerHTML =
            '<p>Plan for <strong>' + plan.start_date + '</strong> through <strong>' + plan.end_date + '</strong> — ' +
            plan.active_count + ' active task(s), ' + plan.stale_freezer_count + ' stale freezer item(s).</p>';

        // Velocity warning
        var vw = $("planVelocityWarning");
        if (plan.velocity_warning) {
            vw.style.display = "";
            $("planVelocityText").textContent = plan.velocity_warning;
        } else {
            vw.style.display = "none";
        }

        // Goal hints
        renderGoalHints(plan.goal_hints || []);

        // Day-by-day plan + leftover suggestions
        renderDays(plan);

        // Stale freezer review
        renderStaleFreezer(plan.stale_freezer_review || []);

        $("planApplyAllBtn").style.display = "";
        updateAppliedCount();
    }

    function renderGoalHints(hints) {
        var ul = $("planGoalList");
        ul.innerHTML = "";
        if (hints.length === 0) {
            ul.innerHTML = "<li class='plan-empty'>No goals tracked yet.</li>";
            return;
        }
        hints.forEach(function (h) {
            var li = document.createElement("li");
            li.className = "plan-goal-row plan-goal-" + h.status;
            li.innerHTML =
                '<span class="plan-goal-title"></span> ' +
                '<span class="plan-goal-status"></span><br>' +
                '<span class="plan-goal-rec"></span>';
            li.querySelector(".plan-goal-title").textContent = h.goal_title || h.goal_id;
            li.querySelector(".plan-goal-status").textContent = statusBadge(h.status);
            li.querySelector(".plan-goal-rec").textContent = h.recommendation;
            ul.appendChild(li);
        });
    }

    function renderDays(plan) {
        var container = $("planDaysContainer");
        container.innerHTML = "";
        var dayNames = ["Monday", "Tuesday", "Wednesday", "Thursday",
                        "Friday", "Saturday", "Sunday"];
        var taskById = {};
        (plan.per_task_suggestions || []).forEach(function (s) { taskById[s.task_id] = s; });
        var placedIds = new Set();

        dayNames.forEach(function (day) {
            var taskIds = (plan.day_by_day_plan || {})[day] || [];
            if (taskIds.length === 0) { return; }
            var section = document.createElement("div");
            section.className = "plan-day";
            var heading = document.createElement("h3");
            heading.textContent = day + " (" + taskIds.length + ")";
            section.appendChild(heading);
            var ul = document.createElement("ul");
            ul.className = "plan-day-list";
            taskIds.forEach(function (tid) {
                placedIds.add(tid);
                var s = taskById[tid];
                if (!s) { return; }
                ul.appendChild(renderSuggestionRow(s));
            });
            section.appendChild(ul);
            container.appendChild(section);
        });

        // Suggestions not assigned to a specific day (action != "move" or no due_date)
        var otherUl = $("planOtherList");
        otherUl.innerHTML = "";
        var others = (plan.per_task_suggestions || []).filter(function (s) {
            return !placedIds.has(s.task_id);
        });
        if (others.length === 0) {
            otherUl.innerHTML = "<li class='plan-empty'>Every active task has a recommended day.</li>";
        } else {
            others.forEach(function (s) { otherUl.appendChild(renderSuggestionRow(s)); });
        }
    }

    function renderSuggestionRow(s) {
        var li = document.createElement("li");
        li.className = "plan-row";
        li.dataset.taskId = s.task_id;
        rowState[s.task_id] = rowState[s.task_id] || "pending";

        var actionEmoji = ({move: "↪", keep: "✓", delete: "✗", freeze: "❄"})[s.action] || "?";

        li.innerHTML =
            '<div class="plan-row-main">' +
                '<span class="plan-row-action"></span> ' +
                '<span class="plan-row-title"></span>' +
                '<div class="plan-row-meta"></div>' +
                '<div class="plan-row-reason"></div>' +
            '</div>' +
            '<div class="plan-row-controls"></div>' +
            '<div class="plan-row-actions">' +
                '<button class="btn btn-sm plan-accept" type="button">Accept</button>' +
                '<button class="btn btn-sm plan-ignore" type="button" title="Stop suggesting this">Ignore</button>' +
            '</div>';

        li.querySelector(".plan-row-action").textContent = actionEmoji + " " + s.action.toUpperCase();
        li.querySelector(".plan-row-title").textContent = s.title;
        var meta = li.querySelector(".plan-row-meta");
        if (s.action === "move") {
            var bits = [];
            if (s.suggested_tier) { bits.push("→ " + tierLabel(s.suggested_tier)); }
            if (s.suggested_due_date) { bits.push("due " + s.suggested_due_date); }
            meta.textContent = bits.join("  ·  ");
        }
        li.querySelector(".plan-row-reason").textContent = s.reason || "";

        // Override controls — render based on action.
        var controls = li.querySelector(".plan-row-controls");
        if (s.action === "move") {
            controls.appendChild(makeTierSelect(s.suggested_tier));
            controls.appendChild(makeDueDateInput(s.suggested_due_date));
        }
        controls.appendChild(makeProjectSelect(s.suggested_project_id));
        controls.appendChild(makeGoalSelect(s.suggested_goal_id));

        li.querySelector(".plan-accept").addEventListener("click", function () { acceptRow(li, s); });
        li.querySelector(".plan-ignore").addEventListener("click", function () { ignoreRow(li, s); });
        return li;
    }

    function makeTierSelect(current) {
        return makeSelect([
            ["today", "Today"], ["tomorrow", "Tomorrow"],
            ["this_week", "This Week"], ["next_week", "Next Week"],
            ["backlog", "Backlog"], ["freezer", "Freezer"],
        ], current || "", "tier");
    }

    function makeDueDateInput(current) {
        var input = document.createElement("input");
        input.type = "date";
        input.dataset.field = "due_date";
        if (current) { input.value = current; }
        return input;
    }

    function makeProjectSelect(current) {
        var opts = [["", "— project —"]];
        availableProjects.forEach(function (p) {
            if (p.is_active === false) { return; }
            opts.push([p.id, p.name]);
        });
        return makeSelect(opts, current || "", "project");
    }

    function makeGoalSelect(current) {
        var opts = [["", "— goal —"]];
        availableGoals.forEach(function (g) {
            opts.push([g.id, g.title]);
        });
        return makeSelect(opts, current || "", "goal");
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

    async function acceptRow(li, s) {
        var btn = li.querySelector(".plan-accept");
        btn.disabled = true;
        btn.textContent = "…";
        try {
            await applyOne(li, s);
            rowState[s.task_id] = "accepted";
            li.classList.add("plan-row-applied");
            btn.textContent = "Applied ✓";
            updateAppliedCount();
        } catch (err) {
            btn.disabled = false;
            btn.textContent = "Retry";
            console.error("plan accept failed:", err);
        }
    }

    async function ignoreRow(li, s) {
        var btn = li.querySelector(".plan-ignore");
        btn.disabled = true;
        try {
            await window.apiFetch("/api/planner/ignore/" + s.task_id, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ ignore: true }),
            });
            rowState[s.task_id] = "ignored";
            li.classList.add("plan-row-ignored");
            btn.textContent = "Ignored";
            updateAppliedCount();
        } catch (err) {
            btn.disabled = false;
            console.error("plan ignore failed:", err);
        }
    }

    function readOverrides(li, s) {
        var get = function (field) {
            var el = li.querySelector('[data-field="' + field + '"]');
            return el ? (el.value || null) : null;
        };
        var payload = {};
        if (s.action === "move") {
            var tier = get("tier") || s.suggested_tier;
            if (tier) { payload.tier = tier; }
            var due = get("due_date") || s.suggested_due_date;
            if (due !== undefined) { payload.due_date = due; }
        } else if (s.action === "freeze") {
            payload.tier = "freezer";
        } else if (s.action === "delete") {
            // Delete is handled separately via DELETE method.
            payload._delete = true;
        }
        var proj = get("project");
        if (proj !== null) { payload.project_id = proj || null; }
        var goal = get("goal");
        if (goal !== null) { payload.goal_id = goal || null; }
        return payload;
    }

    async function applyOne(li, s) {
        var payload = readOverrides(li, s);
        if (payload._delete) {
            await window.apiFetch("/api/tasks/" + s.task_id, { method: "DELETE" });
            return;
        }
        if (Object.keys(payload).length === 0) { return; }  // keep
        await window.apiFetch("/api/tasks/" + s.task_id, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
    }

    async function applyAll() {
        var rows = Array.from(document.querySelectorAll(".plan-row"));
        var pending = rows.filter(function (r) {
            return rowState[r.dataset.taskId] === "pending";
        });
        if (pending.length === 0) { return; }
        $("planApplyAllBtn").disabled = true;
        $("planApplyAllBtn").textContent = "Applying…";
        var failed = 0;
        for (var i = 0; i < pending.length; i++) {
            var li = pending[i];
            var sugg = (lastPlan.per_task_suggestions || [])
                .find(function (x) { return x.task_id === li.dataset.taskId; });
            if (!sugg) { continue; }
            try {
                await applyOne(li, sugg);
                rowState[li.dataset.taskId] = "accepted";
                li.classList.add("plan-row-applied");
            } catch (err) {
                failed++;
                li.classList.add("plan-row-failed");
            }
        }
        $("planApplyAllBtn").disabled = false;
        $("planApplyAllBtn").textContent = "Apply all accepted";
        updateAppliedCount(failed);
    }

    function updateAppliedCount(failed) {
        var rows = Object.values(rowState);
        var accepted = rows.filter(function (s) { return s === "accepted"; }).length;
        var ignored = rows.filter(function (s) { return s === "ignored"; }).length;
        var pending = rows.length - accepted - ignored;
        var bits = [accepted + " accepted", ignored + " ignored", pending + " pending"];
        if (failed) { bits.push(failed + " failed"); }
        $("planAppliedCount").textContent = bits.join("  ·  ");
    }

    function renderStaleFreezer(items) {
        var section = $("planStaleFreezer");
        var ul = $("planStaleList");
        ul.innerHTML = "";
        if (items.length === 0) {
            section.style.display = "none";
            return;
        }
        section.style.display = "";
        items.forEach(function (s) {
            var li = document.createElement("li");
            li.className = "plan-stale-row";
            li.innerHTML =
                '<span class="plan-stale-title"></span> — ' +
                '<span class="plan-stale-rec"></span>' +
                '<span class="plan-stale-reason"></span>';
            li.querySelector(".plan-stale-title").textContent = s.title;
            li.querySelector(".plan-stale-rec").textContent = s.recommendation;
            li.querySelector(".plan-stale-reason").textContent = s.reason ? " (" + s.reason + ")" : "";
            ul.appendChild(li);
        });
    }
})();
