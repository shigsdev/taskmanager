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
 *
 *   REVERSIBILITY IS THE LINE, NOT DIRECTION (#351) — #350 shipped the
 *   confirm on the CLEAR direction only, and that was the wrong test.
 *   The question that matters is whether the move can be taken back.
 *
 *   Move a project whose tasks all sit on ONE goal and the move is
 *   reversible: drag it back and every task returns to the goal they
 *   shared. Move a project whose tasks sit on SEVERAL goals and the
 *   split is gone for good — dragging back lands all of them on
 *   whichever single goal you drag to, because the server stores one
 *   `goal_id` per project and has nowhere to remember the old spread.
 *   That holds in both directions, so direction was never the right
 *   signal; "is more than one goal being overwritten" is.
 *
 *   This was not hypothetical. On the live data a 394-task catch-all
 *   project sat across four goals while its own `goal_id` was NULL, so
 *   dropping it on any goal card would have rewritten all four at once
 *   — with no dialog at all, because nothing was being cleared.
 *
 *   TEMPLATES COUNT TOO — `RecurringTask` carries its own `goal_id`,
 *   and the spawner stamps it onto every task it creates
 *   (`recurring_service.py:676`), so a template is a goal choice that
 *   keeps paying out. #352 brought them into the server-side cascade;
 *   they are counted here for the same reason tasks are.
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
 * What the server is about to do, in enough detail to warn about it.
 *
 * `tasks` must be EVERY task on the project, not just the active ones:
 * `update_project` cascades with no status filter (matching the
 * backfill), while `/api/tasks` returns only ACTIVE by default.
 * Counting the default list would understate the blast radius in
 * exactly the destructive direction, so the caller fetches
 * `status=all` first. `recurring` is the project's RecurringTask
 * templates, which #352 brought into the same cascade.
 *
 * Returns:
 *   changing          tasks whose goal_id will change
 *   clearing          of those, how many lose a goal entirely
 *   recurringChanging templates whose goal_id will change
 *   fromGoals         [{goalId, count}] — the DISTINCT goals being
 *                     overwritten, biggest first. Rows with no goal
 *                     are absent: they are gaining one, so nothing of
 *                     theirs is destroyed.
 *   flattening        fromGoals.length > 1, i.e. the move cannot be
 *                     undone by dragging the project back.
 */
function goalProjectCascadeImpact(tasks, newGoalId, recurring) {
    var dest = newGoalId || null;
    var changing = 0;
    var clearing = 0;
    var recurringChanging = 0;
    var fromCounts = {};

    var scan = function (rows, isTask) {
        if (!rows || !rows.length) return;
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i];
            if (!row) continue;
            var current = row.goal_id || null;
            if (current === dest) continue;          // already correct
            if (isTask) {
                changing += 1;
                if (current !== null && dest === null) clearing += 1;
            } else {
                recurringChanging += 1;
            }
            // Only a real goal can be destroyed. Going from "no goal"
            // to a goal adds information; it never removes any.
            if (current === null) continue;
            fromCounts[current] = (fromCounts[current] || 0) + 1;
        }
    };
    scan(tasks, true);
    scan(recurring, false);

    var fromGoals = Object.keys(fromCounts).map(function (id) {
        return { goalId: id, count: fromCounts[id] };
    });
    // Biggest first so the dialog leads with the goal that loses most.
    // Ties break on id so the order is deterministic under test.
    fromGoals.sort(function (a, b) {
        if (b.count !== a.count) return b.count - a.count;
        return a.goalId < b.goalId ? -1 : 1;
    });

    return {
        changing: changing,
        clearing: clearing,
        recurringChanging: recurringChanging,
        fromGoals: fromGoals,
        flattening: fromGoals.length > 1,
    };
}

/**
 * Does this move need a confirm?
 *
 * Two cases, one reason — the user cannot get back what it overwrites:
 *   clearing > 0   goals are being removed, and there is no undo;
 *   flattening     several goals collapse into one, and the spread is
 *                  unrecoverable even by dragging the project back.
 *
 * A single-goal move is deliberately NOT confirmed. It is what "move
 * the project" plainly means, and dragging it back restores every task
 * exactly as it was.
 */
function goalProjectMoveNeedsConfirm(impact) {
    if (!impact) return false;
    return impact.clearing > 0 || impact.flattening === true;
}

function _gpCount(n, one, many) {
    return n === 1 ? "1 " + one : n + " " + many;
}

/**
 * The confirm() text.
 *
 * Pure, so the copy itself is under test. That matters more here than
 * usual: the dialog's whole job is to state the blast radius, and a
 * count that disagrees with what the server then does is worse than
 * showing no dialog at all.
 *
 * `goalTitles` maps goal id -> title. An id missing from it renders as
 * "a goal you can no longer see" rather than a raw UUID — which is
 * exactly what an overwritten-but-since-archived goal would otherwise
 * look like.
 */
function goalProjectConfirmMessage(project, goal, impact, goalTitles) {
    var titles = goalTitles || {};
    var name = (project && project.name) || "this project";
    var clearing = impact.clearing > 0;

    var head = clearing
        ? 'Take "' + name + '" out of its goal?'
        : 'Move "' + name + '" to "'
            + ((goal && goal.title) || "that goal") + '"?';

    var moved = _gpCount(impact.changing, "task", "tasks");
    if (impact.recurringChanging > 0) {
        moved += " and " + _gpCount(
            impact.recurringChanging, "repeating task", "repeating tasks");
    }
    var body = clearing
        ? "This clears the goal on " + moved + "."
        : "This sets the goal on " + moved + ".";

    if (impact.flattening) {
        var total = 0;
        var i;
        for (i = 0; i < impact.fromGoals.length; i++) {
            total += impact.fromGoals[i].count;
        }
        body += "\n\n" + _gpCount(total, "of them is", "of them are")
            + " on a different goal right now, across "
            + impact.fromGoals.length + " goals. Dragging \"" + name
            + "\" back will NOT restore that split — a project stores "
            + "one goal, so the spread is lost for good:\n";
        for (i = 0; i < impact.fromGoals.length; i++) {
            var row = impact.fromGoals[i];
            body += "\n  " + row.count + "  "
                + (titles[row.goalId] || "a goal you can no longer see");
        }
    } else if (clearing) {
        body += " This cannot be undone.";
    }

    return head + "\n\n" + body;
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        goalProjectDropDecision, goalProjectMovePayload,
        goalProjectCascadeImpact, goalProjectMoveNeedsConfirm,
        goalProjectConfirmMessage,
    };
} else if (typeof window !== "undefined") {
    window.goalProjectDragHelpers = {
        goalProjectDropDecision: goalProjectDropDecision,
        goalProjectMovePayload: goalProjectMovePayload,
        goalProjectCascadeImpact: goalProjectCascadeImpact,
        goalProjectMoveNeedsConfirm: goalProjectMoveNeedsConfirm,
        goalProjectConfirmMessage: goalProjectConfirmMessage,
    };
}
