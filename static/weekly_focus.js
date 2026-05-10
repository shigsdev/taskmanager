/**
 * Weekly Focus panel (Feature 1, 2026-05-09).
 *
 * Hydrates the #weeklyFocusPanel on /:
 *   - GET /api/weekly-focus → render N slots (text input + optional
 *     goal picker + ✨ Plan button + ✕ clear button)
 *   - PATCH /api/weekly-focus/<slot> on blur (or Enter) when text changed
 *   - DELETE /api/weekly-focus/<slot> on ✕ click
 *   - POST /api/weekly-focus/<slot>/plan → opens the review modal
 *
 * Apply on the modal routes back through the canonical task surface
 * (PATCH /api/tasks/<id> for promote/demote, POST /api/tasks for
 * create_new) so the existing cascade rules (auto-promote on due
 * today, etc.) keep firing.
 */
(function () {
    "use strict";

    // ---- DOM refs (resolved on DOMContentLoaded) ----
    var panel, slotsContainer, weekLabel, fallbackLabel;
    var modal, modalFocus, modalLoading, modalError, modalEmpty;
    var modalChanges, modalApply, modalCancel, modalClose;

    // Server state from the most-recent GET. Drives render + apply.
    var state = {
        slot_count: 3,
        week_start_date: null,
        week_offset: 0,
        fallback_from: null,
        slots: [],          // [{slot_order, text, goal_id, goal_title}]
    };
    // #157 (2026-05-09): tab toggle "This Week" | "Next Week".
    // 0 = current week, 1 = next week. Drives the GET/PATCH/DELETE
    // query param on every API call.
    var currentWeekOffset = 0;
    // Goals for the optional Goal-link picker. Loaded once on init,
    // independent of app.js's allGoals (which loads async + may not be
    // ready when the panel first renders).
    var goalsForPicker = [];

    // Pending changes from the last ✨ Plan call. Rendered into the
    // modal; checked rows get applied on click of Apply.
    var pendingChanges = [];

    document.addEventListener("DOMContentLoaded", function () {
        panel = document.getElementById("weeklyFocusPanel");
        if (!panel) return;  // not on the home page
        slotsContainer = document.getElementById("weeklyFocusSlots");
        weekLabel = document.getElementById("weeklyFocusWeek");
        fallbackLabel = document.getElementById("weeklyFocusFallback");

        // #157 — tab pill click handlers (added to the template).
        var thisWeekTab = document.getElementById("weeklyFocusTabThis");
        var nextWeekTab = document.getElementById("weeklyFocusTabNext");
        if (thisWeekTab) {
            thisWeekTab.addEventListener("click", function () {
                if (currentWeekOffset !== 0) {
                    currentWeekOffset = 0;
                    loadFocus();
                }
            });
        }
        if (nextWeekTab) {
            nextWeekTab.addEventListener("click", function () {
                if (currentWeekOffset !== 1) {
                    currentWeekOffset = 1;
                    loadFocus();
                }
            });
        }

        modal = document.getElementById("weeklyFocusPlanModal");
        modalFocus = document.getElementById("weeklyFocusPlanFocus");
        modalLoading = document.getElementById("weeklyFocusPlanLoading");
        modalError = document.getElementById("weeklyFocusPlanError");
        modalEmpty = document.getElementById("weeklyFocusPlanEmpty");
        modalChanges = document.getElementById("weeklyFocusPlanChanges");
        modalApply = document.getElementById("weeklyFocusPlanApply");
        modalCancel = document.getElementById("weeklyFocusPlanCancel");
        modalClose = document.getElementById("weeklyFocusPlanClose");

        modalCancel.addEventListener("click", closeModal);
        modalClose.addEventListener("click", closeModal);
        var backdrop = modal.querySelector(".weekly-focus-plan-backdrop");
        if (backdrop) backdrop.addEventListener("click", closeModal);
        modalApply.addEventListener("click", applyPlan);

        // Fetch goals for the picker in parallel with the focus load.
        // Either resolution order works — render() pulls from goalsForPicker
        // when it runs.
        window.apiFetch("/api/goals").then(function (gs) {
            goalsForPicker = Array.isArray(gs) ? gs : [];
            // If we already rendered before goals arrived, re-render so
            // the picker options surface.
            if (state.slots !== undefined) render();
        }).catch(function () { /* leave empty list */ });

        loadFocus();
    });

    // ---- Read ----

    async function loadFocus() {
        try {
            var data = await window.apiFetch(
                "/api/weekly-focus?week_offset=" + currentWeekOffset,
            );
            state = data;
            render();
        } catch (err) {
            console.error("weekly-focus load failed:", err);
        }
    }

    function _refreshTabActive() {
        var thisTab = document.getElementById("weeklyFocusTabThis");
        var nextTab = document.getElementById("weeklyFocusTabNext");
        if (thisTab) {
            thisTab.classList.toggle("active", currentWeekOffset === 0);
        }
        if (nextTab) {
            nextTab.classList.toggle("active", currentWeekOffset === 1);
        }
    }

    function render() {
        _refreshTabActive();
        // Format the week header.
        if (state.week_start_date) {
            var ws = new Date(state.week_start_date + "T00:00:00");
            var we = new Date(ws);
            we.setDate(we.getDate() + 6);
            weekLabel.textContent =
                "(" + _shortDate(ws) + " – " + _shortDate(we) + ")";
        }
        // The carry-forward "fallback_from" hint only makes sense
        // for the current-week tab. Hide it on next-week regardless
        // (next-week starts blank by design — see service docstring).
        fallbackLabel.hidden = !state.fallback_from
            || (state.week_offset || 0) !== 0;

        // Build a slot_order → row lookup so empty slots render as
        // empty placeholders.
        var bySlot = {};
        for (var i = 0; i < state.slots.length; i++) {
            bySlot[state.slots[i].slot_order] = state.slots[i];
        }

        // Render N slots.
        slotsContainer.innerHTML = "";
        for (var s = 1; s <= state.slot_count; s++) {
            slotsContainer.appendChild(renderSlot(s, bySlot[s] || null));
        }
    }

    function renderSlot(slotOrder, row) {
        var wrap = document.createElement("div");
        wrap.className = "weekly-focus-slot";
        wrap.dataset.slot = String(slotOrder);

        var num = document.createElement("span");
        num.className = "weekly-focus-slot-num";
        num.textContent = String(slotOrder) + ".";
        wrap.appendChild(num);

        var input = document.createElement("input");
        input.type = "text";
        input.className = "weekly-focus-slot-input";
        input.maxLength = 200;
        input.placeholder = "e.g. Ship the auth refresh";
        input.value = row ? row.text : "";
        input.addEventListener("blur", function () {
            saveSlot(slotOrder, input.value, _goalSelectValue(wrap));
        });
        input.addEventListener("keydown", function (e) {
            if (e.key === "Enter") {
                e.preventDefault();
                input.blur();
            }
        });
        wrap.appendChild(input);

        // Goal picker — populated from window.allGoals if app.js has
        // already loaded it. Otherwise we fetch /api/goals lazily.
        var goalSelect = document.createElement("select");
        goalSelect.className = "weekly-focus-slot-goal";
        goalSelect.title = "Optionally link this focus to a Goal";
        var blank = document.createElement("option");
        blank.value = "";
        blank.textContent = "— No goal link —";
        goalSelect.appendChild(blank);
        // Prefer the panel-local goal list (loaded on init); fall back
        // to app.js's window.allGoals if it happens to be populated.
        var goals = goalsForPicker.length
            ? goalsForPicker
            : ((typeof window.allGoals !== "undefined" && window.allGoals) || []);
        for (var i = 0; i < goals.length; i++) {
            var opt = document.createElement("option");
            opt.value = goals[i].id;
            opt.textContent = goals[i].title;
            if (row && row.goal_id === goals[i].id) opt.selected = true;
            goalSelect.appendChild(opt);
        }
        // If allGoals isn't loaded yet AND the row has a goal_id we
        // don't recognize, surface a stub option so the picker shows
        // its current goal title.
        if (row && row.goal_id && !goals.some(function (g) { return g.id === row.goal_id; })) {
            var stub = document.createElement("option");
            stub.value = row.goal_id;
            stub.textContent = row.goal_title || "(linked goal)";
            stub.selected = true;
            goalSelect.appendChild(stub);
        }
        goalSelect.addEventListener("change", function () {
            // Goal change saves immediately (no blur needed — select
            // dispatches change on user pick).
            saveSlot(slotOrder, input.value, goalSelect.value || null);
        });
        wrap.appendChild(goalSelect);

        // ✨ Plan button — only enabled when text is non-empty.
        var planBtn = document.createElement("button");
        planBtn.type = "button";
        planBtn.className = "btn-sm weekly-focus-slot-plan";
        planBtn.textContent = "✨ Plan";
        planBtn.title = "Use AI to propose task changes for this focus";
        planBtn.disabled = !(row && row.text && row.text.trim());
        planBtn.addEventListener("click", function () {
            openPlanModal(slotOrder, input.value);
        });
        // Re-enable / disable on text edits so the button reflects
        // current state without needing to save first.
        input.addEventListener("input", function () {
            planBtn.disabled = !input.value.trim();
        });
        wrap.appendChild(planBtn);

        // ✕ Clear button — only shown if the slot has content.
        var clearBtn = document.createElement("button");
        clearBtn.type = "button";
        clearBtn.className = "btn-sm weekly-focus-slot-clear";
        clearBtn.textContent = "✕";
        clearBtn.title = "Clear this slot";
        clearBtn.disabled = !row;
        clearBtn.addEventListener("click", function () {
            clearSlot(slotOrder);
        });
        wrap.appendChild(clearBtn);

        return wrap;
    }

    function _goalSelectValue(wrap) {
        var sel = wrap.querySelector(".weekly-focus-slot-goal");
        return sel && sel.value ? sel.value : null;
    }

    function _shortDate(d) {
        // Format like "May 11"
        return d.toLocaleDateString(undefined, {
            month: "short", day: "numeric",
        });
    }

    // ---- Write ----

    var _saveInflight = {};   // slotOrder → bool (debounce duplicate saves)

    async function saveSlot(slotOrder, text, goalId) {
        text = (text || "").trim();
        if (!text) {
            // Empty text → if the slot had content, clear it.
            // Otherwise no-op (don't fire a delete on a never-touched slot).
            var existing = state.slots.find(function (s) { return s.slot_order === slotOrder; });
            if (existing) {
                await clearSlot(slotOrder);
            }
            return;
        }
        if (_saveInflight[slotOrder]) return;
        _saveInflight[slotOrder] = true;
        try {
            var fresh = await window.apiFetch(
                "/api/weekly-focus/" + slotOrder
                + "?week_offset=" + currentWeekOffset,
                {
                    method: "PATCH",
                    body: JSON.stringify({ text: text, goal_id: goalId }),
                }
            );
            state = fresh;
            render();
        } catch (err) {
            console.error("weekly-focus save failed:", err);
            alert("Save failed: " + (err.message || err));
        } finally {
            _saveInflight[slotOrder] = false;
        }
    }

    async function clearSlot(slotOrder) {
        try {
            var fresh = await window.apiFetch(
                "/api/weekly-focus/" + slotOrder
                + "?week_offset=" + currentWeekOffset,
                { method: "DELETE" }
            );
            // DELETE response includes the same display payload.
            state = fresh;
            render();
        } catch (err) {
            console.error("weekly-focus clear failed:", err);
        }
    }

    // ---- ✨ Plan modal ----

    async function openPlanModal(slotOrder, focusText) {
        modal.style.display = "";
        modalFocus.textContent = focusText;
        modalLoading.style.display = "";
        modalError.style.display = "none";
        modalEmpty.style.display = "none";
        modalChanges.innerHTML = "";
        modalApply.style.display = "none";
        pendingChanges = [];
        try {
            var result = await window.apiFetch(
                "/api/weekly-focus/" + slotOrder + "/plan"
                + "?week_offset=" + currentWeekOffset,
                { method: "POST", body: JSON.stringify({}) }
            );
            modalLoading.style.display = "none";
            pendingChanges = result.changes || [];
            if (pendingChanges.length === 0) {
                modalEmpty.style.display = "";
                return;
            }
            renderPlanChanges();
            modalApply.style.display = "";
            modalApply.textContent = "Apply (" + pendingChanges.length + ")";
        } catch (err) {
            modalLoading.style.display = "none";
            modalError.style.display = "";
            modalError.textContent =
                "Couldn't reach the planner: " + (err.message || err);
        }
    }

    function closeModal() {
        modal.style.display = "none";
        modalChanges.innerHTML = "";
        pendingChanges = [];
    }

    var _ACTION_GROUPS = [
        { key: "promote_today",     label: "Promote to Today" },
        { key: "promote_this_week", label: "Promote to This Week" },
        { key: "create_new",        label: "New task suggestions" },
        { key: "demote_backlog",    label: "Demote to Backlog" },
    ];

    function renderPlanChanges() {
        modalChanges.innerHTML = "";
        for (var i = 0; i < _ACTION_GROUPS.length; i++) {
            var grp = _ACTION_GROUPS[i];
            var rows = pendingChanges.filter(function (c) { return c.action === grp.key; });
            if (rows.length === 0) continue;
            var section = document.createElement("section");
            section.className = "weekly-focus-plan-group";
            var h = document.createElement("h4");
            h.textContent = grp.label + " (" + rows.length + ")";
            section.appendChild(h);
            for (var j = 0; j < rows.length; j++) {
                section.appendChild(renderPlanRow(rows[j]));
            }
            modalChanges.appendChild(section);
        }
    }

    function renderPlanRow(change) {
        var li = document.createElement("div");
        li.className = "weekly-focus-plan-row";
        li.dataset.action = change.action;

        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = true;
        cb.className = "weekly-focus-plan-check";
        cb.addEventListener("change", function () {
            change._applied = cb.checked;
        });
        change._applied = true;
        li.appendChild(cb);

        var titleSpan = document.createElement("span");
        titleSpan.className = "weekly-focus-plan-title";
        titleSpan.textContent = change.title;
        li.appendChild(titleSpan);

        if (change.reason) {
            var reasonSpan = document.createElement("span");
            reasonSpan.className = "weekly-focus-plan-reason";
            reasonSpan.textContent = change.reason;
            li.appendChild(reasonSpan);
        }

        if (change.action === "create_new") {
            var meta = document.createElement("span");
            meta.className = "weekly-focus-plan-meta";
            var bits = [change.suggested_tier, change.type];
            if (change.due_date) bits.push("due " + change.due_date);
            meta.textContent = "[" + bits.join(", ") + "]";
            li.appendChild(meta);
        }
        return li;
    }

    async function applyPlan() {
        modalApply.disabled = true;
        modalApply.textContent = "Applying…";
        var failed = 0;
        for (var i = 0; i < pendingChanges.length; i++) {
            var c = pendingChanges[i];
            if (c._applied === false) continue;
            try {
                if (c.action === "promote_today") {
                    await _patchTask(c.task_id, { tier: "today" });
                } else if (c.action === "promote_this_week") {
                    await _patchTask(c.task_id, { tier: "this_week" });
                } else if (c.action === "demote_backlog") {
                    await _patchTask(c.task_id, { tier: "backlog" });
                } else if (c.action === "create_new") {
                    await _createTask({
                        title: c.title,
                        type: c.type,
                        tier: c.suggested_tier,
                        due_date: c.due_date || undefined,
                    });
                }
            } catch (e) {
                failed += 1;
                console.error("apply failed for", c, e);
            }
        }
        modalApply.disabled = false;
        if (failed === 0) {
            closeModal();
            if (typeof window.loadTasks === "function") window.loadTasks();
        } else {
            modalApply.textContent = "Apply remaining (" + failed + " failed)";
        }
    }

    function _patchTask(id, body) {
        return window.apiFetch("/api/tasks/" + id, {
            method: "PATCH", body: JSON.stringify(body),
        });
    }
    function _createTask(body) {
        return window.apiFetch("/api/tasks", {
            method: "POST", body: JSON.stringify(body),
        });
    }
})();
