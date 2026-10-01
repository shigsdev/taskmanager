/**
 * goal_project_drag_helpers.js — pure logic for #343: dragging a project
 * from one goal to another on /goals.
 *
 * Dual-export helper (CLAUDE.md anti-pattern #3): the branchy part of
 * the drag lives here so Jest can assert its OUTPUTS, rather than a
 * prod-smoke test string-matching the source. `goals.js` keeps only the
 * DOM wiring.
 *
 * Bug #57 is why the payload builder is in here too: `update_project`
 * accepts whatever `goal_id` it is handed and raises nothing, so a
 * dropped or wrong id is silent. The payload shape needs a mechanical
 * assertion.
 *
 * The hit-test geometry is NOT duplicated here — `goals.js` reuses
 * `projectTaskDragHelpers.cardIdUnderPoint` from #344, which is pure
 * rect math and card-agnostic. Per the #343 backlog note, the two
 * screens share one implementation rather than growing a second copy.
 *
 * Three rules encoded here, all read off the existing code:
 *
 *   NO TYPE/CATEGORY GATE — the opposite conclusion from #344, and
 *   worth stating because the precedent looks like it should transfer.
 *   `populateGoalDropdown` (static/projects.js:639) offers EVERY active
 *   goal for any project with no type filter, and the bulk-edit goal
 *   menu agrees. The enums are not parallel either — ProjectType is
 *   work|personal, GoalCategory is health|personal_growth|
 *   relationships|work|bau — so there is no pairing to enforce, and a
 *   `work` project serving a `personal_growth` goal is legitimate.
 *   #344 added a type gate because the task panel's picker HAD one and
 *   drag would have been a hole in it. Here a gate would make drag
 *   STRICTER than the picker: the same inconsistency, pointing the
 *   other way.
 *
 *   THE UNASSIGN ZONE — `goal === null` is a real target (the "No goal"
 *   zone), not a missing argument. It is the only way to drag a project
 *   back out of a goal, and without it the whole interaction is
 *   one-way. `undefined` stays an error, so an accidental omission
 *   cannot start silently wiping `goal_id`.
 *
 *   NO TASK CASCADE, AND THE BARS DO NOT MOVE — `update_project`
 *   (project_service.py:217) sets `project.goal_id` and stops.
 *   Deliberately: `delete_project` documents the principle as "the goal
 *   is independent intent". But `goal_progress_batch`
 *   (goal_service.py:197) counts tasks by `Task.goal_id` alone and
 *   never traverses Project -> Goal, so after a move the project sits
 *   under its new goal while its tasks keep counting toward the old
 *   one and neither progress bar changes. That is a real user-visible
 *   consequence of a correct design, so it is counted here and said
 *   out loud by the caller.
 */
"use strict";

/**
 * Should this project be allowed to land on this goal?
 *
 * `goal` may be a goal object, or `null` to mean the "No goal" zone.
 * `undefined` is a caller bug and is refused.
 *
 * Returns `{ allowed, reason, newGoalId, unassign }`. `reason` is one
 * of: "ok", "no-project", "no-goal", "same-goal", "archived-project",
 * "archived-goal", "already-unassigned".
 */
function goalProjectDropDecision(project, goal) {
    var refuse = function (reason) {
        return {
            allowed: false, reason: reason,
            newGoalId: null, unassign: false,
        };
    };

    if (!project || !project.id) return refuse("no-project");
    // `is_active` is only false on archived projects; a missing field
    // means a partial payload, not an archived row, so treat it as
    // active rather than blocking every drop.
    if (project.is_active === false) return refuse("archived-project");

    var current = project.goal_id || null;

    // The "No goal" zone. Checked with `=== null` on purpose: see the
    // UNASSIGN ZONE note above.
    if (goal === null) {
        if (!current) return refuse("already-unassigned");
        return { allowed: true, reason: "ok", newGoalId: null, unassign: true };
    }

    if (!goal || !goal.id) return refuse("no-goal");
    if (goal.is_active === false) return refuse("archived-goal");
    if (current === goal.id) return refuse("same-goal");

    // Deliberately no project.type / goal.category comparison.
    return { allowed: true, reason: "ok", newGoalId: goal.id, unassign: false };
}

/**
 * The PATCH body for the move.
 *
 * `goal_id` is always PRESENT, even when null — `update_project` only
 * acts on keys it finds in the body, so omitting it would make an
 * unassign a silent no-op. Empty string and undefined normalise to
 * null so a blank dataset attribute cannot become a bogus id.
 */
function goalProjectMovePayload(goalId) {
    return { goal_id: goalId || null };
}

/**
 * What the move does NOT do, counted so the caller can say it.
 *
 * `tasks` is the moved project's tasks. Returns
 * `{ countedElsewhere, unlinked }`:
 *
 *   countedElsewhere — tasks whose own `goal_id` is set and is not the
 *   destination. These keep counting toward that other goal's progress
 *   bar while the project sits under the new one.
 *
 *   unlinked — tasks with no goal at all, which count toward nothing.
 *
 * Cancelled and deleted tasks are excluded to match
 * `goal_progress_batch`, which drops DELETED entirely and excludes
 * CANCELLED from both numerator and denominator. Counting them would
 * overstate what the user actually sees on the bars.
 */
function goalProjectMoveSideEffects(tasks, newGoalId) {
    var out = { countedElsewhere: 0, unlinked: 0 };
    if (!tasks || !tasks.length) return out;
    var dest = newGoalId || null;
    for (var i = 0; i < tasks.length; i++) {
        var t = tasks[i];
        if (!t) continue;
        if (t.status !== "active" && t.status !== "archived") continue;
        var g = t.goal_id || null;
        if (!g) out.unlinked += 1;
        else if (g !== dest) out.countedElsewhere += 1;
    }
    return out;
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        goalProjectDropDecision, goalProjectMovePayload,
        goalProjectMoveSideEffects,
    };
} else if (typeof window !== "undefined") {
    window.goalProjectDragHelpers = {
        goalProjectDropDecision: goalProjectDropDecision,
        goalProjectMovePayload: goalProjectMovePayload,
        goalProjectMoveSideEffects: goalProjectMoveSideEffects,
    };
}
