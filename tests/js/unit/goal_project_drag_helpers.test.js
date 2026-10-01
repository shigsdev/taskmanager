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
 * 3. THE TASKS CASCADE WITH IT (#350). `update_project` re-points
 *    every task on the project. When #343 shipped it did not, and that
 *    was a gap rather than a design: #77's recorded user decision is
 *    "always overwrite + go back and update any missing" (quoted in
 *    scripts/backfill_task_goal_from_project.py), `update_task` had
 *    honoured it all along, and the repo shipped TWO tools to repair
 *    the resulting drift. `delete_project`'s "the goal is independent
 *    intent" covers deletion only — where nulling a task's goal because
 *    its project vanished would be data loss — and does not extend to
 *    a project being moved.
 *
 *    The count matters because `/api/tasks` returns ACTIVE only by
 *    default while the server cascades with no status filter, so the
 *    caller must pass the `status=all` set or it will understate the
 *    blast radius in exactly the direction that clears data.
 */
"use strict";

const {
    goalProjectDropDecision,
    goalProjectMovePayload,
    goalProjectCascadeCount,
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

// --- The cascade count: what the move WILL do -----------------------------

describe("goalProjectCascadeCount — the number the user acts on", () => {
    // Deliberately includes an archived and a cancelled task: the server
    // cascades with no status filter, so counting only active ones would
    // under-report a clear. These are the rows /api/tasks hides by
    // default, which is the whole reason the caller asks for status=all.
    const tasks = [
        { id: "t1", status: "active", goal_id: "g1" },
        { id: "t2", status: "archived", goal_id: "g1" },
        { id: "t3", status: "active", goal_id: null },
        { id: "t4", status: "cancelled", goal_id: "g2" },
    ];

    test("counts every task whose goal will change", () => {
        // Moving to g2: t1, t2 (g1 -> g2) and t3 (null -> g2) change.
        // t4 is already on g2.
        expect(goalProjectCascadeCount(tasks, "g2")).toBe(3);
    });

    test("a task already on the destination is not counted", () => {
        // Moving to g1: only t3 (null) and t4 (g2) change.
        expect(goalProjectCascadeCount(tasks, "g1")).toBe(2);
    });

    test("unassigning counts every task that HAS a goal — the ones cleared", () => {
        expect(goalProjectCascadeCount(tasks, null)).toBe(3);   // t1, t2, t4
    });

    test("archived and cancelled tasks ARE counted", () => {
        // The server does not filter by status, so neither does this. A
        // completed task left behind would make the goal's own
        // completed-count wrong.
        const hidden = [
            { id: "a", status: "archived", goal_id: "g1" },
            { id: "c", status: "cancelled", goal_id: "g1" },
        ];
        expect(goalProjectCascadeCount(hidden, null)).toBe(2);
    });

    test("nothing to change is zero, so no confirm is raised", () => {
        const aligned = [
            { id: "t1", status: "active", goal_id: "g2" },
            { id: "t2", status: "active", goal_id: "g2" },
        ];
        expect(goalProjectCascadeCount(aligned, "g2")).toBe(0);
    });

    test("a project with no tasks is zero, not a crash", () => {
        expect(goalProjectCascadeCount([], "g2")).toBe(0);
        expect(goalProjectCascadeCount(null, "g2")).toBe(0);
        expect(goalProjectCascadeCount(undefined, null)).toBe(0);
    });

    test("undefined and empty-string goals are treated as no goal", () => {
        // A task carrying goal_id: "" must not read as a real goal and
        // inflate the count the confirm quotes.
        const odd = [
            { id: "t1", status: "active" },
            { id: "t2", status: "active", goal_id: "" },
        ];
        expect(goalProjectCascadeCount(odd, null)).toBe(0);
        expect(goalProjectCascadeCount(odd, "g1")).toBe(2);
    });
});
