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

// Fallback color when a project has none set — matches the theme blue.
const DEFAULT_PROJECT_COLOR = "#2563eb";

let projectsData = [];
let projectsGoals = [];  // for the "Linked goal" dropdown
let projectTaskCounts = {};  // project_id -> { total, active }

// --- Init --------------------------------------------------------------------

async function projectsInit() {
    await projectsLoad();
    projectsSetupFilters();
    projectsSetupDetailPanel();
}

async function projectsLoad() {
    // Load projects (is_active=all so archived ones show when filter is toggled).
    projectsData = await apiFetch("/api/projects?is_active=all");
    projectsGoals = await apiFetch("/api/goals?is_active=all");
    const tasks = await apiFetch("/api/tasks");

    // Compute task counts per project (total and active-only).
    projectTaskCounts = {};
    for (const t of tasks) {
        if (!t.project_id) continue;
        if (!projectTaskCounts[t.project_id]) {
            projectTaskCounts[t.project_id] = { total: 0, active: 0 };
        }
        projectTaskCounts[t.project_id].total += 1;
        if (t.status !== "archived") {
            projectTaskCounts[t.project_id].active += 1;
        }
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

    // Sort: active first, then by sort_order, then by name.
    list.sort((a, b) => {
        if (a.is_active !== b.is_active) return a.is_active ? -1 : 1;
        if (a.sort_order !== b.sort_order) return a.sort_order - b.sort_order;
        return a.name.localeCompare(b.name);
    });

    return list;
}

function projectsRender() {
    const board = document.getElementById("projectsBoard");
    board.innerHTML = "";

    const filtered = projectsFiltered();
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

        for (const project of group) {
            section.appendChild(projectCardEl(project));
        }
        board.appendChild(section);
    }
}

function projectCardEl(project) {
    const card = document.createElement("div");
    card.className = "goal-card project-card";
    if (!project.is_active) card.classList.add("goal-inactive");
    card.addEventListener("click", () => projectDetailOpen(project));

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
    document.getElementById("projectColor").value = DEFAULT_PROJECT_COLOR;
    document.getElementById("projectTargetQuarter").value = "";
    document.getElementById("projectSortOrder").value = "0";
    document.getElementById("projectActions").value = "";
    document.getElementById("projectNotes").value = "";
    document.getElementById("projectStatus").value = "not_started";
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
    document.getElementById("projectSortOrder").value = String(project.sort_order || 0);
    document.getElementById("projectActions").value = project.actions || "";
    document.getElementById("projectNotes").value = project.notes || "";
    document.getElementById("projectStatus").value = project.status || "not_started";
    populateGoalDropdown(project.goal_id);

    // Task summary.
    const counts = projectTaskCounts[project.id] || { total: 0, active: 0 };
    const summary = document.getElementById("projectTaskSummary");
    document.getElementById("projectTaskCount").textContent = counts.total;
    document.getElementById("projectTaskPlural").textContent = counts.total === 1 ? "" : "s";
    summary.style.display = counts.total > 0 ? "" : "none";

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
    const sortRaw = document.getElementById("projectSortOrder").value;
    const data = {
        name: document.getElementById("projectName").value.trim(),
        type: document.getElementById("projectType").value,
        color: document.getElementById("projectColor").value || null,
        target_quarter: document.getElementById("projectTargetQuarter").value.trim() || null,
        actions: document.getElementById("projectActions").value.trim() || null,
        notes: document.getElementById("projectNotes").value.trim() || null,
        status: document.getElementById("projectStatus").value,
        goal_id: goalSel || null,
        sort_order: sortRaw === "" ? 0 : parseInt(sortRaw, 10) || 0,
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

// --- Boot --------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", projectsInit);
