/**
 * project_task_drag_helpers.js — pure logic for #344: dragging a task
 * from one project card to another on /projects.
 *
 * Dual-export helper (CLAUDE.md anti-pattern #3): the branchy part of
 * the drag lives here so Jest can assert its OUTPUTS, rather than a
 * prod-smoke test string-matching the source. `projects.js` keeps only
 * the DOM wiring.
 *
 * Bug #57 is the reason the payload builder is in here too: a wrong or
 * missing `project_id` raises nothing — the API accepts what it is
 * given — so the payload shape needs a mechanical assertion.
 *
 * Two rules encoded here, both read off the existing code rather than
 * assumed:
 *
 *   TYPE GATE — `taskDetailPopulateProjects` (static/app.js:2871) only
 *   ever offers projects matching the task's own type, and the comment
 *   above it records that accidentally widening that back to all types
 *   was a real user report (2026-05-17), same class as #57. Drag is a
 *   second door onto the same field; it honours the same rule.
 *
 *   GOAL CASCADE — `task_service.update_task` overwrites the task's
 *   goal with the destination project's goal when that project has one
 *   (#77 + the PR24 audit refinement). The drag therefore changes a
 *   field the user never touched, so the decision reports it and the
 *   caller can say so.
 */
"use strict";

/**
 * Should this task be allowed to land on this project, and what else
 * changes if it does?
 *
 * Returns `{ allowed, reason, goalWillChange, newGoalId }`.
 * `reason` is one of: "ok", "no-task", "no-project", "same-project",
 * "type-mismatch", "archived-project".
 */
function projectTaskDropDecision(task, project) {
    var refuse = function (reason) {
        return {
            allowed: false, reason: reason,
            goalWillChange: false, newGoalId: null,
        };
    };

    if (!task || !task.id || !task.type) return refuse("no-task");
    if (!project || !project.id || !project.type) return refuse("no-project");
    if (task.project_id && task.project_id === project.id) {
        return refuse("same-project");
    }
    if (task.type !== project.type) return refuse("type-mismatch");
    // `is_active` is only false on archived projects; treat a missing
    // field as active so a partial payload doesn't block every drop.
    if (project.is_active === false) return refuse("archived-project");

    // The server sets the task's goal from the project's, but only when
    // the project actually has one — a project without a goal preserves
    // whatever goal the task already had.
    var destGoal = project.goal_id || null;
    var goalWillChange = !!destGoal && destGoal !== (task.goal_id || null);

    return {
        allowed: true,
        reason: "ok",
        goalWillChange: goalWillChange,
        newGoalId: destGoal,
    };
}

/**
 * The PATCH body for the move. Deliberately `project_id` and nothing
 * else: including `goal_id` here would win over the server-side #77
 * cascade (`update_task` applies an explicit `goal_id` after the
 * project branch) and pin a stale goal onto the moved task.
 */
function projectTaskMovePayload(projectId) {
    return { project_id: projectId };
}

/**
 * Which project card is under this point?
 *
 * Touch drags have no browser drop target — `dragover` never fires from
 * a finger — so the touch path has to hit-test by hand. Kept pure (it
 * takes rects, not elements) so the geometry is Jest-tested instead of
 * only exercised through a real drag.
 *
 * `targets` is `[{ id, rect: {left, right, top, bottom} }]`. Returns the
 * id of the LAST match, so a card stacked over another (bulk toolbar
 * overlap, sticky headers) resolves to the one painted on top, matching
 * what the finger appears to be over. Returns null when over nothing.
 */
function projectCardIdUnderPoint(targets, x, y) {
    if (!targets || !targets.length) return null;
    var hit = null;
    for (var i = 0; i < targets.length; i++) {
        var t = targets[i];
        if (!t || !t.rect || !t.id) continue;
        var r = t.rect;
        if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) {
            hit = t.id;
        }
    }
    return hit;
}

// `cardIdUnderPoint` is the same function under a card-agnostic name.
// #343 reuses this geometry for goal cards on /goals rather than
// growing a second copy of the hit-test, but calling something named
// `projectCardIdUnderPoint` from the goals page would read as a
// mistake. Both names are exported; the project-specific one stays so
// #344's call sites and tests are untouched.
if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        projectTaskDropDecision, projectTaskMovePayload,
        projectCardIdUnderPoint,
        cardIdUnderPoint: projectCardIdUnderPoint,
    };
} else if (typeof window !== "undefined") {
    window.projectTaskDragHelpers = {
        projectTaskDropDecision: projectTaskDropDecision,
        projectTaskMovePayload: projectTaskMovePayload,
        projectCardIdUnderPoint: projectCardIdUnderPoint,
        cardIdUnderPoint: projectCardIdUnderPoint,
    };
}
