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

        // #429: one paid categorize call at a time.
        openBtn.addEventListener("click", function () {
            window.withInflight(openBtn, openModal);
        });
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
        // #427: the task's own values — Apply sends only what differs.
        tr._current = {
            type: s.current_type,
            project_id: s.current_project_id || null,
            goal_id: s.current_goal_id || null,
            project_name: s.current_project_name,
            goal_title: s.current_goal_title,
        };
        // The 4th td() arg is the mobile stacked-layout label (becomes
        // data-label → rendered by the CSS ::before). The title + apply
        // cells get none — the title is self-evident, the apply button
        // needs no label. #209: this replaced `content: attr(class)`,
        // which dumped raw class names ("AUTO-CATEGORIZE-TIER") and,
        // worse, rendered a stray label over the title cell.
        tr.appendChild(td(textNode(s.title), "auto-categorize-title", s.reason));
        tr.appendChild(td(tierSelect(s.suggested_tier), "auto-categorize-tier", null, "Section"));
        tr.appendChild(td(projectSelect(s.suggested_project_id, s.suggested_type, _currentOption(s.current_project_id, s.current_project_name)), "auto-categorize-project", null, "Project"));
        tr.appendChild(td(goalSelect(s.suggested_goal_id, s.suggested_type, _currentOption(s.current_goal_id, s.current_goal_title)), "auto-categorize-goal", null, "Goal"));
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
                // #475: a task can only sit on a project of its own type, so
                // a project of the other type drops, with its goal (#427: a
                // goal set by hand stays). The server unlinks it on Apply too.
                var FH = window.filterHelpers;
                var droppedProject = "";
                var dropGoal = false;
                if (projCell) {
                    var prevProjVal = projCell.querySelector("select").value;
                    if (FH && FH.projectAfterTypeChange(prevProjVal, newType, availableProjects) !== prevProjVal) {
                        droppedProject = prevProjVal;
                        prevProjVal = "";
                    }
                    projCell.innerHTML = "";
                    projCell.appendChild(projectSelect(prevProjVal, newType, _currentOptionFor(tr, "project")));
                    _wireProjectCascade(tr);
                }
                if (goalCell) {
                    var prevGoalVal = goalCell.querySelector("select").value;
                    if (droppedProject && FH) {
                        dropGoal = !FH.goalAfterProjectChange(
                            droppedProject, "", prevGoalVal, availableProjects, null,
                        );
                    }
                    if (dropGoal) { prevGoalVal = ""; }
                    goalCell.innerHTML = "";
                    goalCell.appendChild(goalSelect(prevGoalVal, newType, _currentOptionFor(tr, "goal")));
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
        // #263 (2026-05-29): symmetric reverse direction — when the user
        // types/picks a date, re-route the section dropdown to the tier
        // that naturally matches that date (today / tomorrow / Mon-Sat
        // boundaries / beyond → backlog). Mirrors the detail-panel
        // bidirectional sync from #149 (same `window.tierHelpers`).
        //
        // Without this, the user could pick a date 3 days from now (e.g.
        // 2026-06-01) but the section stayed at whatever Claude
        // originally suggested (e.g. Tomorrow). At Apply time both
        // fields are PATCHed and the server's "explicit tier wins on
        // tie" rule (docs.html:758) landed the task in the stale
        // section — user-reported 2026-05-29 with screenshot showing
        // a task in Tomorrow with due_date 2026-06-01.
        //
        // FREEZER is preserved (matching the detail-panel rule) — if
        // the user has explicitly parked the task in Freezer the date
        // is just a reminder and shouldn't move the section.
        var dueEl = tr.querySelector('input[data-field="due_date"]');
        if (dueEl) {
            dueEl.addEventListener("change", function () {
                var TH = window.tierHelpers;
                if (!TH || typeof TH.tierForDueDate !== "function") { return; }
                if (!tierSel || tierSel.value === "freezer") { return; }
                var iso = dueEl.value;
                if (!iso) { return; }
                var naturalTier = TH.tierForDueDate(iso);
                if (!naturalTier) { return; }
                if (tierSel.value !== naturalTier) {
                    tierSel.value = naturalTier;
                    // Clear data-auto so resolveDueForTier doesn't
                    // overwrite the user's explicit date on a
                    // subsequent tier-driven re-derive.
                    delete dueEl.dataset.auto;
                }
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
        projSel.dataset.prev = projSel.value;
        projSel.addEventListener("change", function () {
            // The goal select may have been rebuilt by a Type change.
            var goalNow = tr.querySelector('select[data-field="goal"]');
            var allowed = new Set(
                Array.from(goalNow.options).map(function (o) { return o.value; })
            );
            // #427: same rule as the task panel — the old project's goal
            // goes with it, a goal set by hand stays.
            var newGoalId = window.filterHelpers.goalAfterProjectChange(
                projSel.dataset.prev, projSel.value, goalNow.value,
                availableProjects, allowed
            );
            projSel.dataset.prev = projSel.value;
            goalNow.value = newGoalId || "";
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

    // #427: a [id, label] option for the task's own project/goal, so the
    // select can show it even when the type filter or an archive hides it
    // (it rendered blank, and Apply sent null).
    function _currentOption(id, label) {
        return id ? [id, label || "(current)"] : null;
    }

    function _currentOptionFor(tr, field) {
        var c = tr._current || {};
        return field === "project"
            ? _currentOption(c.project_id, c.project_name)
            : _currentOption(c.goal_id, c.goal_title);
    }

    function _withCurrent(options, extra) {
        if (extra && !options.some(function (o) { return o[0] === extra[0]; })) {
            options.push(extra);
        }
        return options;
    }

    function projectSelect(current, type, extra) {
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
        return makeSelect(_withCurrent(options, extra), current || "", "project");
    }

    function goalSelect(current, type, extra) {
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
        return makeSelect(_withCurrent(options, extra), current || "", "goal");
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
            return el ? el.value : "";
        };
        // #208: due_date is sent only when it's a real, explicit value
        // (an auto placeholder is omitted so the server's tier→date
        // auto-fill runs). #427: type / project / goal only when they
        // differ from the task's own values. Both rules live in
        // inbox_categorize_helpers.categorizeApplyPayload (Jest-tested).
        var dueEl = tr.querySelector('input[data-field="due_date"]');
        return window.inboxCategorizeHelpers.categorizeApplyPayload({
            tier: get("tier"),
            type: get("type"),
            project: get("project"),
            goal: get("goal"),
            due: dueEl ? dueEl.value : "",
            dueAuto: dueEl ? dueEl.dataset.auto === "1" : false,
        }, tr._current);
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
