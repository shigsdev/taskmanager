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
 *   THE TASKS COME WITH IT (#350) — `update_project` cascades the new
 *   goal onto every task on the project. This was NOT true when #343
 *   shipped, and the gap was mine: I read `delete_project`'s "the goal
 *   is independent intent" as the governing principle when it only
 *   covers DELETION, where nulling a task's goal because its project
 *   vanished would be data loss. The actual rule is #77's recorded
 *   user decision — "always overwrite + go back and update any
 *   missing" — which `update_task` had honoured all along while
 *   `update_project` had not. Two repair tools existed for the
 *   resulting drift, which is the drift being a bug.
 *
 *   Unassigning CLEARS the tasks' goals, by the user's call. That is
 *   not the PR24 "silent data loss" case: PR24 was about assigning a
 *   task to a project that incidentally has no goal, where the goal is
 *   not what you were touching. Clearing a project's goal is a direct
 *   statement about that goal. Because it is destructive and has no
 *   undo, the caller confirms first with an exact count.
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
 * How many of the project's tasks the server will re-point, so the
 * caller can say it — and, when the destination is "no goal", warn
 * BEFORE doing it.
 *
 * `tasks` must be EVERY task on the project, not just the active ones:
 * `update_project` cascades with no status filter (matching the
 * backfill), while `/api/tasks` returns only ACTIVE by default. Counting
 * the default list would understate the blast radius in exactly the
 * destructive direction, so the caller fetches `status=all` first.
 *
 * Returns the count of tasks whose goal will change. When the move is
 * an unassign, every one of those is a goal being CLEARED, which is the
 * number worth confirming against.
 */
function goalProjectCascadeCount(tasks, newGoalId) {
    if (!tasks || !tasks.length) return 0;
    var dest = newGoalId || null;
    var n = 0;
    for (var i = 0; i < tasks.length; i++) {
        var t = tasks[i];
        if (!t) continue;
        if ((t.goal_id || null) !== dest) n += 1;
    }
    return n;
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        goalProjectDropDecision, goalProjectMovePayload,
        goalProjectCascadeCount,
    };
} else if (typeof window !== "undefined") {
    window.goalProjectDragHelpers = {
        goalProjectDropDecision: goalProjectDropDecision,
        goalProjectMovePayload: goalProjectMovePayload,
        goalProjectCascadeCount: goalProjectCascadeCount,
    };
}
