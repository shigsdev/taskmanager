/**
 * projects.js — Projects CRUD view.
 *
 * Mirrors the goals.js pattern:
 *  - Loads projects + tasks + goals via apiFetch (from app.js)
 *  - Renders project cards grouped by Work / Personal
 *  - Detail overlay for create / edit / archive / delete
 *
 * The archive semantics match the DELETE endpoint: archiving sets
 * is_active=false via PATCH (same effect, but keeps the row visible in
 * "archived" / "all" filter modes). True delete uses DELETE (also soft).
 */
"use strict";

const PROJECT_TYPE_LABELS = { work: "Work", personal: "Personal" };

// #90 (PR35): bulk-edit selection state.
let projectsBulkMode = false;
let projectsBulkSelected = new Set();  // Set<UUID>

// Fallback color when a project has none set — matches the theme blue.
const DEFAULT_PROJECT_COLOR = "#2563eb";

// #66 (2026-04-25): per-type default color (Work=blue, Personal=green).
// Mirrors backend project_service.DEFAULT_TYPE_COLORS so the form picker
// reflects what the API would assign if the user didn't touch the picker.
const DEFAULT_TYPE_COLORS = {
    work: "#2563eb",
    personal: "#16a34a",
};
function defaultColorForType(t) {
    return DEFAULT_TYPE_COLORS[t] || DEFAULT_PROJECT_COLOR;
}

let projectsData = [];
let projectsGoals = [];  // for the "Linked goal" dropdown
let projectTaskCounts = {};  // project_id -> { total, active }
// #95 (PR33): keep the per-project task arrays so we can render the
// inline-collapsible list AND the full list in the side panel without
// re-fetching.
let projectTasksById = {};  // project_id -> Task[] (active first)
const PROJECT_TASKS_INLINE_LIMIT = 5;  // collapse threshold

// --- Init --------------------------------------------------------------------

async function projectsInit() {
    await projectsLoad();
    projectsSetupFilters();
    projectsSetupDetailPanel();
    projectsSetupBulk();  // #90 (PR35)
}

async function projectsLoad() {
    // Load projects (is_active=all so archived ones show when filter is toggled).
    projectsData = await apiFetch("/api/projects?is_active=all");
    projectsGoals = await apiFetch("/api/goals?is_active=all");
    const tasks = await apiFetch("/api/tasks");

    // Compute task counts per project (total and active-only) AND keep
    // the task arrays so we can render them inline (#95).
    projectTaskCounts = {};
    projectTasksById = {};
    for (const t of tasks) {
        if (!t.project_id) continue;
        if (!projectTaskCounts[t.project_id]) {
            projectTaskCounts[t.project_id] = { total: 0, active: 0 };
            projectTasksById[t.project_id] = [];
        }
        projectTaskCounts[t.project_id].total += 1;
        if (t.status !== "archived") {
            projectTaskCounts[t.project_id].active += 1;
        }
        projectTasksById[t.project_id].push(t);
    }
    // Sort each project's task list: active first, then by title.
    for (const pid of Object.keys(projectTasksById)) {
        projectTasksById[pid].sort((a, b) => {
            const aActive = a.status !== "archived" ? 0 : 1;
            const bActive = b.status !== "archived" ? 0 : 1;
            if (aActive !== bActive) return aActive - bActive;
            return (a.title || "").localeCompare(b.title || "");
        });
    }

    // Inbox badge (same as other pages — share the widget from base.html).
    const inboxCount = tasks.filter((t) => t.tier === "inbox").length;
    const badge = document.getElementById("inboxBadge");
    if (badge) {
        badge.textContent = inboxCount;
        badge.classList.toggle("empty", inboxCount === 0);
    }

    projectsRender();
}

// --- Rendering ---------------------------------------------------------------

function projectsFiltered() {
    let list = projectsData.slice();

    const typeFilter = document.getElementById("projectFilterType").value;
    if (typeFilter) list = list.filter((p) => p.type === typeFilter);

    const activeFilter = document.getElementById("projectFilterActive").value;
    if (activeFilter === "active") list = list.filter((p) => p.is_active);
    else if (activeFilter === "archived") list = list.filter((p) => !p.is_active);
    // "all" — no filter

    // #96 (PR33): goal filter. Empty string = "All goals".
    const goalFilterEl = document.getElementById("projectFilterGoal");
    const goalFilterVal = goalFilterEl ? goalFilterEl.value : "";
    if (goalFilterVal) list = list.filter((p) => p.goal_id === goalFilterVal);

    // Sort: active first, then by priority_order, then by name.
    list.sort((a, b) => {
        if (a.is_active !== b.is_active) return a.is_active ? -1 : 1;
        if (a.priority_order !== b.priority_order) return a.priority_order - b.priority_order;
        return a.name.localeCompare(b.name);
    });

    return list;
}

function projectsRender() {
    const board = document.getElementById("projectsBoard");
    board.innerHTML = "";

    const filtered = projectsFiltered();
    // PR36 audit TD-3: drop selected ids that no longer match any
    // currently-visible card. Without this, archiving a project
    // (which removes it from the active filter) leaves a "ghost"
    // selection that subsequent bulk actions silently apply to the
    // hidden row. After re-render, only ids that are still on screen
    // can stay in the selection.
    if (projectsBulkMode && projectsBulkSelected.size) {
        const visible = new Set(filtered.map((p) => p.id));
        for (const id of Array.from(projectsBulkSelected)) {
            if (!visible.has(id)) projectsBulkSelected.delete(id);
        }
        updateBulkCount();
    }
    if (filtered.length === 0) {
        board.innerHTML = '<p class="empty-goals">No projects match the current filters.</p>';
        return;
    }

    // Group by type so Work / Personal are visually separated.
    for (const type of ["work", "personal"]) {
        const group = filtered.filter((p) => p.type === type);
        if (group.length === 0) continue;

        const section = document.createElement("div");
        section.className = "goals-category-section";

        const header = document.createElement("h2");
        header.className = "goals-category-header";
        header.textContent = PROJECT_TYPE_LABELS[type];
        header.innerHTML += ` <span class="tier-count">${group.length}</span>`;
        section.appendChild(header);

        // #62: drag-and-drop reorder within this type group. Each card
        // is a drop target; on drop, recompute the order and POST to
        // /api/projects/reorder. Only ACTIVE projects participate
        // (archived sit at the bottom and aren't draggable).
        const dropList = document.createElement("div");
        dropList.className = "project-drop-list";
        dropList.dataset.type = type;
        for (const project of group) {
            const card = projectCardEl(project);
            if (project.is_active) {
                card.draggable = true;
                card.dataset.id = project.id;
                card.addEventListener("dragstart", onCardDragStart);
                card.addEventListener("dragover", onCardDragOver);
                card.addEventListener("drop", onCardDrop);
                card.addEventListener("dragend", onCardDragEnd);
            }
            dropList.appendChild(card);
        }
        section.appendChild(dropList);
        board.appendChild(section);
    }
}

// --- Drag-and-drop reorder (#62) ---------------------------------------------

let _dragSrcId = null;

function onCardDragStart(e) {
    _dragSrcId = e.currentTarget.dataset.id;
    e.currentTarget.classList.add("dragging");
    if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", _dragSrcId);
    }
}

function onCardDragOver(e) {
    if (!_dragSrcId) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
    const target = e.currentTarget;
    const srcCard = document.querySelector(`.project-card.dragging`);
    if (!srcCard || srcCard === target) return;
    const list = target.parentElement;
    if (!list || list !== srcCard.parentElement) return;  // can't cross type groups
    // Insert before or after based on cursor position relative to midpoint.
    const rect = target.getBoundingClientRect();
    const before = e.clientY < rect.top + rect.height / 2;
    list.insertBefore(srcCard, before ? target : target.nextSibling);
}

async function onCardDrop(e) {
    e.preventDefault();
    const list = e.currentTarget.parentElement;
    if (!list) return;
    const ids = Array.from(list.querySelectorAll(".project-card[data-id]"))
        .map((el) => el.dataset.id);
    try {
        await fetch("/api/projects/reorder", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ordered_ids: ids }),
        });
        // Reload to pick up new priority_order values from the server.
        await projectsLoad();
        projectsRender();
    } catch (err) {
        console.error("Reorder failed:", err);
        alert("Reorder failed: " + err.message);
    }
}

function onCardDragEnd(e) {
    e.currentTarget.classList.remove("dragging");
    _dragSrcId = null;
}

function projectCardEl(project) {
    const card = document.createElement("div");
    card.className = "goal-card project-card";
    if (!project.is_active) card.classList.add("goal-inactive");
    // #90 (PR35): in bulk mode, click toggles selection (no detail panel).
    card.addEventListener("click", (e) => {
        if (projectsBulkMode) {
            e.stopPropagation();
            if (projectsBulkSelected.has(project.id)) projectsBulkSelected.delete(project.id);
            else projectsBulkSelected.add(project.id);
            card.classList.toggle("bulk-selected", projectsBulkSelected.has(project.id));
            const cb = card.querySelector(".project-bulk-cb");
            if (cb) cb.checked = projectsBulkSelected.has(project.id);
            updateBulkCount();
        } else {
            projectDetailOpen(project);
        }
    });
    if (projectsBulkMode) {
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.className = "project-bulk-cb";
        cb.checked = projectsBulkSelected.has(project.id);
        if (cb.checked) card.classList.add("bulk-selected");
        cb.addEventListener("click", (e) => e.stopPropagation());
        cb.addEventListener("change", () => {
            if (cb.checked) projectsBulkSelected.add(project.id);
            else projectsBulkSelected.delete(project.id);
            card.classList.toggle("bulk-selected", cb.checked);
            updateBulkCount();
        });
        card.appendChild(cb);
    }

    // Color swatch + name on the same row.
    const titleRow = document.createElement("div");
    titleRow.className = "project-title-row";

    const swatch = document.createElement("span");
    swatch.className = "project-color-dot";
    swatch.style.background = project.color || DEFAULT_PROJECT_COLOR;
    titleRow.appendChild(swatch);

    const title = document.createElement("span");
    title.className = "goal-title project-title";
    title.textContent = project.name;
    titleRow.appendChild(title);

    if (!project.is_active) {
        const archivedBadge = document.createElement("span");
        archivedBadge.className = "badge";
        archivedBadge.textContent = "Archived";
        titleRow.appendChild(archivedBadge);
    }

    card.appendChild(titleRow);

    // Priority badge (#62) — Must/Should/Could/NMI; null = no badge.
    if (project.priority) {
        const pBadge = document.createElement("span");
        pBadge.className = "badge badge-priority-" + project.priority;
        pBadge.textContent = project.priority.replace("_", " ");
        titleRow.appendChild(pBadge);
    }

    // Status badge (#69) — shown unless not_started (default; reduces noise).
    if (project.status && project.status !== "not_started") {
        const sBadge = document.createElement("span");
        sBadge.className = "badge";
        sBadge.textContent = project.status.replace("_", " ");
        titleRow.appendChild(sBadge);
    }

    // Target quarter (if set).
    if (project.target_quarter) {
        const tqBadge = document.createElement("span");
        tqBadge.className = "badge";
        tqBadge.textContent = project.target_quarter;
        titleRow.appendChild(tqBadge);
    }

    // Linked goal (if any).
    if (project.goal_id) {
        const goal = projectsGoals.find((g) => g.id === project.goal_id);
        if (goal) {
            const goalLine = document.createElement("div");
            goalLine.className = "goal-actions-preview";
            goalLine.textContent = "Goal: " + goal.title;
            card.appendChild(goalLine);
        }
    }

    // Task count.
    const counts = projectTaskCounts[project.id] || { total: 0, active: 0 };
    const countRow = document.createElement("div");
    countRow.className = "goal-progress-row";
    const countLabel = document.createElement("span");
    countLabel.className = "progress-label" + (counts.total === 0 ? " muted" : "");
    if (counts.total === 0) {
        countLabel.textContent = "No tasks linked";
    } else {
        countLabel.textContent = `${counts.active} active / ${counts.total} total`;
    }
    countRow.appendChild(countLabel);
    card.appendChild(countRow);

    // #95 (PR33): inline list of linked tasks, collapsed past N. Card
    // click still opens the side panel (the task <li> stops propagation
    // so clicking a task title doesn't also open the project panel).
    const tasks = projectTasksById[project.id] || [];
    if (tasks.length > 0) {
        const listWrap = document.createElement("div");
        listWrap.className = "project-card-tasks";
        const ul = document.createElement("ul");
        ul.className = "project-card-task-list";
        const initialShow = tasks.length <= PROJECT_TASKS_INLINE_LIMIT
            ? tasks.length
            : PROJECT_TASKS_INLINE_LIMIT;
        for (let i = 0; i < tasks.length; i++) {
            const t = tasks[i];
            const li = document.createElement("li");
            li.className = "project-card-task" + (t.status === "archived" ? " done" : "");
            if (i >= initialShow) li.style.display = "none";
            li.textContent = t.title;
            li.title = t.title;
            li.addEventListener("click", (e) => e.stopPropagation());
            ul.appendChild(li);
        }
        listWrap.appendChild(ul);
        if (tasks.length > PROJECT_TASKS_INLINE_LIMIT) {
            const toggle = document.createElement("button");
            toggle.type = "button";
            toggle.className = "btn-sm project-card-toggle";
            const hidden = tasks.length - initialShow;
            toggle.textContent = `Show all (${tasks.length})`;
            let expanded = false;
            toggle.addEventListener("click", (e) => {
                e.stopPropagation();
                expanded = !expanded;
                Array.from(ul.children).forEach((li, idx) => {
                    li.style.display = (expanded || idx < initialShow) ? "" : "none";
                });
                toggle.textContent = expanded ? "Hide" : `Show all (${tasks.length})`;
            });
            listWrap.appendChild(toggle);
        }
        card.appendChild(listWrap);
    }

    return card;
}

// --- Filters -----------------------------------------------------------------

function projectsSetupFilters() {
    document
        .getElementById("projectFilterType")
        .addEventListener("change", projectsRender);
    document
        .getElementById("projectFilterActive")
        .addEventListener("change", projectsRender);
    // #96 (PR33): goal filter dropdown — populate from active goals,
    // re-render on change.
    const goalSel = document.getElementById("projectFilterGoal");
    if (goalSel) {
        for (const g of projectsGoals.filter((x) => x.is_active)) {
            const opt = document.createElement("option");
            opt.value = g.id;
            opt.textContent = g.title;
            goalSel.appendChild(opt);
        }
        goalSel.addEventListener("change", projectsRender);
    }
    document
        .getElementById("addProjectBtn")
        .addEventListener("click", projectDetailNew);
}

// --- Detail panel ------------------------------------------------------------

function projectsSetupDetailPanel() {
    document
        .getElementById("projectDetailClose")
        .addEventListener("click", projectDetailClose);
    document
        .getElementById("projectDetailOverlay")
        .addEventListener("click", (e) => {
            if (e.target === e.currentTarget) projectDetailClose();
        });
    document
        .getElementById("projectDetailForm")
        .addEventListener("submit", projectDetailSave);
    // #66: when type changes, snap the color picker to the per-type
    // default ONLY if the picker still holds a known default (i.e., the
    // user hasn't manually picked a custom color). Manual overrides win.
    document
        .getElementById("projectType")
        .addEventListener("change", (e) => {
            const colorInput = document.getElementById("projectColor");
            const isAtKnownDefault = Object.values(DEFAULT_TYPE_COLORS)
                .concat([DEFAULT_PROJECT_COLOR])
                .includes(colorInput.value.toLowerCase());
            if (isAtKnownDefault) {
                colorInput.value = defaultColorForType(e.target.value);
            }
        });
    document
        .getElementById("projectArchiveToggle")
        .addEventListener("click", projectDetailToggleArchive);
}

function populateGoalDropdown(selectedId) {
    const select = document.getElementById("projectGoalId");
    // Keep the "(no goal)" option as #1.
    select.innerHTML = '<option value="">(no goal)</option>';
    const activeGoals = projectsGoals.filter((g) => g.is_active);
    for (const goal of activeGoals) {
        const opt = document.createElement("option");
        opt.value = goal.id;
        opt.textContent = goal.title;
        if (selectedId && goal.id === selectedId) opt.selected = true;
        select.appendChild(opt);
    }
}

function projectDetailNew() {
    document.getElementById("projectId").value = "";
    document.getElementById("projectDetailHeading").textContent = "New Project";
    document.getElementById("projectName").value = "";
    document.getElementById("projectType").value = "work";
    document.getElementById("projectColor").value = defaultColorForType("work");
    document.getElementById("projectTargetQuarter").value = "";
    document.getElementById("projectPriorityOrder").value = "0";
    document.getElementById("projectActions").value = "";
    document.getElementById("projectNotes").value = "";
    document.getElementById("projectStatus").value = "not_started";
    document.getElementById("projectPriority").value = "";
    populateGoalDropdown(null);
    document.getElementById("projectTaskSummary").style.display = "none";
    // No archive on a project that doesn't exist yet.
    document.getElementById("projectArchiveToggle").style.display = "none";
    document.getElementById("projectDetailOverlay").style.display = "";
}

function projectDetailOpen(project) {
    document.getElementById("projectId").value = project.id;
    document.getElementById("projectDetailHeading").textContent = "Edit Project";
    document.getElementById("projectName").value = project.name;
    document.getElementById("projectType").value = project.type;
    document.getElementById("projectColor").value = project.color || DEFAULT_PROJECT_COLOR;
    document.getElementById("projectTargetQuarter").value = project.target_quarter || "";
    document.getElementById("projectPriorityOrder").value = String(project.priority_order || 0);
    document.getElementById("projectActions").value = project.actions || "";
    document.getElementById("projectNotes").value = project.notes || "";
    document.getElementById("projectStatus").value = project.status || "not_started";
    document.getElementById("projectPriority").value = project.priority || "";
    populateGoalDropdown(project.goal_id);

    // Task summary.
    const counts = projectTaskCounts[project.id] || { total: 0, active: 0 };
    const summary = document.getElementById("projectTaskSummary");
    document.getElementById("projectTaskCount").textContent = counts.total;
    document.getElementById("projectTaskPlural").textContent = counts.total === 1 ? "" : "s";
    summary.style.display = counts.total > 0 ? "" : "none";

    // #95 (PR33): full task list in the side panel — no collapse, since
    // the panel scrolls anyway and the user opened it specifically to
    // see project detail.
    const taskListWrap = document.getElementById("projectTaskListWrap");
    const taskList = document.getElementById("projectTaskList");
    const tasks = projectTasksById[project.id] || [];
    taskList.innerHTML = "";
    if (tasks.length > 0) {
        for (const t of tasks) {
            const li = document.createElement("li");
            li.className = "project-side-task" + (t.status === "archived" ? " done" : "");
            li.textContent = t.title;
            li.title = t.title;
            taskList.appendChild(li);
        }
        taskListWrap.style.display = "";
    } else {
        taskListWrap.style.display = "none";
    }

    // Archive toggle label flips based on current state.
    const archiveBtn = document.getElementById("projectArchiveToggle");
    archiveBtn.style.display = "";
    archiveBtn.textContent = project.is_active ? "Archive" : "Unarchive";

    document.getElementById("projectDetailOverlay").style.display = "";
}

function projectDetailClose() {
    document.getElementById("projectDetailOverlay").style.display = "none";
}

async function projectDetailSave(e) {
    e.preventDefault();
    const id = document.getElementById("projectId").value;
    const goalSel = document.getElementById("projectGoalId").value;
    const orderRaw = document.getElementById("projectPriorityOrder").value;
    const prioRaw = document.getElementById("projectPriority").value;
    const data = {
        name: document.getElementById("projectName").value.trim(),
        type: document.getElementById("projectType").value,
        color: document.getElementById("projectColor").value || null,
        target_quarter: document.getElementById("projectTargetQuarter").value.trim() || null,
        actions: document.getElementById("projectActions").value.trim() || null,
        notes: document.getElementById("projectNotes").value.trim() || null,
        status: document.getElementById("projectStatus").value,
        priority: prioRaw || null,
        goal_id: goalSel || null,
        priority_order: orderRaw === "" ? 0 : parseInt(orderRaw, 10) || 0,
    };

    if (!data.name) {
        alert("Name is required.");
        return;
    }

    try {
        if (id) {
            await apiFetch(`/api/projects/${id}`, {
                method: "PATCH",
                body: JSON.stringify(data),
            });
        } else {
            await apiFetch("/api/projects", {
                method: "POST",
                body: JSON.stringify(data),
            });
        }
        await projectsLoad();
        projectDetailClose();
    } catch (err) {
        alert("Save failed: " + err.message);
    }
}

async function projectDetailToggleArchive() {
    const id = document.getElementById("projectId").value;
    if (!id) return;
    const current = projectsData.find((p) => p.id === id);
    if (!current) return;
    const newState = !current.is_active;
    try {
        await apiFetch(`/api/projects/${id}`, {
            method: "PATCH",
            body: JSON.stringify({ is_active: newState }),
        });
        await projectsLoad();
        projectDetailClose();
    } catch (err) {
        alert((newState ? "Unarchive" : "Archive") + " failed: " + err.message);
    }
}

// --- Bulk edit (#90 PR35) ----------------------------------------------------

function updateBulkCount() {
    const count = document.getElementById("projectsBulkCount");
    if (count) count.textContent = `${projectsBulkSelected.size} selected`;
}

function bulkSelectedIds() {
    return Array.from(projectsBulkSelected);
}

async function bulkPatchProjects(updates) {
    const ids = bulkSelectedIds();
    if (!ids.length) { alert("Select at least one project."); return; }
    try {
        const result = await apiFetch("/api/projects/bulk", {
            method: "PATCH",
            body: JSON.stringify({ project_ids: ids, updates }),
        });
        // PR36 audit SEC-1: server returns HTTP 200 even on partial
        // per-row failures (errors collected in result.errors). Don't
        // swallow them — surface so the user knows some rows didn't
        // apply (esp. for the type/status/priority dropdowns where an
        // enum mismatch is a real possibility on dirty data).
        if (result && Array.isArray(result.errors) && result.errors.length) {
            const summary = result.errors.slice(0, 3).map(
                (e) => `${e.field || "?"}: ${e.message}`
            ).join("\n");
            alert(
                `Bulk update partially applied: ${result.updated} ok, ` +
                `${result.errors.length} errors.\n\n${summary}`
            );
        }
        await projectsLoad();
    } catch (err) {
        alert("Bulk update failed: " + err.message);
    }
}

function showProjectsBulkDropdown(anchorBtn, items) {
    // Reuse the same simple dropdown affordance pattern as app.js
    // showBulkDropdown — render as an inline popover under the button.
    document.querySelectorAll(".bulk-dropdown-popover").forEach((el) => el.remove());
    const pop = document.createElement("div");
    pop.className = "bulk-dropdown-popover";
    for (const item of items) {
        const a = document.createElement("button");
        a.type = "button";
        a.className = "bulk-dropdown-item";
        a.textContent = item.label;
        a.addEventListener("click", (e) => {
            e.stopPropagation();
            pop.remove();
            item.onClick();
        });
        pop.appendChild(a);
    }
    document.body.appendChild(pop);
    const r = anchorBtn.getBoundingClientRect();
    pop.style.position = "absolute";
    pop.style.left = `${r.left + window.scrollX}px`;
    pop.style.top = `${r.bottom + window.scrollY + 4}px`;
    setTimeout(() => {
        const dismiss = (e) => {
            if (!pop.contains(e.target)) {
                pop.remove();
                document.removeEventListener("click", dismiss);
            }
        };
        document.addEventListener("click", dismiss);
    }, 0);
}

function projectsSetupBulk() {
    const toggleBtn = document.getElementById("projectsBulkToggle");
    const toolbar = document.getElementById("projectsBulkToolbar");
    if (!toggleBtn || !toolbar) return;

    toggleBtn.addEventListener("click", () => {
        projectsBulkMode = !projectsBulkMode;
        if (!projectsBulkMode) projectsBulkSelected.clear();
        toggleBtn.classList.toggle("active", projectsBulkMode);
        toolbar.style.display = projectsBulkMode ? "" : "none";
        projectsRender();
        updateBulkCount();
    });

    document.getElementById("projectsBulkCancel").addEventListener("click", () => {
        projectsBulkMode = false;
        projectsBulkSelected.clear();
        toggleBtn.classList.remove("active");
        toolbar.style.display = "none";
        projectsRender();
    });

    document.getElementById("projectsBulkType").addEventListener("click", (e) => {
        showProjectsBulkDropdown(e.currentTarget, [
            { label: "Work", onClick: () => bulkPatchProjects({ type: "work" }) },
            { label: "Personal", onClick: () => bulkPatchProjects({ type: "personal" }) },
        ]);
    });

    document.getElementById("projectsBulkStatus").addEventListener("click", (e) => {
        showProjectsBulkDropdown(e.currentTarget, [
            { label: "Not started", onClick: () => bulkPatchProjects({ status: "not_started" }) },
            { label: "In progress", onClick: () => bulkPatchProjects({ status: "in_progress" }) },
            { label: "Done", onClick: () => bulkPatchProjects({ status: "done" }) },
            { label: "On hold", onClick: () => bulkPatchProjects({ status: "on_hold" }) },
        ]);
    });

    document.getElementById("projectsBulkPriority").addEventListener("click", (e) => {
        showProjectsBulkDropdown(e.currentTarget, [
            { label: "(none)", onClick: () => bulkPatchProjects({ priority: null }) },
            { label: "Must", onClick: () => bulkPatchProjects({ priority: "must" }) },
            { label: "Should", onClick: () => bulkPatchProjects({ priority: "should" }) },
            { label: "Could", onClick: () => bulkPatchProjects({ priority: "could" }) },
            { label: "Need more info", onClick: () => bulkPatchProjects({ priority: "need_more_info" }) },
        ]);
    });

    document.getElementById("projectsBulkGoal").addEventListener("click", (e) => {
        const items = [{ label: "(no goal)", onClick: () => bulkPatchProjects({ goal_id: null }) }];
        for (const g of projectsGoals.filter((x) => x.is_active)) {
            items.push({ label: g.title, onClick: () => bulkPatchProjects({ goal_id: g.id }) });
        }
        showProjectsBulkDropdown(e.currentTarget, items);
    });

    document.getElementById("projectsBulkArchive").addEventListener("click", () => {
        const ids = bulkSelectedIds();
        if (!ids.length) return;
        if (!confirm(`Archive ${ids.length} project(s)?`)) return;
        bulkPatchProjects({ is_active: false });
    });

    document.getElementById("projectsBulkDelete").addEventListener("click", async () => {
        const ids = bulkSelectedIds();
        if (!ids.length) return;
        if (!confirm(`Soft-delete (archive) ${ids.length} project(s)? They can be restored from the Projects archived filter.`)) return;
        try {
            await apiFetch("/api/projects/bulk", {
                method: "DELETE",
                body: JSON.stringify({ project_ids: ids }),
            });
            await projectsLoad();
        } catch (err) {
            alert("Bulk delete failed: " + err.message);
        }
    });
}

// --- Boot --------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", projectsInit);
