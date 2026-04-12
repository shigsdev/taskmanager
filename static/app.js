/* app.js — Main UI: tier board, task cards, detail panel */
"use strict";

const API = "/api/tasks";
const GOALS_API = "/api/goals";
const PROJECTS_API = "/api/projects";

// --- State -------------------------------------------------------------------

let allTasks = [];
let allGoals = [];
let allProjects = [];
let currentView = "all"; // "all" | "work" | "personal"
let projectFilter = null; // UUID string or null

// --- API helpers -------------------------------------------------------------

async function apiFetch(url, opts = {}) {
    const resp = await fetch(url, {
        headers: { "Content-Type": "application/json", ...opts.headers },
        ...opts,
    });
    if (resp.status === 204) return null;
    if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.error || resp.statusText);
    }
    return resp.json();
}

// --- Data loading ------------------------------------------------------------

async function loadTasks() {
    try {
        allTasks = await apiFetch(API);
    } catch (err) {
        console.error("Failed to load tasks:", err);
        // Don't wipe existing tasks if fetch fails (offline/cache issue)
        if (allTasks.length === 0) {
            alert("Could not load tasks. Please check your connection and reload.");
        }
        return;
    }
    renderBoard();
}

async function loadGoals() {
    allGoals = await apiFetch(GOALS_API);
    taskDetailPopulateGoals();
}

async function loadProjects() {
    allProjects = await apiFetch(PROJECTS_API);
    taskDetailPopulateProjects();
    renderProjectFilter();
}

async function init() {
    await Promise.all([loadTasks(), loadGoals(), loadProjects()]);
    setupNavTabs();
    setupCollapse();
    setupDetailPanel();
    // Populate the Completed section immediately so its header count is
    // correct even before the user expands it for the first time.
    loadCompletedTasks();
}

// --- Rendering ---------------------------------------------------------------

const TIER_ORDER = ["inbox", "today", "this_week", "backlog", "freezer"];
const TIER_EMPTY = {
    inbox: "All caught up — inbox is empty",
    today: "No tasks for today",
    this_week: "No tasks this week",
    backlog: "Backlog is empty",
    freezer: "Nothing in the freezer",
};

function renderBoard() {
    for (const tier of TIER_ORDER) {
        const list = document.querySelector(`.task-list[data-tier="${tier}"]`);
        if (!list) continue;
        const tasks = filteredTasks().filter((t) => t.tier === tier);
        list.innerHTML = "";
        if (tasks.length === 0) {
            list.classList.add("empty-state");
            list.setAttribute("data-empty-msg", TIER_EMPTY[tier]);
        } else {
            list.classList.remove("empty-state");
            list.removeAttribute("data-empty-msg");

            // In work view with no project filter, group by project
            if (currentView === "work" && !projectFilter) {
                renderTierGroupedByProject(list, tasks);
            } else {
                for (const task of tasks) {
                    list.appendChild(taskCardEl(task));
                }
            }
        }
        // Update count
        const section = list.closest(".tier");
        const count = section.querySelector(".tier-count");
        if (count) count.textContent = tasks.length;
    }
    updateInboxBadge();
    updateTodayWarning();
    updateBulkTriageBtn();
    setupDragAndDrop();
}

function renderTierGroupedByProject(list, tasks) {
    // Collect tasks by project
    const byProject = new Map();
    const noProject = [];
    for (const task of tasks) {
        if (task.project_id) {
            if (!byProject.has(task.project_id)) byProject.set(task.project_id, []);
            byProject.get(task.project_id).push(task);
        } else {
            noProject.push(task);
        }
    }

    // Render each project group
    for (const project of allProjects) {
        const projectTasks = byProject.get(project.id);
        if (!projectTasks) continue;
        const groupHeader = document.createElement("div");
        groupHeader.className = "project-group-header";
        groupHeader.innerHTML = `<span class="project-dot" style="background:${project.color || '#999'}"></span> ${escapeHtml(project.name)}`;
        list.appendChild(groupHeader);
        for (const task of projectTasks) {
            list.appendChild(taskCardEl(task));
        }
    }

    // Tasks without project
    if (noProject.length > 0) {
        const groupHeader = document.createElement("div");
        groupHeader.className = "project-group-header";
        groupHeader.textContent = "No project";
        list.appendChild(groupHeader);
        for (const task of noProject) {
            list.appendChild(taskCardEl(task));
        }
    }
}

// --- Drag and drop reordering ------------------------------------------------
// Supports both desktop (HTML5 drag) and mobile (touch events).

let draggedCard = null;
let dragDropInitialized = false;
let touchDragState = null; // { card, placeholder, startY, scrollInterval }

function setupDragAndDrop() {
    if (dragDropInitialized) return;
    dragDropInitialized = true;

    for (const tier of TIER_ORDER) {
        const list = document.querySelector(`.task-list[data-tier="${tier}"]`);
        if (!list) continue;

        // --- Desktop: HTML5 drag events ---
        list.addEventListener("dragover", function (e) {
            e.preventDefault();
            if (!draggedCard) return;
            e.dataTransfer.dropEffect = "move";
            const afterEl = getDragAfterElement(list, e.clientY);
            if (afterEl) {
                list.insertBefore(draggedCard, afterEl);
            } else {
                list.appendChild(draggedCard);
            }
        });

        list.addEventListener("drop", function (e) {
            e.preventDefault();
            if (!draggedCard) return;
            finishDrop(list);
        });
    }

    // --- Completed section: drop-to-archive target ---
    // The Completed section isn't a tier — it's a status filter — so it
    // needs its own drop handler that PATCHes {status: "archived"} instead
    // of the normal tier move. We attach to the whole <section> (not just
    // the inner list) so the drop zone works even when the list is
    // collapsed, which is the default state.
    const completedSection = document.getElementById("tierCompleted");
    if (completedSection) {
        completedSection.addEventListener("dragenter", function (e) {
            if (!draggedCard) return;
            // Don't offer to "complete" a card that's already completed.
            if (draggedCard.dataset.sourceTier === "completed") return;
            e.preventDefault();
            completedSection.classList.add("drag-over");
        });
        completedSection.addEventListener("dragover", function (e) {
            if (!draggedCard) return;
            if (draggedCard.dataset.sourceTier === "completed") return;
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
            completedSection.classList.add("drag-over");
        });
        completedSection.addEventListener("dragleave", function (e) {
            // Only clear when the pointer actually leaves the section,
            // not when it moves between child elements inside it.
            if (!completedSection.contains(e.relatedTarget)) {
                completedSection.classList.remove("drag-over");
            }
        });
        completedSection.addEventListener("drop", function (e) {
            e.preventDefault();
            e.stopPropagation();
            completedSection.classList.remove("drag-over");
            if (!draggedCard) return;
            const taskId = draggedCard.dataset.id;
            draggedCard.classList.remove("dragging");
            draggedCard = null;
            taskComplete(taskId);
        });
    }

    // --- Mobile: touch events (document-level for cross-tier dragging) ---
    document.addEventListener("touchmove", onTouchMove, { passive: false });
    document.addEventListener("touchend", onTouchEnd);
}

function onTouchMove(e) {
    if (!touchDragState) return;
    e.preventDefault(); // stop page scrolling while dragging

    var touch = e.touches[0];
    var card = touchDragState.card;

    // Move the card visually
    var dy = touch.clientY - touchDragState.startY;
    card.style.transform = "translateY(" + dy + "px)";
    card.style.zIndex = "9999";

    // Is the finger over the Completed drop-zone?
    // Checked BEFORE the tier-list scan so an inbox card dropped on the
    // completed section archives instead of landing in a tier underneath.
    // Skip this when the card being dragged ALREADY lives in completed —
    // dropping it back on itself would be a no-op.
    var completedSection = document.getElementById("tierCompleted");
    var draggingFromCompleted = card.dataset.sourceTier === "completed";
    if (!draggingFromCompleted && completedSection &&
            isPointOverEl(completedSection, touch.clientX, touch.clientY)) {
        completedSection.classList.add("drag-over");
        touchDragState.overCompleted = true;
        return;
    }
    if (completedSection) {
        completedSection.classList.remove("drag-over");
    }
    touchDragState.overCompleted = false;

    // Find which tier list we're over and reposition
    var targetList = getListUnderPoint(touch.clientX, touch.clientY);
    if (targetList) {
        var afterEl = getDragAfterElement(targetList, touch.clientY);
        if (afterEl) {
            targetList.insertBefore(card, afterEl);
        } else {
            targetList.appendChild(card);
        }
    }
}

function onTouchEnd() {
    if (!touchDragState) return;
    var card = touchDragState.card;
    var overCompleted = touchDragState.overCompleted;

    // Reset visual state
    card.style.transform = "";
    card.style.zIndex = "";
    card.classList.remove("dragging");
    var completedSection = document.getElementById("tierCompleted");
    if (completedSection) completedSection.classList.remove("drag-over");

    if (overCompleted) {
        // Dropped on Completed → archive instead of tier-move
        var taskId = card.dataset.id;
        touchDragState = null;
        draggedCard = null;
        taskComplete(taskId);
        return;
    }

    // Find the list it ended up in
    var parentList = card.closest(".task-list");
    if (parentList && parentList.dataset.tier) {
        finishDrop(parentList);
    }

    touchDragState = null;
    draggedCard = null;
}

function isPointOverEl(el, x, y) {
    var rect = el.getBoundingClientRect();
    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
}

function getListUnderPoint(x, y) {
    for (var i = 0; i < TIER_ORDER.length; i++) {
        var list = document.querySelector('.task-list[data-tier="' + TIER_ORDER[i] + '"]');
        if (!list) continue;
        var rect = list.getBoundingClientRect();
        // Use generous vertical bounds for easier targeting
        if (y >= rect.top - 20 && y <= rect.bottom + 20 && x >= rect.left && x <= rect.right) {
            return list;
        }
    }
    return null;
}

function finishDrop(list) {
    if (!draggedCard) return;
    var targetTier = list.dataset.tier;
    var taskId = draggedCard.dataset.id;
    var sourceTier = draggedCard.dataset.sourceTier;

    var cardIds = Array.from(list.querySelectorAll(".task-card"))
        .map(function (c) { return c.dataset.id; });

    if (sourceTier === "completed") {
        // Completed → tier: restore status=active AND set new tier
        apiFetch(API + "/" + taskId, {
            method: "PATCH",
            body: JSON.stringify({ status: "active", tier: targetTier }),
        }).then(function () {
            return saveReorder(targetTier, cardIds);
        }).then(function () {
            loadTasks();
            loadCompletedTasks();
        });
    } else if (sourceTier !== targetTier) {
        apiFetch(API + "/" + taskId, {
            method: "PATCH",
            body: JSON.stringify({ tier: targetTier }),
        }).then(function () {
            return saveReorder(targetTier, cardIds);
        }).then(function () {
            loadTasks();
        });
    } else {
        saveReorder(targetTier, cardIds);
    }
}

function getDragAfterElement(list, y) {
    var cards = Array.from(list.querySelectorAll(".task-card:not(.dragging)"));
    var closest = null;
    var closestOffset = Number.NEGATIVE_INFINITY;

    for (var i = 0; i < cards.length; i++) {
        var box = cards[i].getBoundingClientRect();
        var offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closestOffset) {
            closestOffset = offset;
            closest = cards[i];
        }
    }
    return closest;
}

async function saveReorder(tier, taskIds) {
    await apiFetch(API + "/reorder", {
        method: "POST",
        body: JSON.stringify({ tier: tier, task_ids: taskIds }),
    });
}

function filteredTasks() {
    let tasks = allTasks;
    if (currentView === "work") tasks = tasks.filter((t) => t.type === "work");
    if (currentView === "personal") tasks = tasks.filter((t) => t.type === "personal");
    if (projectFilter) tasks = tasks.filter((t) => t.project_id === projectFilter);
    return tasks;
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function taskCardEl(task) {
    const card = document.createElement("div");
    card.className = "task-card";
    card.dataset.id = task.id;
    card.dataset.sourceTier = task.tier;
    card.draggable = true;

    // Desktop drag events
    card.addEventListener("dragstart", function (e) {
        draggedCard = card;
        card.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", task.id);
    });
    card.addEventListener("dragend", function () {
        card.classList.remove("dragging");
        draggedCard = null;
    });

    // Mobile touch: long-press to start drag (500ms hold)
    var longPressTimer = null;
    var touchStartX = 0;
    var touchStartY = 0;
    card.addEventListener("touchstart", function (e) {
        touchStartX = e.touches[0].clientX;
        touchStartY = e.touches[0].clientY;
        longPressTimer = setTimeout(function () {
            longPressTimer = null;
            draggedCard = card;
            touchDragState = {
                card: card,
                startY: e.touches[0].clientY,
            };
            card.classList.add("dragging");
            // Haptic feedback if available
            if (navigator.vibrate) navigator.vibrate(50);
        }, 500);
    }, { passive: true });
    card.addEventListener("touchmove", function (e) {
        // Only cancel long-press if finger moves more than 10px (natural jitter tolerance)
        if (longPressTimer) {
            var dx = e.touches[0].clientX - touchStartX;
            var dy = e.touches[0].clientY - touchStartY;
            if (Math.sqrt(dx * dx + dy * dy) > 10) {
                clearTimeout(longPressTimer);
                longPressTimer = null;
            }
        }
    }, { passive: true });
    card.addEventListener("touchend", function () {
        if (longPressTimer) {
            clearTimeout(longPressTimer);
            longPressTimer = null;
        }
    });

    const today = new Date().toISOString().slice(0, 10);

    // Triage checkbox (inbox only)
    const triageCheck = document.createElement("input");
    triageCheck.type = "checkbox";
    triageCheck.className = "triage-check";
    triageCheck.addEventListener("click", (e) => e.stopPropagation());
    triageCheck.addEventListener("change", updateBulkTriageBtn);
    card.appendChild(triageCheck);

    // Complete checkbox
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "task-checkbox";
    cb.title = "Complete task";
    cb.addEventListener("click", (e) => e.stopPropagation());
    cb.addEventListener("change", () => taskComplete(task.id));
    card.appendChild(cb);

    // Body
    const body = document.createElement("div");
    body.className = "task-body";

    const title = document.createElement("div");
    title.className = "task-title";
    title.textContent = task.title;
    body.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "task-meta";

    // Type badge
    const typeBadge = document.createElement("span");
    typeBadge.className = `badge badge-${task.type}`;
    typeBadge.textContent = task.type;
    meta.appendChild(typeBadge);

    // Project badge (work tasks)
    if (task.project_id) {
        const project = allProjects.find((p) => p.id === task.project_id);
        if (project) {
            const projBadge = document.createElement("span");
            projBadge.className = "badge badge-project";
            if (project.color) projBadge.style.borderColor = project.color;
            projBadge.textContent = project.name;
            meta.appendChild(projBadge);
        }
    }

    // Due date
    if (task.due_date) {
        const dueBadge = document.createElement("span");
        dueBadge.className = "badge badge-due";
        if (task.due_date < today) {
            dueBadge.classList.add("overdue");
            dueBadge.textContent = `overdue: ${task.due_date}`;
        } else if (task.due_date === today) {
            dueBadge.classList.add("due-today");
            dueBadge.textContent = "due today";
        } else {
            dueBadge.textContent = `due ${task.due_date}`;
        }
        meta.appendChild(dueBadge);
    }

    // Goal badge
    if (task.goal_id) {
        const goal = allGoals.find((g) => g.id === task.goal_id);
        if (goal) {
            const goalBadge = document.createElement("span");
            goalBadge.className = "badge badge-goal";
            goalBadge.textContent = goal.title;
            meta.appendChild(goalBadge);
        }
    }

    // URL / article badge
    if (task.url) {
        const urlBadge = document.createElement("a");
        urlBadge.className = "badge badge-url";
        urlBadge.textContent = "Read ↗";
        urlBadge.href = task.url;
        urlBadge.target = "_blank";
        urlBadge.rel = "noopener noreferrer";
        urlBadge.title = task.url;
        urlBadge.addEventListener("click", (e) => e.stopPropagation());
        meta.appendChild(urlBadge);
    }

    // Checklist progress
    if (task.checklist && task.checklist.length > 0) {
        const done = task.checklist.filter((c) => c.checked).length;
        const clBadge = document.createElement("span");
        clBadge.className = "badge badge-checklist";
        if (done === task.checklist.length) clBadge.classList.add("all-done");
        clBadge.textContent = `${done}/${task.checklist.length}`;
        meta.appendChild(clBadge);
    }

    // Subtask progress badge (parent tasks only)
    if (task.subtask_count > 0) {
        const stBadge = document.createElement("span");
        stBadge.className = "badge badge-subtask";
        if (task.subtask_done === task.subtask_count) stBadge.classList.add("all-done");
        stBadge.textContent = `${task.subtask_done}/${task.subtask_count} subtasks`;
        meta.appendChild(stBadge);
    }

    // Parent indicator (subtasks only)
    if (task.parent_id) {
        const parent = allTasks.find((t) => t.id === task.parent_id);
        if (parent) {
            const parentBadge = document.createElement("span");
            parentBadge.className = "badge badge-parent";
            parentBadge.textContent = `↳ ${parent.title}`;
            parentBadge.title = `Subtask of: ${parent.title}`;
            meta.appendChild(parentBadge);
        }
    }

    body.appendChild(meta);
    card.appendChild(body);

    // Quick actions
    const actions = document.createElement("div");
    actions.className = "task-quick-actions";

    // Complete button — shown on every tier, including inbox, so users
    // can archive a task straight from triage without a two-step move.
    const completeBtn = document.createElement("button");
    completeBtn.textContent = "✓ Done";
    completeBtn.title = "Mark complete";
    completeBtn.className = "quick-complete-btn";
    completeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        taskComplete(task.id);
    });
    actions.appendChild(completeBtn);

    const tierBtns = TIER_ORDER.filter((t) => t !== task.tier && t !== "inbox");
    for (const t of tierBtns) {
        const btn = document.createElement("button");
        btn.textContent = tierLabel(t);
        btn.title = `Move to ${tierLabel(t)}`;
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            taskMoveTier(task.id, t);
        });
        actions.appendChild(btn);
    }
    card.appendChild(actions);

    // Click to open detail
    card.addEventListener("click", () => taskDetailOpen(task));

    return card;
}

function tierLabel(tier) {
    const labels = {
        today: "Today",
        this_week: "Week",
        backlog: "Backlog",
        freezer: "Freezer",
        inbox: "Inbox",
    };
    return labels[tier] || tier;
}

// --- Inbox badge & Today warning -------------------------------------------

function updateInboxBadge() {
    const badge = document.getElementById("inboxBadge");
    const count = allTasks.filter((t) => t.tier === "inbox").length;
    badge.textContent = count;
    badge.classList.toggle("empty", count === 0);
}

function updateTodayWarning() {
    const warn = document.getElementById("todayWarning");
    const count = filteredTasks().filter((t) => t.tier === "today").length;
    warn.style.display = count > 7 ? "" : "none";
}

// --- Project filter (Work view) ----------------------------------------------

function renderProjectFilter() {
    const container = document.getElementById("projectFilterBar");
    if (!container) return;
    container.innerHTML = "";

    const allBtn = document.createElement("button");
    allBtn.className = "btn-sm project-filter-btn" + (!projectFilter ? " active" : "");
    allBtn.textContent = "All projects";
    allBtn.addEventListener("click", () => { projectFilter = null; renderBoard(); renderCompletedList(); renderProjectFilter(); });
    container.appendChild(allBtn);

    for (const p of allProjects) {
        const btn = document.createElement("button");
        btn.className = "btn-sm project-filter-btn" + (projectFilter === p.id ? " active" : "");
        btn.innerHTML = `<span class="project-dot" style="background:${p.color || '#999'}"></span> ${escapeHtml(p.name)}`;
        btn.addEventListener("click", () => { projectFilter = p.id; renderBoard(); renderCompletedList(); renderProjectFilter(); });
        container.appendChild(btn);
    }
}

// --- Bulk triage -------------------------------------------------------------

function updateBulkTriageBtn() {
    const btn = document.getElementById("bulkTriageBtn");
    const checked = document.querySelectorAll(
        '.tier[data-tier="inbox"] .triage-check:checked'
    );
    btn.style.display = checked.length > 0 ? "" : "none";
}

document.getElementById("bulkTriageBtn").addEventListener("click", (e) => {
    const existing = document.querySelector(".triage-dropdown");
    if (existing) { existing.remove(); return; }

    const dd = document.createElement("div");
    dd.className = "triage-dropdown";
    dd.style.top = e.target.offsetTop + e.target.offsetHeight + "px";
    dd.style.right = "14px";

    for (const tier of ["today", "this_week", "backlog", "freezer"]) {
        const btn = document.createElement("button");
        btn.textContent = tierLabel(tier);
        btn.addEventListener("click", () => {
            bulkMoveTier(tier);
            dd.remove();
        });
        dd.appendChild(btn);
    }
    e.target.parentElement.appendChild(dd);
    document.addEventListener("click", function close(ev) {
        if (!dd.contains(ev.target) && ev.target !== e.target) {
            dd.remove();
            document.removeEventListener("click", close);
        }
    });
});

async function bulkMoveTier(tier) {
    const checks = document.querySelectorAll(
        '.tier[data-tier="inbox"] .triage-check:checked'
    );
    const ids = Array.from(checks).map((c) => c.closest(".task-card").dataset.id);
    await Promise.all(
        ids.map((id) => apiFetch(`${API}/${id}`, {
            method: "PATCH",
            body: JSON.stringify({ tier }),
        }))
    );
    await loadTasks();
}

// --- Task mutations ----------------------------------------------------------

async function taskMoveTier(id, tier) {
    await apiFetch(`${API}/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ tier }),
    });
    await loadTasks();
}

async function taskComplete(id) {
    const task = allTasks.find((t) => t.id === id);

    // Parent tasks with open subtasks: use the /complete endpoint which
    // returns a 422 warning. Prompt user to auto-close or cancel.
    if (task && task.subtask_count > task.subtask_done) {
        const open = task.subtask_count - task.subtask_done;
        const ok = confirm(
            `This task has ${open} open subtask(s).\n\nComplete all subtasks too?`
        );
        if (!ok) return;
        await apiFetch(`${API}/${id}/complete`, {
            method: "POST",
            body: JSON.stringify({ complete_subtasks: true }),
        });
    } else {
        await apiFetch(`${API}/${id}`, {
            method: "PATCH",
            body: JSON.stringify({ status: "archived" }),
        });
    }

    await loadTasks();
    loadCompletedTasks();
}

async function taskDelete(id) {
    await apiFetch(`${API}/${id}`, { method: "DELETE" });
    await loadTasks();
    taskDetailClose();
}

// --- Nav tabs ----------------------------------------------------------------

function setupNavTabs() {
    document.querySelectorAll(".nav-tab[data-view]").forEach((tab) => {
        tab.addEventListener("click", (e) => {
            e.preventDefault();
            // Only clear active state on the view-filter sub-nav, not on
            // the main page tabs in the header (which now include a
            // permanent .active marker for the current page).
            document.querySelectorAll(".view-filter-btn").forEach((t) => t.classList.remove("active"));
            tab.classList.add("active");
            currentView = tab.dataset.view;
            projectFilter = null;
            renderBoard();
            renderCompletedList();
            // Show/hide project filter bar
            const bar = document.getElementById("projectFilterBar");
            if (bar) {
                bar.style.display = currentView === "work" ? "" : "none";
                renderProjectFilter();
            }
        });
    });
}

// --- Collapse / expand -------------------------------------------------------

function setupCollapse() {
    document.querySelectorAll(".collapse-toggle").forEach((btn) => {
        btn.addEventListener("click", () => {
            const section = btn.closest(".tier");
            const body = section.querySelector(".tier-body");
            const expanded = btn.getAttribute("aria-expanded") === "true";
            btn.setAttribute("aria-expanded", !expanded);
            btn.textContent = expanded ? "▸" : "▾";
            if (expanded) {
                body.style.display = "none";
            } else {
                body.style.display = "";
                // Load completed tasks on first expand
                if (section.id === "tierCompleted" && !section.dataset.loaded) {
                    loadCompletedTasks();
                }
            }
        });
    });
}

// --- Completed tasks ---------------------------------------------------------

let completedLoaded = false;
let allCompleted = [];  // raw cache so view/project filter changes don't re-hit the API

async function loadCompletedTasks() {
    const section = document.getElementById("tierCompleted");
    const list = document.getElementById("completedList");
    list.innerHTML = "<div class='loading-msg'>Loading...</div>";
    section.dataset.loaded = "true";

    allCompleted = await apiFetch(API + "?status=archived");
    renderCompletedList();
}

function filteredCompleted() {
    let tasks = allCompleted;
    if (currentView === "work") tasks = tasks.filter((t) => t.type === "work");
    if (currentView === "personal") tasks = tasks.filter((t) => t.type === "personal");
    if (projectFilter) tasks = tasks.filter((t) => t.project_id === projectFilter);
    return tasks;
}

function renderCompletedList() {
    const list = document.getElementById("completedList");
    const count = document.getElementById("completedCount");
    const tasks = filteredCompleted();
    list.innerHTML = "";
    count.textContent = tasks.length;

    if (tasks.length === 0) {
        list.classList.add("empty-state");
        list.setAttribute("data-empty-msg", "No completed tasks yet");
        return;
    }

    list.classList.remove("empty-state");
    // Show most recently completed first
    for (const task of tasks) {
        const card = document.createElement("div");
        card.className = "task-card completed-card";
        card.dataset.id = task.id;
        // Marker used by finishDrop() + touch handlers to route drops
        // from the Completed list into taskRestore instead of a tier move.
        card.dataset.sourceTier = "completed";
        card.draggable = true;

        // Desktop drag
        card.addEventListener("dragstart", function (e) {
            draggedCard = card;
            card.classList.add("dragging");
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData("text/plain", task.id);
        });
        card.addEventListener("dragend", function () {
            card.classList.remove("dragging");
            draggedCard = null;
        });

        // Mobile long-press to drag
        var cLongPress = null;
        var cStartX = 0;
        var cStartY = 0;
        card.addEventListener("touchstart", function (e) {
            cStartX = e.touches[0].clientX;
            cStartY = e.touches[0].clientY;
            cLongPress = setTimeout(function () {
                cLongPress = null;
                draggedCard = card;
                touchDragState = {
                    card: card,
                    startY: e.touches[0].clientY,
                };
                card.classList.add("dragging");
                if (navigator.vibrate) navigator.vibrate(50);
            }, 500);
        }, { passive: true });
        card.addEventListener("touchmove", function (e) {
            if (cLongPress) {
                var dx = e.touches[0].clientX - cStartX;
                var dy = e.touches[0].clientY - cStartY;
                if (Math.sqrt(dx * dx + dy * dy) > 10) {
                    clearTimeout(cLongPress);
                    cLongPress = null;
                }
            }
        }, { passive: true });
        card.addEventListener("touchend", function () {
            if (cLongPress) { clearTimeout(cLongPress); cLongPress = null; }
        });

        const title = document.createElement("div");
        title.className = "task-title completed-title";
        title.textContent = task.title;
        card.appendChild(title);

        const meta = document.createElement("div");
        meta.className = "task-meta";

        const typeBadge = document.createElement("span");
        typeBadge.className = "badge badge-" + task.type;
        typeBadge.textContent = task.type;
        meta.appendChild(typeBadge);

        const dateBadge = document.createElement("span");
        dateBadge.className = "badge";
        dateBadge.textContent = task.updated_at.slice(0, 10);
        meta.appendChild(dateBadge);

        card.appendChild(meta);

        // Re-open dropdown
        const reopenWrap = document.createElement("div");
        reopenWrap.className = "reopen-wrap";
        const reopenBtn = document.createElement("button");
        reopenBtn.className = "btn-sm reopen-btn";
        reopenBtn.textContent = "Re-open ▾";
        reopenBtn.title = "Move back to active tasks";
        reopenBtn.addEventListener("click", function (e) {
            e.stopPropagation();
            // Toggle dropdown
            const existing = reopenWrap.querySelector(".reopen-dropdown");
            if (existing) { existing.remove(); return; }
            const dd = document.createElement("div");
            dd.className = "reopen-dropdown";
            ["inbox", "today", "this_week", "backlog", "freezer"].forEach(function (t) {
                const opt = document.createElement("button");
                opt.textContent = tierLabel(t);
                opt.addEventListener("click", function (ev) {
                    ev.stopPropagation();
                    taskRestore(task.id, t);
                    dd.remove();
                });
                dd.appendChild(opt);
            });
            reopenWrap.appendChild(dd);
            // Close on outside click
            document.addEventListener("click", function close() {
                dd.remove();
                document.removeEventListener("click", close);
            }, { once: true });
        });
        reopenWrap.appendChild(reopenBtn);
        card.appendChild(reopenWrap);

        // Click to view detail
        card.addEventListener("click", function () {
            taskDetailOpen(task);
        });

        list.appendChild(card);
    }
}

async function taskRestore(id, tier) {
    tier = tier || "inbox";
    await apiFetch(API + "/" + id, {
        method: "PATCH",
        body: JSON.stringify({ status: "active", tier: tier }),
    });
    await loadTasks();
    // Always reload — keeps #completedCount in sync even if the
    // Completed section hasn't been expanded yet.
    loadCompletedTasks();
}

// --- Detail panel ------------------------------------------------------------

function setupDetailPanel() {
    document.getElementById("detailClose").addEventListener("click", taskDetailClose);
    document.getElementById("detailOverlay").addEventListener("click", (e) => {
        if (e.target === e.currentTarget) taskDetailClose();
    });
    document.getElementById("detailForm").addEventListener("submit", taskDetailSave);
    document.getElementById("detailDelete").addEventListener("click", () => {
        const id = document.getElementById("detailId").value;
        if (id) taskDelete(id);
    });
    document.getElementById("detailComplete").addEventListener("click", () => {
        const id = document.getElementById("detailId").value;
        if (id) {
            taskDetailClose();
            taskComplete(id);
        }
    });
    document.getElementById("addChecklistItem").addEventListener("click", () => {
        taskDetailAddChecklistRow("", false);
    });
    setupAddSubtask();
}

function taskDetailOpen(task) {
    document.getElementById("detailId").value = task.id;
    document.getElementById("detailTitle").value = task.title;
    document.getElementById("detailTier").value = task.tier;
    document.getElementById("detailType").value = task.type;
    document.getElementById("detailProject").value = task.project_id || "";
    document.getElementById("detailDueDate").value = task.due_date || "";
    document.getElementById("detailGoal").value = task.goal_id || "";
    const urlInput = document.getElementById("detailUrl");
    const urlOpen = document.getElementById("detailUrlOpen");
    urlInput.value = task.url || "";
    if (task.url) {
        urlOpen.href = task.url;
        urlOpen.style.display = "";
    } else {
        urlOpen.style.display = "none";
    }
    urlInput.addEventListener("input", () => {
        const v = urlInput.value.trim();
        if (v.startsWith("http://") || v.startsWith("https://")) {
            urlOpen.href = v;
            urlOpen.style.display = "";
        } else {
            urlOpen.style.display = "none";
        }
    });

    document.getElementById("detailNotes").value = task.notes || "";

    // Show/hide project selector based on type
    taskDetailToggleProject(task.type);

    // Checklist
    const container = document.getElementById("checklistItems");
    container.innerHTML = "";
    if (task.checklist) {
        for (const item of task.checklist) {
            taskDetailAddChecklistRow(item.text, item.checked);
        }
    }

    // Subtasks section — only for non-subtask tasks (one level deep)
    const subtaskSection = document.getElementById("subtaskSection");
    const subtaskList = document.getElementById("subtaskItems");
    subtaskList.innerHTML = "";
    if (task.parent_id) {
        // This IS a subtask — hide the subtask section and show parent link
        subtaskSection.style.display = "none";
    } else {
        subtaskSection.style.display = "";
        taskDetailLoadSubtasks(task.id);
    }

    // Meta
    document.getElementById("detailMeta").innerHTML =
        `Created: ${new Date(task.created_at).toLocaleDateString()}<br>` +
        `Updated: ${new Date(task.updated_at).toLocaleDateString()}`;

    document.getElementById("detailOverlay").style.display = "";
}

function taskDetailToggleProject(type) {
    const projectField = document.getElementById("detailProjectField");
    if (projectField) {
        projectField.style.display = type === "work" ? "" : "none";
    }
}

function taskDetailClose() {
    document.getElementById("detailOverlay").style.display = "none";
}

function taskDetailAddChecklistRow(text, checked) {
    const container = document.getElementById("checklistItems");
    const row = document.createElement("div");
    row.className = "checklist-item";

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = checked;
    row.appendChild(cb);

    const input = document.createElement("input");
    input.type = "text";
    input.value = text;
    input.placeholder = "Checklist item…";
    row.appendChild(input);

    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "remove-item";
    rm.textContent = "✕";
    rm.addEventListener("click", () => row.remove());
    row.appendChild(rm);

    container.appendChild(row);
}

function taskDetailPopulateGoals() {
    const sel = document.getElementById("detailGoal");
    while (sel.options.length > 1) sel.remove(1);
    for (const goal of allGoals) {
        const opt = document.createElement("option");
        opt.value = goal.id;
        opt.textContent = `${goal.title} (${goal.category})`;
        sel.appendChild(opt);
    }
}

function taskDetailPopulateProjects() {
    const sel = document.getElementById("detailProject");
    if (!sel) return;
    while (sel.options.length > 1) sel.remove(1);
    for (const p of allProjects) {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = p.name;
        sel.appendChild(opt);
    }
}

async function taskDetailSave(e) {
    e.preventDefault();
    const id = document.getElementById("detailId").value;
    if (!id) return;

    // Collect checklist
    const clItems = [];
    document.querySelectorAll("#checklistItems .checklist-item").forEach((row, i) => {
        const text = row.querySelector('input[type="text"]').value.trim();
        const checked = row.querySelector('input[type="checkbox"]').checked;
        if (text) {
            clItems.push({ id: String(i), text, checked });
        }
    });

    const type = document.getElementById("detailType").value;
    const rawUrl = document.getElementById("detailUrl").value.trim();
    const data = {
        title: document.getElementById("detailTitle").value.trim(),
        tier: document.getElementById("detailTier").value,
        type: type,
        project_id: type === "work" ? (document.getElementById("detailProject").value || null) : null,
        due_date: document.getElementById("detailDueDate").value || null,
        goal_id: document.getElementById("detailGoal").value || null,
        url: rawUrl || null,
        notes: document.getElementById("detailNotes").value || "",
        checklist: clItems,
    };

    try {
        await apiFetch(`${API}/${id}`, {
            method: "PATCH",
            body: JSON.stringify(data),
        });
        await loadTasks();
        taskDetailClose();
    } catch (err) {
        alert("Save failed: " + err.message);
    }
}

// --- Subtasks in detail panel ------------------------------------------------

async function taskDetailLoadSubtasks(parentId) {
    const list = document.getElementById("subtaskItems");
    list.innerHTML = "";
    let subtasks;
    try {
        subtasks = await apiFetch(`${API}/${parentId}/subtasks`);
    } catch {
        return;
    }
    for (const sub of subtasks) {
        const row = document.createElement("div");
        row.className = "subtask-row";

        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.title = "Complete subtask";
        cb.addEventListener("change", async () => {
            await apiFetch(`${API}/${sub.id}`, {
                method: "PATCH",
                body: JSON.stringify({ status: "archived" }),
            });
            await loadTasks();
            taskDetailLoadSubtasks(parentId);
        });
        row.appendChild(cb);

        const titleEl = document.createElement("span");
        titleEl.className = "subtask-title";
        titleEl.textContent = sub.title;
        titleEl.addEventListener("click", () => {
            const full = allTasks.find((t) => t.id === sub.id) || sub;
            taskDetailOpen(full);
        });
        row.appendChild(titleEl);

        const tierBadge = document.createElement("span");
        tierBadge.className = "badge badge-subtask-tier";
        tierBadge.textContent = tierLabel(sub.tier);
        row.appendChild(tierBadge);

        list.appendChild(row);
    }
}

function setupAddSubtask() {
    const btn = document.getElementById("addSubtaskBtn");
    const input = document.getElementById("subtaskInput");
    if (!btn || !input) return;

    btn.addEventListener("click", addSubtask);
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            addSubtask();
        }
    });
}

async function addSubtask() {
    const input = document.getElementById("subtaskInput");
    const title = input.value.trim();
    if (!title) return;

    const parentId = document.getElementById("detailId").value;
    if (!parentId) return;

    const parentTask = allTasks.find((t) => t.id === parentId);
    const type = parentTask ? parentTask.type : "work";

    try {
        await apiFetch(API, {
            method: "POST",
            body: JSON.stringify({
                title,
                type,
                tier: "inbox",
                parent_id: parentId,
            }),
        });
        input.value = "";
        await loadTasks();
        taskDetailLoadSubtasks(parentId);
    } catch (err) {
        alert("Failed to add subtask: " + err.message);
    }
}

// --- Boot --------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", init);
