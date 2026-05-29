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

        // #211: re-sync the board's task cache BEFORE asking the
        // server to categorize. The Auto-categorize button visibility
        // is driven by what's rendered under the Inbox panel — if the
        // user moved/completed inbox items in another tab/device, the
        // cards on screen are stale, the visible inbox still looks
        // populated, and the server (correctly) returns count=0,
        // which surfaces as a confusing "Inbox is empty" message.
        // Fetching first makes the visible state match the server's
        // truth before the modal opens.
        if (typeof window.loadTasks === "function") {
            try { await window.loadTasks(); } catch (_) { /* non-fatal */ }
            // Re-run the button-visibility check so the button hides
            // itself if the refresh emptied the Inbox panel.
            if (typeof window.updateAutoCategorizeBtn === "function") {
                window.updateAutoCategorizeBtn();
            }
        }

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
        // The 4th td() arg is the mobile stacked-layout label (becomes
        // data-label → rendered by the CSS ::before). The title + apply
        // cells get none — the title is self-evident, the apply button
        // needs no label. #209: this replaced `content: attr(class)`,
        // which dumped raw class names ("AUTO-CATEGORIZE-TIER") and,
        // worse, rendered a stray label over the title cell.
        tr.appendChild(td(textNode(s.title), "auto-categorize-title", s.reason));
        tr.appendChild(td(tierSelect(s.suggested_tier), "auto-categorize-tier", null, "Section"));
        tr.appendChild(td(projectSelect(s.suggested_project_id, s.suggested_type), "auto-categorize-project", null, "Project"));
        tr.appendChild(td(goalSelect(s.suggested_goal_id, s.suggested_type), "auto-categorize-goal", null, "Goal"));
        tr.appendChild(td(dueInput(s.suggested_due_date, s.suggested_tier), "auto-categorize-due", null, "Due"));
        tr.appendChild(td(typeSelect(s.suggested_type), "auto-categorize-type", null, "Type"));
        tr.appendChild(td(rowApplyBtn(), "auto-categorize-actions"));

        // User-reported 2026-05-12: clicking Personal in the Type
        // dropdown left the Project list showing Work projects only
        // — same class as #98 / #142 (type-scope filter applied once
        // at row creation, never re-applied when type changed). Wire
        // a change listener that rebuilds both project + goal
        // dropdowns when type flips.
        var typeSel = tr.querySelector('select[data-field="type"]');
        if (typeSel) {
            typeSel.addEventListener("change", function () {
                var newType = typeSel.value;
                var projCell = tr.querySelector(".auto-categorize-project");
                var goalCell = tr.querySelector(".auto-categorize-goal");
                if (projCell) {
                    var prevProjVal = projCell.querySelector("select").value;
                    projCell.innerHTML = "";
                    projCell.appendChild(projectSelect(prevProjVal, newType));
                    _wireProjectCascade(tr);
                }
                if (goalCell) {
                    var prevGoalVal = goalCell.querySelector("select").value;
                    goalCell.innerHTML = "";
                    goalCell.appendChild(goalSelect(prevGoalVal, newType));
                }
            });
        }
        // #208 (2026-05-22): re-derive the due placeholder when the
        // tier changes. An explicit value (Claude's date, or one the
        // user typed — no data-auto flag) is left untouched; an empty
        // or auto-derived input snaps to the new tier's auto-fill date
        // (Today → today, Tomorrow → tomorrow, other tiers → cleared).
        var tierSel = tr.querySelector('select[data-field="tier"]');
        if (tierSel) {
            tierSel.addEventListener("change", function () {
                var dueEl = tr.querySelector('input[data-field="due_date"]');
                var H = window.inboxCategorizeHelpers;
                if (!dueEl || !H) { return; }
                var explicit = dueEl.dataset.auto === "1" ? "" : dueEl.value;
                var resolved = H.resolveDueForTier(
                    explicit, tierSel.value, _todayIso(),
                );
                dueEl.value = resolved.value;
                if (resolved.auto) { dueEl.dataset.auto = "1"; }
                else { delete dueEl.dataset.auto; }
            });
        }
        // #117 cascade on this row too — same pattern as the detail
        // panel (taskDetailProjectChanged). Wire ONCE on first render;
        // re-wire after the type-change rebuild via _wireProjectCascade.
        _wireProjectCascade(tr);
        return tr;
    }

    // User-reported follow-up 2026-05-12: picking a Project did not
    // auto-set the Goal even though the project has a goal_id. Mirror
    // the detail-panel cascade (#117) using the same pure helper.
    function _wireProjectCascade(tr) {
        var projSel = tr.querySelector('select[data-field="project"]');
        var goalSel = tr.querySelector('select[data-field="goal"]');
        if (!projSel || !goalSel || !window.filterHelpers) return;
        projSel.addEventListener("change", function () {
            var allowed = new Set(
                Array.from(goalSel.options).map(function (o) { return o.value; })
            );
            var newGoalId = window.filterHelpers.projectCascadeGoalId(
                projSel.value, availableProjects, allowed
            );
            // Always reset: empty string → "— None —"; real UUID
            // jumps to the matching option. Matches the detail-panel
            // 2026-05-04 UX fix — picking a new project that has its
            // own goal shouldn't leave the old project's goal in place.
            goalSel.value = newGoalId || "";
        });
    }

    function td(child, cls, titleAttr, label) {
        var el = document.createElement("td");
        if (cls) { el.className = cls; }
        if (titleAttr) { el.title = titleAttr; }
        // #209: data-label drives the mobile stacked-layout cell label
        // (CSS ::before). Cells without one render with no label.
        if (label) { el.dataset.label = label; }
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
            // Project model uses `name` (not `title` like Goal). Bug
            // 2026-05-08: was reading p.title, every option label
            // rendered blank, so even when Claude suggested a project
            // the dropdown looked empty.
            options.push([p.id, p.name]);
        });
        return makeSelect(options, current || "", "project");
    }

    function goalSelect(current, type) {
        var options = [["", "— None —"]];
        // #142 (2026-05-09) strict bipartition: work + bau → work-side,
        // health + relationships + personal_growth → personal-side.
        // Same filter the detail panel uses (window.goalFilterHelpers).
        // If no type is provided OR the helper isn't loaded, show all.
        var filtered = (type && window.goalFilterHelpers)
            ? window.goalFilterHelpers.filterGoalsByType(availableGoals, type)
            : availableGoals;
        filtered.forEach(function (g) {
            options.push([g.id, g.title]);
        });
        return makeSelect(options, current || "", "goal");
    }

    // Today as local "YYYY-MM-DD". Uses the shared dateHelpers (loaded
    // app-wide via base.html) so the modal's derived dates match every
    // other local-date computation in the app.
    function _todayIso() {
        if (window.dateHelpers && window.dateHelpers.localIsoDate) {
            return window.dateHelpers.localIsoDate();
        }
        var d = new Date();
        return (
            d.getFullYear()
            + "-" + String(d.getMonth() + 1).padStart(2, "0")
            + "-" + String(d.getDate()).padStart(2, "0")
        );
    }

    // #208 (2026-05-22): the due input now pre-fills from the tier when
    // Claude didn't suggest a date — Today → today, Tomorrow → tomorrow
    // — so the user SEES the date the server's tier→date auto-fill will
    // stamp. A derived placeholder carries data-auto="1"; readRow omits
    // those from the PATCH so the server produces the authoritative
    // date. A real value (Claude's suggestion, or one the user types)
    // has no data-auto flag and IS sent.
    function dueInput(current, tier) {
        var input = document.createElement("input");
        input.type = "date";
        input.dataset.field = "due_date";
        var H = window.inboxCategorizeHelpers;
        var resolved = H
            ? H.resolveDueForTier(current, tier, _todayIso())
            : { value: current || "", auto: false };
        if (resolved.value) { input.value = resolved.value; }
        if (resolved.auto) { input.dataset.auto = "1"; }
        // A manual edit turns the value into the user's explicit intent
        // — drop the auto flag so readRow sends it verbatim.
        input.addEventListener("input", function () {
            delete input.dataset.auto;
        });
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
        // Server treats "" as no-change; null clears. Client policy:
        // empty selects mean "leave null on the server".
        payload.project_id = project || null;
        payload.goal_id = goal || null;
        // #208 (2026-05-22): only send due_date when it's a real,
        // explicit value. An empty field OR an auto-derived placeholder
        // is OMITTED so the server's tier→date auto-fill
        // (_auto_fill_tier_due_date) runs and stamps the authoritative
        // date. Sending `due_date: null` would suppress that auto-fill
        // — the original bug: every auto-categorized Today task landed
        // with no due date.
        var dueEl = tr.querySelector('input[data-field="due_date"]');
        var dueVal = dueEl ? dueEl.value : "";
        var dueAuto = dueEl ? dueEl.dataset.auto === "1" : false;
        var H = window.inboxCategorizeHelpers;
        var sendDue = H
            ? H.shouldSendDue(dueVal, dueAuto)
            : (Boolean(dueVal) && !dueAuto);
        if (sendDue) { payload.due_date = dueVal; }
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
