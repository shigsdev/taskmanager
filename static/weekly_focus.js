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
    var panel, slotsContainer, weekLabel, fallbackLabel, planAllBtn;
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
    // 0 = current week, 1 = next week: the tab last asked for.
    var currentWeekOffset = 0;
    // #441: the week whose slots are on screen. Saves, clears and ✨ Plan
    // use it, so an edit made while the other tab loads stays in its week.
    var shownWeekOffset = 0;
    // #441: bumped each time a week's slots are drawn from a load. A save
    // answer only updates the screen if it is still the same drawing.
    var viewSeq = 0;
    var drawnSeq = -1;     // the viewSeq the slots in the DOM belong to
    // #441: only the last tab asked for may draw.
    var loadGuard = window.requestGuardHelpers.createRequestGuard();
    var H = window.weeklyFocusHelpers;
    // Goals for the optional Goal-link picker. Loaded once on init,
    // independent of app.js's allGoals (which loads async + may not be
    // ready when the panel first renders).
    var goalsForPicker = [];

    // Pending changes from the last ✨ Plan call. Rendered into the
    // modal; checked rows get applied on click of Apply.
    var pendingChanges = [];
    // #418: the dialog is shared by every plan, so each answer must still
    // own it when it lands. begin() on open, cancel() on close.
    var planGuard = window.requestGuardHelpers.createRequestGuard();

    document.addEventListener("DOMContentLoaded", function () {
        panel = document.getElementById("weeklyFocusPanel");
        if (!panel) return;  // not on the home page
        slotsContainer = document.getElementById("weeklyFocusSlots");
        weekLabel = document.getElementById("weeklyFocusWeek");
        fallbackLabel = document.getElementById("weeklyFocusFallback");

        // Whole-week planner button (considers ALL focus statements).
        planAllBtn = document.getElementById("weeklyFocusPlanAll");
        if (planAllBtn) {
            // #429: one paid planner call at a time per button.
            planAllBtn.addEventListener("click", function () {
                window.withInflight(planAllBtn, openPlanAllModal);
            });
        }

        // #157 — tab pill click handlers (added to the template).
        var thisWeekTab = document.getElementById("weeklyFocusTabThis");
        var nextWeekTab = document.getElementById("weeklyFocusTabNext");
        if (thisWeekTab) {
            thisWeekTab.addEventListener("click", function () { _showWeek(0); });
        }
        if (nextWeekTab) {
            nextWeekTab.addEventListener("click", function () { _showWeek(1); });
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
            // the picker options surface. #440: only once the focus itself
            // has loaded — the default state drew 3 empty, editable slots,
            // and typing in one replaced text that was never shown.
            if (focusLoaded) render();
        }).catch(function () { /* leave empty list */ });

        loadFocus();
    });

    // ---- Read ----

    // #440: whether the slots on screen are the loaded week's. While
    // they aren't, there are no slots to type into — only a Retry.
    var focusLoaded = false;

    // A tab click. Until the asked-for week answers, the slots on screen
    // stay the shown week's and still save there (#441).
    function _showWeek(offset) {
        if (offset === currentWeekOffset) return;
        currentWeekOffset = offset;
        if (focusLoaded && offset === shownWeekOffset) {
            // Back to the week already drawn: drop the other tab's load.
            loadGuard.cancel();
            _refreshTabActive(offset);
            return;
        }
        loadFocus();
    }

    async function loadFocus() {
        var mine = loadGuard.begin();
        var offset = currentWeekOffset;
        try {
            var data = await window.apiFetch(
                "/api/weekly-focus?week_offset=" + offset,
            );
            if (!loadGuard.isCurrent(mine)) return;  // #441: a newer tab owns it
            state = data;
            shownWeekOffset = offset;
            viewSeq += 1;
            focusLoaded = true;
            render();
        } catch (err) {
            if (!loadGuard.isCurrent(mine)) return;
            console.error("weekly-focus load failed:", err);
            // #440: replace the slots (an earlier week's, or none) so
            // nothing can be typed into the wrong week.
            focusLoaded = false;
            _refreshTabActive(offset);
            if (planAllBtn) planAllBtn.disabled = true;
            if (window.loadErrorHelpers) {
                window.loadErrorHelpers.showLoadError(
                    slotsContainer,
                    offset ? "next week's focus" : "this week's focus",
                    err, loadFocus);
            }
        }
    }

    // #441: the highlighted tab is the week drawn (or the one that failed).
    function _refreshTabActive(offset) {
        var thisTab = document.getElementById("weeklyFocusTabThis");
        var nextTab = document.getElementById("weeklyFocusTabNext");
        // #458: aria-selected says the same to a screen reader.
        if (thisTab) {
            thisTab.classList.toggle("active", offset === 0);
            thisTab.setAttribute("aria-selected", offset === 0 ? "true" : "false");
        }
        if (nextTab) {
            nextTab.classList.toggle("active", offset === 1);
            nextTab.setAttribute("aria-selected", offset === 1 ? "true" : "false");
        }
    }

    function render() {
        _refreshTabActive(shownWeekOffset);
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

        // #441: a save's answer updates the slots in place, so typing in
        // another slot (and its focus) survives. A newly loaded week, or a
        // changed slot count, draws them afresh.
        var existing = slotsContainer.querySelectorAll(".weekly-focus-slot");
        if (drawnSeq === viewSeq && existing.length === state.slot_count) {
            for (var k = 0; k < existing.length; k++) {
                var n = Number(existing[k].dataset.slot);
                updateSlot(existing[k], bySlot[n] || null);
            }
        } else {
            slotsContainer.innerHTML = "";
            for (var s = 1; s <= state.slot_count; s++) {
                slotsContainer.appendChild(renderSlot(s, bySlot[s] || null));
            }
            drawnSeq = viewSeq;
        }

        // "Plan week" is only actionable when at least one slot has text.
        if (planAllBtn) {
            var hasAnyFocus = (state.slots || []).some(function (row) {
                return row && row.text && row.text.trim();
            });
            planAllBtn.disabled = !hasAnyFocus;
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
        input.setAttribute("aria-label", "Focus " + slotOrder);   // #458
        input.value = row ? row.text : "";
        input.dataset.synced = input.value;   // #441
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
        goalSelect.setAttribute("aria-label", "Goal for focus " + slotOrder);   // #458
        _fillGoalSelect(goalSelect, row);
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
        // #429: one paid call at a time for this slot; another slot's
        // ✨ Plan still works meanwhile (#418 keeps only its answer).
        planBtn.addEventListener("click", function () {
            window.withInflight(planBtn, function () {
                return openPlanModal(slotOrder, input.value);
            });
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
            // #441: empty the box now, so if this slot is still saving the
            // clear is sent right after (saveSlot reads the box then).
            input.value = "";
            planBtn.disabled = true;
            saveSlot(slotOrder, "", _goalSelectValue(wrap));
        });
        wrap.appendChild(clearBtn);

        return wrap;
    }

    // #441: bring a drawn slot up to date with the server's answer without
    // replacing it. What the user is typing, or changed and hasn't saved
    // yet, stays (slotInputValue); so does a picker they have open.
    function updateSlot(wrap, row) {
        var input = wrap.querySelector(".weekly-focus-slot-input");
        var serverText = row ? row.text : "";
        input.value = H.slotInputValue({
            value: input.value,
            synced: input.dataset.synced,
            serverText: serverText,
            focused: document.activeElement === input,
        });
        if (input.value === serverText) input.dataset.synced = serverText;
        var goalSelect = wrap.querySelector(".weekly-focus-slot-goal");
        if (document.activeElement !== goalSelect) _fillGoalSelect(goalSelect, row);
        wrap.querySelector(".weekly-focus-slot-plan").disabled = !input.value.trim();
        wrap.querySelector(".weekly-focus-slot-clear").disabled = !row;
    }

    function _fillGoalSelect(goalSelect, row) {
        goalSelect.replaceChildren();
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
    }

    function _slotWrap(slotOrder) {
        return slotsContainer.querySelector(
            '.weekly-focus-slot[data-slot="' + slotOrder + '"]');
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

    // "<week>:<slot>" → true while that slot's write is in flight, and
    // → true in _saveAgain when it changed again meanwhile (#441).
    var _saveInflight = {};
    var _saveAgain = {};

    function _savedRow(slotOrder) {
        return state.slots.find(function (s) { return s.slot_order === slotOrder; }) || null;
    }

    // Blur / goal pick / ✕: send what changed (PATCH), clear an emptied
    // slot (DELETE), or nothing at all (#441: a plain blur used to PATCH).
    function saveSlot(slotOrder, text, goalId) {
        var key = shownWeekOffset + ":" + slotOrder;
        if (_saveInflight[key]) {
            // #441: it used to be dropped. Sent once the first one answers.
            _saveAgain[key] = true;
            return;
        }
        text = (text || "").trim();
        var need = H.slotNeedsSave(_savedRow(slotOrder), text, goalId);
        if (need === "none") return;
        return _writeSlot(slotOrder, need === "clear"
            ? { method: "DELETE" }
            : { method: "PATCH", body: JSON.stringify({ text: text, goal_id: goalId }) });
    }

    async function _writeSlot(slotOrder, opts) {
        // #441: the week the user edited, not the tab clicked since; and
        // its answer only draws if those slots are still the ones showing.
        var offset = shownWeekOffset;
        var seq = viewSeq;
        var key = offset + ":" + slotOrder;
        var wrap = _slotWrap(slotOrder);
        var input = wrap ? wrap.querySelector(".weekly-focus-slot-input") : null;
        if (input) input.dataset.synced = input.value;
        _saveInflight[key] = true;
        try {
            // Both answers carry the week's display payload.
            var fresh = await window.apiFetch(
                "/api/weekly-focus/" + slotOrder + "?week_offset=" + offset, opts);
            if (seq === viewSeq) {
                state = fresh;
                render();
            }
        } catch (err) {
            console.error("weekly-focus save failed:", err);
            if (input && seq === viewSeq) {
                // Not saved: the box keeps the edit as unsaved, so the next
                // blur tries again. An emptied (✕) box shows what's saved.
                var saved = _savedRow(slotOrder);
                input.dataset.synced = saved ? saved.text : "";
                if (opts.method === "DELETE" && !input.value) {
                    input.value = input.dataset.synced;
                    render();
                }
            }
            if (opts.method === "PATCH") alert("Save failed: " + (err.message || err));
        } finally {
            _saveInflight[key] = false;
            if (_saveAgain[key]) {
                _saveAgain[key] = false;
                var again = seq === viewSeq ? _slotWrap(slotOrder) : null;
                var box = again ? again.querySelector(".weekly-focus-slot-input") : null;
                // Still typing there: its own blur will save.
                if (box && document.activeElement !== box) {
                    saveSlot(slotOrder, box.value, _goalSelectValue(again));
                }
            }
        }
    }

    // ---- ✨ Plan modal ----

    function openPlanModal(slotOrder, focusText) {
        // #429: returned so the ✨ Plan button stays guarded until it answers.
        return _runPlan(
            "/api/weekly-focus/" + slotOrder + "/plan"
            + "?week_offset=" + shownWeekOffset,
            focusText
        );
    }

    // Whole-week planner — considers ALL focus statements in one pass.
    function openPlanAllModal() {
        var texts = (state.slots || [])
            .filter(function (r) { return r && r.text && r.text.trim(); })
            .map(function (r) { return r.text.trim(); });
        if (texts.length === 0) return;
        var when = shownWeekOffset === 1 ? "next week" : "this week";
        var label = texts.length === 1
            ? texts[0]
            : (texts.length + " focus statements " + when);
        return _runPlan(
            "/api/weekly-focus/plan-all?week_offset=" + shownWeekOffset,
            label
        );
    }

    // Shared runner for the per-slot and whole-week planners: opens the
    // modal, POSTs to `url`, renders the returned changes for review.
    async function _runPlan(url, focusLabel) {
        var mine = planGuard.begin();
        modal.style.display = "";
        modalFocus.textContent = focusLabel;
        modalLoading.style.display = "";
        modalError.style.display = "none";
        modalEmpty.style.display = "none";
        modalChanges.replaceChildren();
        modalApply.style.display = "none";
        modalApply.disabled = false;   // an older apply may still be running
        pendingChanges = [];
        try {
            var result = await window.apiFetch(
                url, { method: "POST", body: JSON.stringify({}) }
            );
            if (!planGuard.isCurrent(mine)) return;  // closed or replaced
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
            if (!planGuard.isCurrent(mine)) return;
            modalLoading.style.display = "none";
            modalError.style.display = "";
            modalError.textContent =
                "Couldn't reach the planner: " + (err.message || err);
        }
    }

    function closeModal() {
        planGuard.cancel();
        modal.style.display = "none";
        modalChanges.innerHTML = "";
        pendingChanges = [];
    }

    var _ACTION_GROUPS = [
        { key: "promote_today",     label: "Promote to Today" },
        { key: "promote_this_week", label: "Promote to This Week" },
        { key: "promote_next_week", label: "Promote to Next Week" },
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

        if (change._failed) li.classList.add("weekly-focus-plan-row-failed");

        // #422: a re-render after a partial failure keeps the user's ticks.
        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = change._applied !== false;
        cb.className = "weekly-focus-plan-check";
        cb.setAttribute("aria-label", "Apply: " + change.title);   // #458
        cb.addEventListener("change", function () {
            change._applied = cb.checked;
        });
        change._applied = cb.checked;
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
        // #418: work on the list the user approved. Closing mid-apply
        // doesn't stop it part-way, and a newer plan's rows are never read.
        var mine = planGuard.begin();
        var approved = pendingChanges.filter(function (c) { return c._applied !== false; });
        modalApply.disabled = true;
        modalApply.textContent = "Applying…";
        var failed = 0;
        for (var i = 0; i < approved.length; i++) {
            var c = approved[i];
            c._failed = false;
            try {
                if (c.action === "promote_today") {
                    await _patchTask(c.task_id, { tier: "today" });
                } else if (c.action === "promote_this_week") {
                    await _patchTask(c.task_id, { tier: "this_week" });
                } else if (c.action === "promote_next_week") {
                    await _patchTask(c.task_id, { tier: "next_week" });
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
                c._landed = true;
            } catch (e) {
                c._failed = true;
                failed += 1;
                console.error("apply failed for", c, e);
            }
        }
        if (typeof window.loadTasks === "function") window.loadTasks();
        // Closed or replaced meanwhile: the dialog isn't ours to touch.
        if (!planGuard.isCurrent(mine)) return;
        modalApply.disabled = false;
        if (failed === 0) {
            closeModal();
        } else {
            // #422: what landed leaves the list, so a retry sends only the
            // failures (a create_new must not be created twice).
            pendingChanges = pendingChanges.filter(function (c) { return !c._landed; });
            renderPlanChanges();
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
