/**
 * Jest tests for the #344 project-card task-drag decision + payload.
 *
 * Written BEFORE the implementation, per bug #57's rule: a
 * project-assignment bug does NOT raise — the API happily accepts
 * whatever it is handed, so a dropped or wrong `project_id` is silent.
 * The payload assertion is the only thing that catches it.
 *
 * Two non-obvious rules are pinned here, both discovered by reading
 * the code rather than guessing:
 *
 * 1. TYPE GATE. The task detail panel only ever offers projects of the
 *    task's own type (`static/app.js:2871`), and the comment above it
 *    records that widening this back to all types was a real user
 *    report on 2026-05-17 — the same single-type bug class as #57.
 *    Drag-and-drop is a second door onto the same field, so it has to
 *    honour the same rule or it becomes the hole the picker closed.
 *
 * 2. GOAL CASCADE. `task_service.update_task` overwrites the task's
 *    goal with the destination project's goal whenever that project
 *    HAS one (#77 + the PR24 audit refinement). A drag therefore has a
 *    side effect on a field the user never touched, so the decision
 *    reports it and the UI can say so out loud.
 */
"use strict";

const {
    projectTaskDropDecision,
    projectTaskMovePayload,
    projectCardIdUnderPoint,
    taskLineClickOpens,
} = require("../../../static/project_task_drag_helpers");

const workTask = { id: "t1", title: "Draft plan", type: "work", project_id: "p1" };
const personalTask = { id: "t2", title: "Gym", type: "personal", project_id: "p9" };

const workProjA = { id: "p1", name: "Exit JPMC", type: "work", is_active: true, goal_id: null };
const workProjB = { id: "p2", name: "Onboard DTCC", type: "work", is_active: true, goal_id: null };
const workProjWithGoal = { id: "p3", name: "Comp", type: "work", is_active: true, goal_id: "g7" };
const personalProj = { id: "p9", name: "Health", type: "personal", is_active: true, goal_id: null };
const archivedProj = { id: "p4", name: "Old", type: "work", is_active: false, goal_id: null };

describe("projectTaskMovePayload — the field must survive (bug #57)", () => {
    test("sends project_id and nothing else", () => {
        expect(projectTaskMovePayload("p2")).toEqual({ project_id: "p2" });
    });

    test("the id is passed through verbatim, not coerced or truncated", () => {
        const uuid = "6f1c2f6a-9b3d-4e77-8a21-0c5d9e4b7f30";
        expect(projectTaskMovePayload(uuid).project_id).toBe(uuid);
    });

    test("never emits goal_id — the server owns the cascade", () => {
        // If the client also sent goal_id it would win over the #77
        // project→goal cascade in update_task and silently pin a stale
        // goal onto the moved task.
        expect(Object.keys(projectTaskMovePayload("p2"))).toEqual(["project_id"]);
    });
});

describe("projectTaskDropDecision — what a drop is allowed to do", () => {
    test("a work task moves between two work projects", () => {
        const d = projectTaskDropDecision(workTask, workProjB);
        expect(d.allowed).toBe(true);
        expect(d.reason).toBe("ok");
    });

    test("dropping on the project it already belongs to is a no-op", () => {
        const d = projectTaskDropDecision(workTask, workProjA);
        expect(d.allowed).toBe(false);
        expect(d.reason).toBe("same-project");
    });

    test("a work task is REFUSED by a personal project", () => {
        // Matches the detail-panel picker. Without this, drag-and-drop
        // is a back door onto a field the picker deliberately fences.
        const d = projectTaskDropDecision(workTask, personalProj);
        expect(d.allowed).toBe(false);
        expect(d.reason).toBe("type-mismatch");
    });

    test("a personal task is REFUSED by a work project", () => {
        const d = projectTaskDropDecision(personalTask, workProjB);
        expect(d.allowed).toBe(false);
        expect(d.reason).toBe("type-mismatch");
    });

    test("an archived project refuses the drop", () => {
        const d = projectTaskDropDecision(workTask, archivedProj);
        expect(d.allowed).toBe(false);
        expect(d.reason).toBe("archived-project");
    });

    test("missing task or project is refused, not crashed", () => {
        expect(projectTaskDropDecision(null, workProjB).allowed).toBe(false);
        expect(projectTaskDropDecision(workTask, null).allowed).toBe(false);
        expect(projectTaskDropDecision(undefined, undefined).allowed).toBe(false);
        expect(projectTaskDropDecision({}, {}).allowed).toBe(false);
    });

    test("a task with no project at all can be dropped onto one", () => {
        // Not reachable from the board today (the card lists only its
        // own tasks) but the decision must not depend on project_id
        // being set — #343 will drag across goals with the same helper.
        const orphan = { id: "t3", title: "Loose", type: "work", project_id: null };
        expect(projectTaskDropDecision(orphan, workProjB).allowed).toBe(true);
    });
});

describe("projectTaskDropDecision — the goal cascade is reported", () => {
    test("moving to a project WITH a goal flags the goal change", () => {
        const d = projectTaskDropDecision(workTask, workProjWithGoal);
        expect(d.allowed).toBe(true);
        expect(d.goalWillChange).toBe(true);
        expect(d.newGoalId).toBe("g7");
    });

    test("moving to a project with NO goal leaves the goal alone", () => {
        const d = projectTaskDropDecision(workTask, workProjB);
        expect(d.goalWillChange).toBe(false);
        expect(d.newGoalId).toBe(null);
    });

    test("a task already on that goal is not reported as a change", () => {
        const already = { id: "t4", title: "x", type: "work", project_id: "p1", goal_id: "g7" };
        const d = projectTaskDropDecision(already, workProjWithGoal);
        expect(d.allowed).toBe(true);
        expect(d.goalWillChange).toBe(false);
    });

    test("a refused drop never claims a goal change", () => {
        const d = projectTaskDropDecision(workTask, personalProj);
        expect(d.goalWillChange).toBe(false);
    });
});

describe("projectCardIdUnderPoint — the touch path's hit test", () => {
    // A finger produces no dragover and no drop target, so on mobile the
    // card has to be found by geometry. These are the cases a real drag
    // would only find by accident.
    const rect = (left, top, right, bottom) => ({ left, top, right, bottom });
    const cards = [
        { id: "p1", rect: rect(0, 0, 100, 50) },
        { id: "p2", rect: rect(0, 60, 100, 110) },
    ];

    test("a point inside a card finds it", () => {
        expect(projectCardIdUnderPoint(cards, 50, 25)).toBe("p1");
        expect(projectCardIdUnderPoint(cards, 50, 80)).toBe("p2");
    });

    test("a point in the gap between cards finds nothing", () => {
        expect(projectCardIdUnderPoint(cards, 50, 55)).toBe(null);
    });

    test("the edges count as inside — a fingertip on a border still drops", () => {
        expect(projectCardIdUnderPoint(cards, 0, 0)).toBe("p1");
        expect(projectCardIdUnderPoint(cards, 100, 50)).toBe("p1");
    });

    test("a point outside every card finds nothing", () => {
        expect(projectCardIdUnderPoint(cards, 500, 500)).toBe(null);
        expect(projectCardIdUnderPoint(cards, -10, 25)).toBe(null);
    });

    test("overlapping cards resolve to the one on top (last wins)", () => {
        const stacked = [
            { id: "under", rect: rect(0, 0, 100, 100) },
            { id: "over", rect: rect(40, 40, 60, 60) },
        ];
        expect(projectCardIdUnderPoint(stacked, 50, 50)).toBe("over");
        expect(projectCardIdUnderPoint(stacked, 10, 10)).toBe("under");
    });

    test("empty, missing and malformed inputs return null, not a crash", () => {
        expect(projectCardIdUnderPoint([], 10, 10)).toBe(null);
        expect(projectCardIdUnderPoint(null, 10, 10)).toBe(null);
        expect(projectCardIdUnderPoint(undefined, 10, 10)).toBe(null);
        expect(projectCardIdUnderPoint([{}, { id: "x" }, null], 10, 10)).toBe(null);
    });
});

// #372: a task line on a project card opens the task panel on click.
// On touch, releasing a long-press (the #344 drag gesture) can still
// synthesize a click, which must NOT open the panel.
describe("taskLineClickOpens (#372)", () => {
    test("opens when no long-press has fired", () => {
        expect(taskLineClickOpens(null, 1000)).toBe(true);
        expect(taskLineClickOpens(undefined, 1000)).toBe(true);
    });

    test("swallows a click right after a long-press", () => {
        expect(taskLineClickOpens(1000, 1000)).toBe(false);
        expect(taskLineClickOpens(1000, 1700)).toBe(false);
    });

    test("opens once the window has passed", () => {
        expect(taskLineClickOpens(1000, 1701)).toBe(true);
    });

    test("opens for a stale long-press", () => {
        expect(taskLineClickOpens(1000, 60000)).toBe(true);
    });
});
