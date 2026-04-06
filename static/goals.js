/* goals.js — Goals view: grouped by category, progress, linked tasks */
"use strict";

const GOALS_CATEGORIES = [
    { value: "health", label: "Health" },
    { value: "personal_growth", label: "Personal Growth" },
    { value: "relationships", label: "Relationships" },
    { value: "work", label: "Work" },
];

const PRIORITY_LABELS = {
    must: "Must",
    should: "Should",
    could: "Could",
    need_more_info: "Need More Info",
};

const STATUS_LABELS = {
    not_started: "Not Started",
    in_progress: "In Progress",
    done: "Done",
    on_hold: "On Hold",
};

// --- Init --------------------------------------------------------------------

let goalsData = [];
let goalTasks = {};  // goal_id -> [task, ...]

async function goalsInit() {
    await goalsLoad();
    goalsSetupFilters();
    goalsSetupDetailPanel();
    goalsUpdateInboxBadge();
}

async function goalsLoad() {
    goalsData = await apiFetch("/api/goals?is_active=all");
    const tasks = await apiFetch("/api/tasks");
    goalTasks = {};
    for (const task of tasks) {
        if (task.goal_id) {
            if (!goalTasks[task.goal_id]) goalTasks[task.goal_id] = [];
            goalTasks[task.goal_id].push(task);
        }
    }
    // Update inbox badge
    const inboxCount = tasks.filter((t) => t.tier === "inbox").length;
    const badge = document.getElementById("inboxBadge");
    if (badge) {
        badge.textContent = inboxCount;
        badge.classList.toggle("empty", inboxCount === 0);
    }
    goalsRender();
}

// --- Rendering ---------------------------------------------------------------

function goalsRender() {
    const board = document.getElementById("goalsBoard");
    board.innerHTML = "";

    const filtered = goalsFiltered();

    // Group by category
    for (const cat of GOALS_CATEGORIES) {
        const catGoals = filtered.filter((g) => g.category === cat.value);
        if (catGoals.length === 0) continue;

        const section = document.createElement("div");
        section.className = "goals-category-section";

        const header = document.createElement("h2");
        header.className = "goals-category-header";
        header.textContent = cat.label;
        header.innerHTML += ` <span class="tier-count">${catGoals.length}</span>`;
        section.appendChild(header);

        for (const goal of catGoals) {
            section.appendChild(goalCardEl(goal));
        }
        board.appendChild(section);
    }

    if (filtered.length === 0) {
        board.innerHTML = '<p class="empty-goals">No goals match the current filters.</p>';
    }
}

function goalsFiltered() {
    let goals = goalsData.filter((g) => g.is_active);

    const cat = document.getElementById("filterCategory").value;
    if (cat) goals = goals.filter((g) => g.category === cat);

    const pri = document.getElementById("filterPriority").value;
    if (pri) goals = goals.filter((g) => g.priority === pri);

    const status = document.getElementById("filterStatus").value;
    if (status) goals = goals.filter((g) => g.status === status);

    const quarter = document.getElementById("filterQuarter").value;
    if (quarter) goals = goals.filter((g) => g.target_quarter && g.target_quarter.includes(quarter));

    return goals;
}

function goalCardEl(goal) {
    const card = document.createElement("div");
    card.className = "goal-card";
    if (!goal.is_active) card.classList.add("goal-inactive");
    card.addEventListener("click", () => goalDetailOpen(goal));

    // Top row: badges
    const badges = document.createElement("div");
    badges.className = "goal-badges";

    const priBadge = document.createElement("span");
    priBadge.className = `badge badge-priority-${goal.priority}`;
    priBadge.textContent = PRIORITY_LABELS[goal.priority];
    badges.appendChild(priBadge);

    const statusBadge = document.createElement("span");
    statusBadge.className = `badge badge-status-${goal.status}`;
    statusBadge.textContent = STATUS_LABELS[goal.status];
    badges.appendChild(statusBadge);

    if (goal.target_quarter) {
        const qBadge = document.createElement("span");
        qBadge.className = "badge badge-quarter";
        qBadge.textContent = goal.target_quarter;
        badges.appendChild(qBadge);
    }

    card.appendChild(badges);

    // Title
    const title = document.createElement("div");
    title.className = "goal-title";
    title.textContent = goal.title;
    card.appendChild(title);

    // Actions preview
    if (goal.actions) {
        const actions = document.createElement("div");
        actions.className = "goal-actions-preview";
        actions.textContent = goal.actions.length > 120
            ? goal.actions.slice(0, 120) + "…"
            : goal.actions;
        card.appendChild(actions);
    }

    // Progress
    const prog = goal.progress;
    const progressRow = document.createElement("div");
    progressRow.className = "goal-progress-row";

    if (prog.total > 0) {
        const bar = document.createElement("div");
        bar.className = "progress-bar";
        const fill = document.createElement("div");
        fill.className = "progress-fill";
        fill.style.width = (prog.percent || 0) + "%";
        if (prog.percent === 100) fill.classList.add("complete");
        bar.appendChild(fill);
        progressRow.appendChild(bar);

        const label = document.createElement("span");
        label.className = "progress-label";
        label.textContent = `${prog.completed} of ${prog.total} tasks done`;
        progressRow.appendChild(label);
    } else {
        const label = document.createElement("span");
        label.className = "progress-label muted";
        label.textContent = "No tasks linked";
        progressRow.appendChild(label);
    }

    card.appendChild(progressRow);

    return card;
}

// --- Filters -----------------------------------------------------------------

function goalsSetupFilters() {
    ["filterCategory", "filterPriority", "filterStatus", "filterQuarter"].forEach((id) => {
        document.getElementById(id).addEventListener("change", goalsRender);
    });
    document.getElementById("addGoalBtn").addEventListener("click", goalDetailNew);
}

// --- Detail panel ------------------------------------------------------------

function goalsSetupDetailPanel() {
    document.getElementById("goalDetailClose").addEventListener("click", goalDetailClose);
    document.getElementById("goalDetailOverlay").addEventListener("click", (e) => {
        if (e.target === e.currentTarget) goalDetailClose();
    });
    document.getElementById("goalDetailForm").addEventListener("submit", goalDetailSave);
    document.getElementById("goalDelete").addEventListener("click", goalDetailDelete);
    document.getElementById("addLinkedTaskBtn").addEventListener("click", goalAddLinkedTask);
    document.getElementById("linkedTaskInput").addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); goalAddLinkedTask(); }
    });
}

function goalDetailNew() {
    document.getElementById("goalId").value = "";
    document.getElementById("goalDetailHeading").textContent = "New Goal";
    document.getElementById("goalTitle").value = "";
    document.getElementById("goalCategory").value = "work";
    document.getElementById("goalPriority").value = "should";
    document.getElementById("goalPriorityRank").value = "";
    document.getElementById("goalTargetQuarter").value = "";
    document.getElementById("goalStatus").value = "not_started";
    document.getElementById("goalActions").value = "";
    document.getElementById("goalNotes").value = "";
    document.getElementById("goalDelete").style.display = "none";
    document.getElementById("linkedTasksSection").style.display = "none";
    document.getElementById("goalDetailOverlay").style.display = "";
}

function goalDetailOpen(goal) {
    document.getElementById("goalId").value = goal.id;
    document.getElementById("goalDetailHeading").textContent = "Edit Goal";
    document.getElementById("goalTitle").value = goal.title;
    document.getElementById("goalCategory").value = goal.category;
    document.getElementById("goalPriority").value = goal.priority;
    document.getElementById("goalPriorityRank").value = goal.priority_rank ?? "";
    document.getElementById("goalTargetQuarter").value = goal.target_quarter || "";
    document.getElementById("goalStatus").value = goal.status;
    document.getElementById("goalActions").value = goal.actions || "";
    document.getElementById("goalNotes").value = goal.notes || "";
    document.getElementById("goalDelete").style.display = "";

    // Linked tasks
    const section = document.getElementById("linkedTasksSection");
    section.style.display = "";
    goalRenderLinkedTasks(goal.id);

    document.getElementById("goalDetailOverlay").style.display = "";
}

function goalDetailClose() {
    document.getElementById("goalDetailOverlay").style.display = "none";
}

function goalRenderLinkedTasks(goalId) {
    const list = document.getElementById("linkedTasksList");
    const countEl = document.getElementById("linkedTaskCount");
    const tasks = goalTasks[goalId] || [];
    countEl.textContent = tasks.length;
    list.innerHTML = "";

    if (tasks.length === 0) {
        list.innerHTML = '<div class="muted" style="padding:8px 0;font-size:0.85rem">No tasks linked yet.</div>';
        return;
    }

    for (const task of tasks) {
        const row = document.createElement("div");
        row.className = "linked-task-row";

        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = task.status === "archived";
        cb.disabled = task.status === "archived";
        cb.addEventListener("change", async () => {
            await apiFetch(`/api/tasks/${task.id}`, {
                method: "PATCH",
                body: JSON.stringify({ status: "archived" }),
            });
            await goalsLoad();
            goalRenderLinkedTasks(goalId);
        });
        row.appendChild(cb);

        const label = document.createElement("span");
        label.className = "linked-task-title";
        if (task.status === "archived") label.classList.add("completed");
        label.textContent = task.title;
        row.appendChild(label);

        const tierBadge = document.createElement("span");
        tierBadge.className = "badge badge-project";
        tierBadge.textContent = task.tier.replace("_", " ");
        row.appendChild(tierBadge);

        list.appendChild(row);
    }
}

async function goalAddLinkedTask() {
    const goalId = document.getElementById("goalId").value;
    if (!goalId) return;
    const input = document.getElementById("linkedTaskInput");
    const title = input.value.trim();
    if (!title) return;
    const type = document.getElementById("linkedTaskType").value;

    try {
        await apiFetch("/api/tasks", {
            method: "POST",
            body: JSON.stringify({ title, type, goal_id: goalId }),
        });
        input.value = "";
        await goalsLoad();
        goalRenderLinkedTasks(goalId);
    } catch (err) {
        alert("Failed: " + err.message);
    }
}

async function goalDetailSave(e) {
    e.preventDefault();
    const id = document.getElementById("goalId").value;
    const data = {
        title: document.getElementById("goalTitle").value.trim(),
        category: document.getElementById("goalCategory").value,
        priority: document.getElementById("goalPriority").value,
        priority_rank: document.getElementById("goalPriorityRank").value
            ? parseInt(document.getElementById("goalPriorityRank").value, 10)
            : null,
        target_quarter: document.getElementById("goalTargetQuarter").value.trim() || null,
        status: document.getElementById("goalStatus").value,
        actions: document.getElementById("goalActions").value.trim() || null,
        notes: document.getElementById("goalNotes").value.trim() || null,
    };

    try {
        if (id) {
            await apiFetch(`/api/goals/${id}`, { method: "PATCH", body: JSON.stringify(data) });
        } else {
            await apiFetch("/api/goals", { method: "POST", body: JSON.stringify(data) });
        }
        await goalsLoad();
        goalDetailClose();
    } catch (err) {
        alert("Save failed: " + err.message);
    }
}

async function goalDetailDelete() {
    const id = document.getElementById("goalId").value;
    if (!id) return;
    await apiFetch(`/api/goals/${id}`, { method: "DELETE" });
    await goalsLoad();
    goalDetailClose();
}

function goalsUpdateInboxBadge() {
    // Handled inside goalsLoad()
}

// --- Boot --------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", goalsInit);
