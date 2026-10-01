/**
 * Jest tests for the #343 goal-card project-drag decision + payload.
 *
 * Written BEFORE the implementation, per bug #57's rule: a
 * goal-assignment bug does NOT raise — `update_project` accepts
 * whatever `goal_id` it is handed — so a dropped or wrong id is
 * silent. The payload assertion is the only thing that catches it.
 *
 * Three non-obvious rules are pinned here, all three read off the
 * existing code rather than guessed:
 *
 * 1. NO TYPE/CATEGORY GATE — and this is the OPPOSITE of #344.
 *    `populateGoalDropdown` (static/projects.js:639) offers EVERY
 *    active goal for any project, with no filter on project.type vs
 *    goal.category, and the bulk-edit goal menu agrees. The two enums
 *    are not even parallel (ProjectType is work|personal; GoalCategory
 *    is health|personal_growth|relationships|work|bau), so there is no
 *    pairing to enforce — a `work` project legitimately serves a
 *    `personal_growth` goal. #344 added a type gate because the task
 *    panel's picker HAD one and drag would have been a hole in it;
 *    here a gate would make drag STRICTER than the picker, which is
 *    the same inconsistency pointing the other way.
 *
 * 2. `goal === null` IS A REAL TARGET, not a missing argument. It is
 *    the "No goal" zone, and it is the only way to drag a project back
 *    OUT of a goal. Without it the feature is one-way.
 *
 * 3. NO TASK CASCADE. `update_project` (project_service.py:217) sets
 *    `project.goal_id` and stops — it does not touch the tasks. That
 *    is deliberate: `delete_project` documents the principle as "the
 *    goal is independent intent". But `goal_progress_batch`
 *    (goal_service.py:197) counts tasks by `Task.goal_id` ALONE and
 *    never traverses Project -> Goal, so after a move the project sits
 *    under the new goal while its tasks still count toward the old
 *    one. The progress bars do not move. That is a real user-visible
 *    consequence of a correct design, so it gets counted and said out
 *    loud rather than left to be discovered.
 */
"use strict";

const {
    goalProjectDropDecision,
    goalProjectMovePayload,
    goalProjectMoveSideEffects,
} = require("../../../static/goal_project_drag_helpers");

const goalA = { id: "g1", title: "Land the DTCC role", category: "work", is_active: true };
const goalB = { id: "g2", title: "Get fit", category: "health", is_active: true };
const archivedGoal = { id: "g3", title: "Old goal", category: "work", is_active: false };

const projInA = { id: "p1", name: "Exit JPMC", type: "work", is_active: true, goal_id: "g1" };
const projLoose = { id: "p2", name: "Reading", type: "personal", is_active: true, goal_id: null };
const archivedProj = { id: "p3", name: "Old", type: "work", is_active: false, goal_id: "g1" };

// --- The payload: bug #57's lesson -----------------------------------------

describe("goalProjectMovePayload — the field must survive (bug #57)", () => {
    test("sends goal_id and nothing else", () => {
        expect(goalProjectMovePayload("g2")).toEqual({ goal_id: "g2" });
    });

    test("only one key, so no neighbouring field is overwritten", () => {
        expect(Object.keys(goalProjectMovePayload("g2"))).toEqual(["goal_id"]);
    });

    test("null unassigns rather than being omitted", () => {
        // `{}` would be a no-op PATCH — update_project only acts on keys
        // that are PRESENT, so an omitted goal_id leaves the old one.
        expect(goalProjectMovePayload(null)).toEqual({ goal_id: null });
        expect("goal_id" in goalProjectMovePayload(null)).toBe(true);
    });

    test("undefined and empty string normalise to null, not to garbage", () => {
        expect(goalProjectMovePayload(undefined)).toEqual({ goal_id: null });
        expect(goalProjectMovePayload("")).toEqual({ goal_id: null });
    });
});

// --- The decision ----------------------------------------------------------

describe("goalProjectDropDecision — moving between goals", () => {
    test("a project moves to a different goal", () => {
        const d = goalProjectDropDecision(projInA, goalB);
        expect(d.allowed).toBe(true);
        expect(d.reason).toBe("ok");
        expect(d.newGoalId).toBe("g2");
        expect(d.unassign).toBe(false);
    });

    test("a goal-less project can be filed under a goal", () => {
        const d = goalProjectDropDecision(projLoose, goalA);
        expect(d.allowed).toBe(true);
        expect(d.newGoalId).toBe("g1");
    });

    test("dropping on the goal it already has is refused as a no-op", () => {
        const d = goalProjectDropDecision(projInA, goalA);
        expect(d.allowed).toBe(false);
        expect(d.reason).toBe("same-goal");
    });

    test("an archived project is refused", () => {
        const d = goalProjectDropDecision(archivedProj, goalB);
        expect(d.allowed).toBe(false);
        expect(d.reason).toBe("archived-project");
    });

    test("an archived goal is refused as a destination", () => {
        const d = goalProjectDropDecision(projInA, archivedGoal);
        expect(d.allowed).toBe(false);
        expect(d.reason).toBe("archived-goal");
    });

    test("a missing project or goal is refused, not thrown", () => {
        expect(goalProjectDropDecision(null, goalA).reason).toBe("no-project");
        expect(goalProjectDropDecision(undefined, goalA).reason).toBe("no-project");
        expect(goalProjectDropDecision({ name: "x" }, goalA).reason).toBe("no-project");
        expect(goalProjectDropDecision(projInA, undefined).reason).toBe("no-goal");
        expect(goalProjectDropDecision(projInA, { title: "x" }).reason).toBe("no-goal");
    });

    test("a refusal never reports a destination", () => {
        for (const d of [
            goalProjectDropDecision(projInA, goalA),
            goalProjectDropDecision(archivedProj, goalB),
            goalProjectDropDecision(projInA, archivedGoal),
            goalProjectDropDecision(null, goalA),
        ]) {
            expect(d.allowed).toBe(false);
            expect(d.newGoalId).toBeNull();
            expect(d.unassign).toBe(false);
        }
    });

    test("a project with no is_active field is treated as active", () => {
        // A partial payload must not silently block every drop.
        const partial = { id: "p9", name: "New", type: "work", goal_id: null };
        expect(goalProjectDropDecision(partial, goalA).allowed).toBe(true);
    });
});

// --- The type/category question, answered the other way from #344 ----------

describe("no type/category gate — drag must not out-restrict the picker", () => {
    test("a work project may be dropped on a health goal", () => {
        const workProj = { id: "p4", type: "work", is_active: true, goal_id: null };
        expect(goalProjectDropDecision(workProj, goalB).allowed).toBe(true);
    });

    test("a personal project may be dropped on a work goal", () => {
        const personalProj = { id: "p5", type: "personal", is_active: true, goal_id: null };
        expect(goalProjectDropDecision(personalProj, goalA).allowed).toBe(true);
    });

    test("every ProjectType x GoalCategory pairing is allowed", () => {
        // populateGoalDropdown offers all of them; so does bulk edit. If
        // a future change adds a gate here, it has to change the picker
        // in the same commit or the two doors disagree.
        const categories = ["health", "personal_growth", "relationships", "work", "bau"];
        for (const type of ["work", "personal"]) {
            for (const category of categories) {
                const p = { id: "px", type: type, is_active: true, goal_id: null };
                const g = { id: "gx", category: category, is_active: true };
                expect(goalProjectDropDecision(p, g).allowed).toBe(true);
            }
        }
    });

    test("a project with no type at all is still allowed", () => {
        // Nothing reads project.type on this path, so a payload missing
        // it must not be refused for the wrong reason.
        const noType = { id: "p6", is_active: true, goal_id: null };
        expect(goalProjectDropDecision(noType, goalA).allowed).toBe(true);
    });
});

// --- The "No goal" zone: the way back out ----------------------------------

describe("the unassign zone — without it the drag is one-way", () => {
    test("dropping a filed project on the No-goal zone unassigns it", () => {
        const d = goalProjectDropDecision(projInA, null);
        expect(d.allowed).toBe(true);
        expect(d.reason).toBe("ok");
        expect(d.unassign).toBe(true);
        expect(d.newGoalId).toBeNull();
    });

    test("its payload nulls the goal", () => {
        const d = goalProjectDropDecision(projInA, null);
        expect(goalProjectMovePayload(d.newGoalId)).toEqual({ goal_id: null });
    });

    test("a project that already has no goal is refused as a no-op", () => {
        const d = goalProjectDropDecision(projLoose, null);
        expect(d.allowed).toBe(false);
        expect(d.reason).toBe("already-unassigned");
    });

    test("an archived project cannot be unassigned by drag either", () => {
        expect(goalProjectDropDecision(archivedProj, null).reason)
            .toBe("archived-project");
    });

    test("null (the zone) and undefined (a bug) are NOT the same", () => {
        // This distinction is the whole reason the zone works. If a
        // future refactor collapses them, an accidental undefined would
        // silently start wiping goal_id.
        expect(goalProjectDropDecision(projInA, null).allowed).toBe(true);
        expect(goalProjectDropDecision(projInA, undefined).allowed).toBe(false);
    });
});

// --- The consequence nobody asked about: progress bars don't move ----------

describe("goalProjectMoveSideEffects — what the move does NOT do", () => {
    const tasks = [
        { id: "t1", status: "active", goal_id: "g1" },
        { id: "t2", status: "archived", goal_id: "g1" },
        { id: "t3", status: "active", goal_id: null },
        { id: "t4", status: "active", goal_id: "g2" },
    ];

    test("counts tasks that will keep counting toward another goal", () => {
        // Moving to g2: t1 + t2 still point at g1, so g1's progress bar
        // keeps counting them while the project sits under g2.
        const s = goalProjectMoveSideEffects(tasks, "g2");
        expect(s.countedElsewhere).toBe(2);
    });

    test("counts tasks that count toward no goal at all", () => {
        expect(goalProjectMoveSideEffects(tasks, "g2").unlinked).toBe(1);
    });

    test("a task already on the destination goal is not a side effect", () => {
        const s = goalProjectMoveSideEffects(tasks, "g1");
        expect(s.countedElsewhere).toBe(1);   // only t4 (g2)
    });

    test("cancelled and deleted tasks are excluded, matching goal_progress", () => {
        // goal_progress_batch excludes CANCELLED from both numerator and
        // denominator and filters DELETED out entirely, so counting them
        // here would overstate what the user sees on the bars.
        const withNoise = tasks.concat([
            { id: "t5", status: "cancelled", goal_id: "g1" },
            { id: "t6", status: "deleted", goal_id: "g1" },
        ]);
        expect(goalProjectMoveSideEffects(withNoise, "g2").countedElsewhere).toBe(2);
    });

    test("unassigning counts every goal-linked task as elsewhere", () => {
        const s = goalProjectMoveSideEffects(tasks, null);
        expect(s.countedElsewhere).toBe(3);   // t1, t2, t4
        expect(s.unlinked).toBe(1);
    });

    test("no tasks is zero, not a crash", () => {
        expect(goalProjectMoveSideEffects([], "g2"))
            .toEqual({ countedElsewhere: 0, unlinked: 0 });
        expect(goalProjectMoveSideEffects(null, "g2"))
            .toEqual({ countedElsewhere: 0, unlinked: 0 });
        expect(goalProjectMoveSideEffects(undefined, null))
            .toEqual({ countedElsewhere: 0, unlinked: 0 });
    });
});
