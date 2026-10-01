/* goals.js — Goals view: grouped by category, progress, linked tasks */
"use strict";

// Must cover EVERY GoalCategory enum member (models.py) — goalsRender()
// groups goals by iterating this list, so a category missing here renders
// NO section and its goals silently vanish from the page. #277 (2026-05-30):
// BAU (added to the enum in #68) was missing here, so BAU goals disappeared
// from /goals even though the data was intact. tests/test_goal_category_
// pickers.py is the drift guard that fails if this list (or the scan/import
// pickers) ever falls behind the enum again.
const GOALS_CATEGORIES = [
    { value: "health", label: "Health" },
    { value: "personal_growth", label: "Personal Growth" },
    { value: "relationships", label: "Relationships" },
    { value: "work", label: "Work" },
    { value: "bau", label: "BAU" },
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

// #343 state. `goalProjects` is keyed by goal id, with goal-less
// projects under the sentinel so one map covers both the goal cards and
// the "No goal" zone.
const _GOALS_NO_GOAL = "__no_goal__";
let goalProjects = {};            // goal_id | sentinel -> [project, ...]
let goalProjectsById = {};        // project_id -> project
// Which project lists are open. Held outside the DOM so an expansion
// survives the full re-render that follows every move.
const _goalsExpanded = new Set();

async function goalsInit() {
    await goalsLoad();
    goalsSetupFilters();
    goalsSetupDetailPanel();
    goalsUpdateInboxBadge();
    // #343 touch drag. Registered on the document, not the chip: a
    // finger that leaves the element still has to be tracked.
    // touchmove must be non-passive because it preventDefaults to stop
    // the page scrolling under the drag.
    document.addEventListener("touchmove", onGoalsTouchMove,
                              { passive: false });
    document.addEventListener("touchend", onGoalsTouchEnd);
}

async function goalsLoad() {
    goalsData = await apiFetch("/api/goals?is_active=all");
    // #343 added the projects fetch. Run it alongside tasks rather than
    // making the page wait for a third serial round-trip.
    //
    // Active projects only: an archived project sitting under a goal is
    // noise, and /projects is where archived ones are managed (#24).
    const [tasks, projects] = await Promise.all([
        apiFetch("/api/tasks"),
        apiFetch("/api/projects"),
    ]);
    goalTasks = {};
    for (const task of tasks) {
        if (task.goal_id) {
            if (!goalTasks[task.goal_id]) goalTasks[task.goal_id] = [];
            goalTasks[task.goal_id].push(task);
        }
    }

    // #343: projects bucketed by their goal, plus the goal-less bucket
    // under the _GOALS_NO_GOAL sentinel — that bucket is what the "No
    // goal" zone renders, and without it a goal-less project would be
    // invisible on this page and impossible to drag anywhere.
    goalProjectsById = {};
    goalProjects = {};
    for (const p of projects) {
        goalProjectsById[p.id] = p;
        const key = p.goal_id || _GOALS_NO_GOAL;
        if (!goalProjects[key]) goalProjects[key] = [];
        goalProjects[key].push(p);
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

        // #275: cards flow in a responsive grid (.goals-card-grid) so wide
        // desktops show 2–5 cards per row instead of one stretched card.
        const grid = document.createElement("div");
        grid.className = "goals-card-grid";
        for (const goal of catGoals) {
            grid.appendChild(goalCardEl(goal));
        }
        section.appendChild(grid);
        board.appendChild(section);
    }

    if (filtered.length === 0) {
        board.innerHTML = '<p class="empty-goals">No goals match the current filters.</p>';
    }

    // #343: the "No goal" zone, rendered last so it reads as a holding
    // area rather than a sixth category. It is appended AFTER the
    // empty-state branch above on purpose — that branch replaces the
    // board's contents, and the zone has to survive it. With no zone
    // there is nothing to drag a project out TO, and a goal-less
    // project never appears on this page at all, so the obvious first
    // move ("file this project under a goal") would be impossible.
    board.appendChild(goalsUnassignedZoneEl());
}

function goalsFiltered() {
    // #349: the archive filter replaces a hard-coded `g.is_active`.
    // That hard filter, plus a "Delete" button that only archived, is
    // what made a deleted goal unreachable from the UI forever.
    const archEl = document.getElementById("filterArchived");
    let goals = window.goalArchiveHelpers.goalArchiveFilter(
        goalsData, archEl ? archEl.value : "active");

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

    // #343: the whole CARD is the project drop target, not the project
    // list inside it. That is what makes the recorded decision work —
    // a collapsed card still accepts a drop, so you never have to
    // expand a goal just to file something under it.
    card.dataset.goalId = goal.id;
    card.addEventListener("dragover", onGoalCardDragOver);
    card.addEventListener("dragleave", onGoalCardDragLeave);
    card.addEventListener("drop", onGoalCardDrop);

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

    // #349: an archived goal is only visible under the Archived/All
    // filter, but once it IS on screen it has to be distinguishable —
    // otherwise "All" renders live and dead goals identically.
    if (goal.is_active === false) {
        const archBadge = document.createElement("span");
        archBadge.className = "badge badge-archived";
        archBadge.textContent = "Archived";
        badges.appendChild(archBadge);
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

    // #343: linked projects, collapsed behind a count by default.
    card.appendChild(goalProjectListEl(_goalsProjectsFor(goal.id), goal.id));

    return card;
}

// --- Filters -----------------------------------------------------------------

function goalsSetupFilters() {
    [
        "filterCategory", "filterPriority", "filterStatus", "filterQuarter",
        "filterArchived",                                       // #349
    ].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener("change", goalsRender);
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
    document.getElementById("goalDelete")
        .addEventListener("click", goalDetailToggleArchive);
    document.getElementById("goalHardDelete")
        .addEventListener("click", goalDetailHardDelete);   // #349
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
    // A goal that does not exist yet can be neither archived nor deleted.
    document.getElementById("goalDangerZone").style.display = "none";
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
    const toggle = document.getElementById("goalDelete");
    toggle.style.display = "";
    // #349: the label follows the goal's state rather than lying about it.
    toggle.textContent = window.goalArchiveHelpers.goalArchiveToggleLabel(goal);
    document.getElementById("goalDangerZone").style.display = "";
    _goalRefreshHardDeleteState(goal);

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

// #349: this button used to say "Delete" and silently archive. It is
// the same request — DELETE /api/goals/<id> is a soft delete and always
// was — but it now says what it does, and it toggles back.
async function goalDetailToggleArchive() {
    const id = document.getElementById("goalId").value;
    if (!id) return;
    const goal = goalsData.find((g) => g.id === id);
    if (!goal) return;

    if (goal.is_active === false) {
        // Unarchive. PATCH rather than DELETE — there is no "undelete".
        await apiFetch(`/api/goals/${id}`, {
            method: "PATCH",
            body: JSON.stringify({ is_active: true }),
        });
    } else {
        await apiFetch(`/api/goals/${id}`, { method: "DELETE" });
    }
    await goalsLoad();
    goalDetailClose();
}

// The real delete. Gated on state rather than guarded by a scary
// dialog: the goal must already be archived, and nothing may still
// point at it. `goalDetailOpen` has already resolved both and set the
// button's disabled state, so reaching here means the server agreed
// when we asked — but it checks again, because the data can change
// between opening the panel and clicking.
async function goalDetailHardDelete() {
    const id = document.getElementById("goalId").value;
    if (!id) return;
    const goal = goalsData.find((g) => g.id === id);
    const h = window.goalArchiveHelpers;
    if (!confirm(h.goalHardDeleteConfirm(goal))) return;

    try {
        await apiFetch(`/api/goals/${id}/permanent`, { method: "DELETE" });
    } catch (err) {
        // A 409 means something started pointing at it since the panel
        // opened. Re-resolve rather than leaving a stale hint on screen.
        console.error("Permanent delete refused:", err);
        alert("Could not delete this goal: " + err.message);
        await _goalRefreshHardDeleteState(goal);
        return;
    }
    await goalsLoad();
    goalDetailClose();
}

// Resolve the permanent-delete button's state for `goal`. Null
// references mean "not counted yet", which the helper renders as a
// disabled button rather than an enabled one.
async function _goalRefreshHardDeleteState(goal) {
    const btn = document.getElementById("goalHardDelete");
    const hint = document.getElementById("goalHardDeleteHint");
    if (!btn || !hint) return;
    const h = window.goalArchiveHelpers;

    const paint = (state) => {
        btn.disabled = !state.enabled;
        hint.textContent = state.hint;
    };
    paint(h.goalHardDeleteState(goal, null));
    if (!goal || !goal.id) return;

    let refs = null;
    try {
        refs = await apiFetch(`/api/goals/${goal.id}/references`);
    } catch (err) {
        // Leave it disabled and say so; an unreachable count must not
        // read as "nothing points at this".
        console.error("Could not load goal references:", err);
        hint.textContent = "Could not check what points at this goal.";
        return;
    }
    // The panel may have been closed or moved on while that was in
    // flight — only paint if this is still the goal on screen.
    if (document.getElementById("goalId").value !== goal.id) return;
    paint(h.goalHardDeleteState(goal, refs));
}

function goalsUpdateInboxBadge() {
    // Handled inside goalsLoad()
}

// --- Boot --------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", goalsInit);

// --- #343: drag a project from one goal to another ---------------------------
//
// Decision logic is pure in static/goal_project_drag_helpers.js; this is
// the DOM wiring only. Three things about this screen are worth knowing
// before changing any of it:
//
//   * the goal CARD carries the click handler that opens the detail
//     panel, so everything interactive added inside it has to
//     stopPropagation or clicking a project chip edits the goal;
//   * the card, not the project list, is the drop target — a collapsed
//     card accepts a drop, which is the whole point of the recorded
//     "collapsed count, expand to drag" decision;
//   * the "No goal" zone is a first-class target carrying the
//     _GOALS_NO_GOAL sentinel. A non-empty sentinel rather than "" is
//     deliberate: the shared hit-test skips falsy ids, so an
//     empty-string dataset value would make the zone untouchable on
//     mobile.

const DEFAULT_GOAL_PROJECT_COLOR = "#3b82f6";

function _goalsProjectsFor(goalId) {
    return goalProjects[goalId || _GOALS_NO_GOAL] || [];
}

function _goalsProjectById(id) {
    return goalProjectsById[id] || null;
}

// Resolves a drop-target element to what the decision helper expects:
// a goal object, `null` for the No-goal zone, or `undefined` for "not
// a drop target". The three-way return is load-bearing — the helper
// treats null as unassign and undefined as a bug.
function _goalsTargetForId(id) {
    if (!id) return undefined;
    if (id === _GOALS_NO_GOAL) return null;
    return goalsData.find((g) => g.id === id) || undefined;
}

function _goalsTargetForEl(el) {
    if (!el || !el.dataset) return undefined;
    return _goalsTargetForId(el.dataset.goalId);
}

// A refused drop is otherwise indistinguishable from "drag-and-drop is
// broken", so say why. Cleared on the next drag.
function goalsDragStatus(msg) {
    const el = document.getElementById("goalsDragStatus");
    if (!el) return;
    if (!msg) {
        el.textContent = "";
        el.hidden = true;
        return;
    }
    el.textContent = msg;
    el.hidden = false;
}

const _GOAL_DROP_REFUSAL_TEXT = {
    "archived-project": (project) =>
        `"${project.name}" is archived — restore it on the Projects page ` +
        `before filing it under a goal.`,
    "archived-goal": (project, goal) =>
        `"${goal.title}" is archived — restore it before moving projects in.`,
};

function _goalDecide(project, goal) {
    const h = window.goalProjectDragHelpers;
    if (!h) {
        return {
            allowed: false, reason: "no-project",
            newGoalId: null, unassign: false,
        };
    }
    return h.goalProjectDropDecision(project, goal);
}

// The collapsible project list. Shared by the goal cards and the "No
// goal" zone so the two cannot drift apart.
function goalProjectListEl(projects, key) {
    const wrap = document.createElement("div");
    wrap.className = "goal-card-projects";

    if (projects.length === 0) {
        const none = document.createElement("span");
        none.className = "progress-label muted";
        none.textContent = key === _GOALS_NO_GOAL
            ? "Every project is filed under a goal."
            : "No projects linked";
        wrap.appendChild(none);
        return wrap;
    }

    const list = document.createElement("ul");
    list.className = "goal-card-project-list";
    list.id = "goalProjectList-" + key;

    for (const p of projects) {
        const li = document.createElement("li");
        li.className = "goal-card-project";
        li.dataset.projectId = p.id;
        li.title = p.name;

        const dot = document.createElement("span");
        dot.className = "goal-card-project-dot";
        // Assigned through the CSSOM, not an inline style string: an
        // invalid value is simply dropped, and the server validates the
        // field to hex anyway (project_service._parse_color).
        dot.style.background = p.color || DEFAULT_GOAL_PROJECT_COLOR;
        li.appendChild(dot);

        const name = document.createElement("span");
        name.className = "goal-card-project-name";
        name.textContent = p.name;
        li.appendChild(name);

        // Without this, clicking a chip opens the GOAL editor.
        li.addEventListener("click", (e) => e.stopPropagation());

        li.draggable = true;
        li.addEventListener("dragstart", onGoalProjectDragStart);
        li.addEventListener("dragend", onGoalProjectDragEnd);
        li.addEventListener("touchstart", onGoalProjectTouchStart,
                            { passive: true });

        list.appendChild(li);
    }

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "goal-card-projects-toggle";
    toggle.setAttribute("aria-controls", list.id);

    const setOpen = (open) => {
        list.hidden = !open;
        toggle.textContent = (open ? "▾ " : "▸ ") + `Projects (${projects.length})`;
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
    };

    toggle.addEventListener("click", (e) => {
        e.stopPropagation();           // don't open the goal detail panel
        const open = list.hidden;
        if (open) _goalsExpanded.add(key);
        else _goalsExpanded.delete(key);
        setOpen(open);
    });

    setOpen(_goalsExpanded.has(key));

    wrap.appendChild(toggle);
    wrap.appendChild(list);
    return wrap;
}

function goalsUnassignedZoneEl() {
    const projects = _goalsProjectsFor(_GOALS_NO_GOAL);

    const section = document.createElement("div");
    section.className = "goals-category-section goals-unassigned-section";

    const header = document.createElement("h2");
    header.className = "goals-category-header";
    // Trailing space is load-bearing: the category headers above get
    // theirs from the literal in their template string, and without it
    // this one renders as "No goal2".
    header.textContent = "No goal ";
    const count = document.createElement("span");
    count.className = "tier-count";
    count.textContent = projects.length;
    header.appendChild(count);
    section.appendChild(header);

    // Styled as a card so it is visibly a drop target, but with no
    // click handler — there is no "unassigned goal" to open.
    const zone = document.createElement("div");
    zone.className = "goal-card goals-unassigned-zone";
    zone.dataset.goalId = _GOALS_NO_GOAL;
    zone.addEventListener("dragover", onGoalCardDragOver);
    zone.addEventListener("dragleave", onGoalCardDragLeave);
    zone.addEventListener("drop", onGoalCardDrop);

    const hint = document.createElement("div");
    hint.className = "goal-actions-preview";
    hint.textContent = "Drop a project here to remove it from its goal.";
    zone.appendChild(hint);

    zone.appendChild(goalProjectListEl(projects, _GOALS_NO_GOAL));
    section.appendChild(zone);
    return section;
}

// --- Mouse drag --------------------------------------------------------------

let _dragProject = null;

function onGoalProjectDragStart(e) {
    // The chip sits inside the goal card; stop the event here so no
    // ancestor handler can mistake this for something else.
    e.stopPropagation();
    const id = e.currentTarget.dataset.projectId;
    _dragProject = _goalsProjectById(id);
    e.currentTarget.classList.add("dragging");
    goalsDragStatus("");
    if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", id || "");
    }
}

function onGoalProjectDragEnd(e) {
    e.stopPropagation();
    e.currentTarget.classList.remove("dragging");
    _dragProject = null;
    _goalsClearDropMarks();
}

function _goalsClearDropMarks() {
    document.querySelectorAll(".goal-card-drop-ok, .goal-card-drop-no")
        .forEach((el) => {
            el.classList.remove("goal-card-drop-ok");
            el.classList.remove("goal-card-drop-no");
        });
}

// A no-op drop (the card it came from, or No-goal for a project that
// already has none) gets no red outline — refusing something the user
// has not actually done wrong is just noise.
function _goalsIsNoOp(reason) {
    return reason === "same-goal" || reason === "already-unassigned";
}

function onGoalCardDragOver(e) {
    if (!_dragProject) return;
    const el = e.currentTarget;
    const target = _goalsTargetForEl(el);
    if (target === undefined) return;
    const d = _goalDecide(_dragProject, target);
    if (d.allowed) {
        // preventDefault is what actually makes this a drop target.
        e.preventDefault();
        e.stopPropagation();
        if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
        el.classList.add("goal-card-drop-ok");
    } else if (!_goalsIsNoOp(d.reason)) {
        // No preventDefault: the browser shows the no-drop cursor for
        // free, and the class paints the refusal.
        el.classList.add("goal-card-drop-no");
    }
}

function onGoalCardDragLeave(e) {
    if (!_dragProject) return;
    const el = e.currentTarget;
    // dragleave also fires when the cursor crosses into a CHILD of the
    // card; ignore those or the highlight flickers away mid-hover.
    if (e.relatedTarget && el.contains(e.relatedTarget)) return;
    el.classList.remove("goal-card-drop-ok");
    el.classList.remove("goal-card-drop-no");
}

async function onGoalCardDrop(e) {
    if (!_dragProject) return;
    const el = e.currentTarget;
    const target = _goalsTargetForEl(el);
    if (target === undefined) return;
    e.preventDefault();
    e.stopPropagation();
    _goalsClearDropMarks();
    const project = _dragProject;
    _dragProject = null;
    await _goalsApplyProjectMove(project, target);
}

// Shared by the mouse drop and the touch end — one PATCH, one set of
// messages, so the two input paths cannot drift apart.
async function _goalsApplyProjectMove(project, goal) {
    const d = _goalDecide(project, goal);
    if (!d.allowed) {
        const explain = _GOAL_DROP_REFUSAL_TEXT[d.reason];
        goalsDragStatus(explain ? explain(project, goal) : "");
        return;
    }
    const h = window.goalProjectDragHelpers;

    try {
        // #350: the server re-points every task on this project, with no
        // status filter. `/api/tasks` returns only ACTIVE by default, so
        // the board's own map would undercount — ask for the real set
        // before quoting a number the user is about to act on.
        //
        // #352: templates cascade too, and `?all=1` is required for the
        // same reason `status=all` is — the server filters on
        // project_id alone, so an inactive template is still re-pointed
        // and still has to be counted. `/api/recurring` takes no
        // project filter, so narrow it here rather than widen the API
        // for one caller.
        const [owned, allRecurring] = await Promise.all([
            apiFetch(
                `/api/tasks?status=all&project_id=${encodeURIComponent(project.id)}`),
            apiFetch("/api/recurring?all=1"),
        ]);
        const recurring = allRecurring.filter((r) => r.project_id === project.id);
        const impact = h.goalProjectCascadeImpact(owned, d.newGoalId, recurring);

        // #351: ask when the user cannot get back what this overwrites.
        // That is NOT the same as "is this a clear" — a project whose
        // tasks sit on several goals collapses them all into one on any
        // drop, and nothing afterwards remembers the spread, because a
        // project stores a single goal_id. A one-goal move is left
        // frictionless: dragging it back restores every task exactly.
        if (h.goalProjectMoveNeedsConfirm(impact)) {
            const titles = {};
            for (const g of goalsData) titles[g.id] = g.title;
            if (!confirm(h.goalProjectConfirmMessage(
                project, goal, impact, titles))) {
                goalsDragStatus(`Left "${project.name}" where it was.`);
                return;
            }
        }

        await apiFetch(`/api/projects/${project.id}`, {
            method: "PATCH",
            body: JSON.stringify(h.goalProjectMovePayload(d.newGoalId)),
        });
        await goalsLoad();             // goalsLoad() re-renders

        // The tasks move with the project now, so the progress bars DO
        // change — the message says what happened to them rather than
        // explaining why nothing did.
        let msg = d.unassign
            ? `Moved "${project.name}" out of its goal.`
            : `Moved "${project.name}" to "${goal.title}".`;
        if (impact.changing > 0 || impact.recurringChanging > 0) {
            const parts = [];
            if (impact.changing > 0) {
                parts.push(impact.changing === 1
                    ? "1 task" : `${impact.changing} tasks`);
            }
            if (impact.recurringChanging > 0) {
                parts.push(impact.recurringChanging === 1
                    ? "1 repeating task"
                    : `${impact.recurringChanging} repeating tasks`);
            }
            const what = parts.join(" and ");
            msg += d.unassign
                ? ` Cleared the goal on ${what}.`
                : ` ${what} moved with it.`;
        }
        goalsDragStatus(msg);
    } catch (err) {
        console.error("Project move failed:", err);
        alert("Could not move the project: " + err.message);
    }
}

// --- #343 mobile: long-press, then drag --------------------------------------
//
// HTML5 drag-and-drop does not fire from a finger — no dragstart, no
// dragover, no drop — so touch needs its own path or this feature simply
// would not exist on the phone. The GESTURE is deliberately identical to
// the board's and to /projects' (500ms hold + a haptic tick) so all
// three screens feel the same in the hand.

let _goalTouchDrag = null;      // { li, project, startY }
let _goalTouchLongPress = null;
let _goalTouchStart = { x: 0, y: 0 };

function _goalsTouchTargets() {
    return Array.from(document.querySelectorAll("[data-goal-id]")).map((el) => ({
        id: el.dataset.goalId, rect: el.getBoundingClientRect(), el: el,
    }));
}

function onGoalProjectTouchStart(e) {
    const li = e.currentTarget;
    const t = e.touches[0];
    if (!t) return;
    _goalTouchStart = { x: t.clientX, y: t.clientY };
    _goalTouchLongPress = setTimeout(function () {
        _goalTouchLongPress = null;
        const project = _goalsProjectById(li.dataset.projectId);
        if (!project) return;
        // Read the stored coords, not the Touch object — it may be
        // recycled by the time this fires.
        _goalTouchDrag = { li: li, project: project, startY: _goalTouchStart.y };
        _dragProject = project;        // share the decision path with the mouse
        li.classList.add("dragging");
        if (navigator.vibrate) navigator.vibrate(50);
        goalsDragStatus(`Moving "${project.name}" — drop it on a goal.`);
    }, 500);
}

function onGoalsTouchMove(e) {
    if (_goalTouchLongPress) {
        // Same 10px jitter tolerance as the board: a hold that drifts is
        // still a hold, but a scroll is not a drag.
        const t = e.touches[0];
        if (!t) return;
        const dx = t.clientX - _goalTouchStart.x;
        const dy = t.clientY - _goalTouchStart.y;
        if (Math.sqrt(dx * dx + dy * dy) > 10) {
            clearTimeout(_goalTouchLongPress);
            _goalTouchLongPress = null;
        }
        return;
    }
    if (!_goalTouchDrag) return;
    e.preventDefault();               // stop the page scrolling under the drag
    const t = e.touches[0];
    if (!t) return;
    _goalTouchDrag.li.style.transform =
        "translateY(" + (t.clientY - _goalTouchDrag.startY) + "px)";
    _goalTouchDrag.li.style.zIndex = "9999";
    _goalsClearDropMarks();
    const targets = _goalsTouchTargets();
    const id = window.projectTaskDragHelpers.cardIdUnderPoint(
        targets, t.clientX, t.clientY);
    if (!id) return;
    const target = targets.find((x) => x.id === id);
    if (!target) return;
    const d = _goalDecide(_goalTouchDrag.project, _goalsTargetForId(id));
    if (d.allowed) target.el.classList.add("goal-card-drop-ok");
    else if (!_goalsIsNoOp(d.reason)) {
        target.el.classList.add("goal-card-drop-no");
    }
}

async function onGoalsTouchEnd(e) {
    if (_goalTouchLongPress) {
        clearTimeout(_goalTouchLongPress);
        _goalTouchLongPress = null;
    }
    if (!_goalTouchDrag) return;
    const li = _goalTouchDrag.li;
    const project = _goalTouchDrag.project;
    li.style.transform = "";
    li.style.zIndex = "";
    li.classList.remove("dragging");
    // Suppress the click the browser synthesises from this touch — on
    // this page that click lands on the goal card and would open the
    // detail panel on top of the drop the user just made.
    if (e.cancelable) e.preventDefault();
    // `touches` is empty at touchend — the release point is in
    // changedTouches.
    const t = (e.changedTouches && e.changedTouches[0]) || null;
    _goalTouchDrag = null;
    _dragProject = null;
    _goalsClearDropMarks();
    if (!t) {
        goalsDragStatus("");
        return;
    }
    const id = window.projectTaskDragHelpers.cardIdUnderPoint(
        _goalsTouchTargets(), t.clientX, t.clientY);
    const target = id ? _goalsTargetForId(id) : undefined;
    if (target === undefined) {
        goalsDragStatus("Dropped outside a goal — nothing moved.");
        return;
    }
    await _goalsApplyProjectMove(project, target);
}
