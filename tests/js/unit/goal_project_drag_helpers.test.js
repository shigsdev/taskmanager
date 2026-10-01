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
 *
 * 4. REVERSIBILITY, NOT DIRECTION, DECIDES THE CONFIRM (#351). #350
 *    confirmed only when goals were being CLEARED, which left the
 *    worse case silent: a project whose tasks sit on several goals
 *    collapses them all into one on any drop, and nothing then holds
 *    the old spread, because a project stores a single `goal_id`.
 *    Dragging it back restores a one-goal move exactly and a
 *    many-goal move not at all. The live data had a 394-task project
 *    across four goals with its own goal_id NULL — the exact shape
 *    that cleared nothing and warned about nothing.
 *
 * 5. TEMPLATES ARE PART OF IT (#352). `RecurringTask` carries its own
 *    `goal_id` and `recurring_service.py:676` stamps it onto every
 *    task it spawns, so a template left behind re-introduces the old
 *    goal on every future spawn — the #350 invariant decaying on a
 *    timer. They cascade server-side now and are counted here.
 */
"use strict";

const {
    goalProjectDropDecision,
    goalProjectMovePayload,
    goalProjectCascadeImpact,
    goalProjectMoveNeedsConfirm,
    goalProjectConfirmMessage,
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

// --- The cascade impact: what the move WILL do ----------------------------

describe("goalProjectCascadeImpact — the numbers the user acts on", () => {
    // Deliberately includes an archived and a cancelled task: the server
    // cascades with no status filter, so counting only active ones would
    // under-report. These are the rows /api/tasks hides by default,
    // which is the whole reason the caller asks for status=all.
    const tasks = [
        { id: "t1", status: "active", goal_id: "g1" },
        { id: "t2", status: "archived", goal_id: "g1" },
        { id: "t3", status: "active", goal_id: null },
        { id: "t4", status: "cancelled", goal_id: "g2" },
    ];

    test("counts every task whose goal will change", () => {
        // Moving to g2: t1, t2 (g1 -> g2) and t3 (null -> g2) change.
        // t4 is already on g2.
        expect(goalProjectCascadeImpact(tasks, "g2").changing).toBe(3);
    });

    test("a task already on the destination is not counted", () => {
        // Moving to g1: only t3 (null) and t4 (g2) change.
        expect(goalProjectCascadeImpact(tasks, "g1").changing).toBe(2);
    });

    test("unassigning counts every task that HAS a goal — the ones cleared", () => {
        const im = goalProjectCascadeImpact(tasks, null);
        expect(im.changing).toBe(3);        // t1, t2, t4
        expect(im.clearing).toBe(3);
    });

    test("clearing is zero when the destination is a real goal", () => {
        // Nothing loses a goal outright, so the only risk is the spread.
        expect(goalProjectCascadeImpact(tasks, "g2").clearing).toBe(0);
    });

    test("archived and cancelled tasks ARE counted", () => {
        // The server does not filter by status, so neither does this. A
        // completed task left behind would make the goal's own
        // completed-count wrong.
        const hidden = [
            { id: "a", status: "archived", goal_id: "g1" },
            { id: "c", status: "cancelled", goal_id: "g1" },
        ];
        expect(goalProjectCascadeImpact(hidden, null).changing).toBe(2);
    });

    test("nothing to change is zero, so no confirm is raised", () => {
        const aligned = [
            { id: "t1", status: "active", goal_id: "g2" },
            { id: "t2", status: "active", goal_id: "g2" },
        ];
        const im = goalProjectCascadeImpact(aligned, "g2");
        expect(im.changing).toBe(0);
        expect(goalProjectMoveNeedsConfirm(im)).toBe(false);
    });

    test("a project with no tasks is zero, not a crash", () => {
        expect(goalProjectCascadeImpact([], "g2").changing).toBe(0);
        expect(goalProjectCascadeImpact(null, "g2").changing).toBe(0);
        expect(goalProjectCascadeImpact(undefined, null).changing).toBe(0);
    });

    test("undefined and empty-string goals are treated as no goal", () => {
        // A task carrying goal_id: "" must not read as a real goal and
        // inflate the count the confirm quotes.
        const odd = [
            { id: "t1", status: "active" },
            { id: "t2", status: "active", goal_id: "" },
        ];
        expect(goalProjectCascadeImpact(odd, null).changing).toBe(0);
        expect(goalProjectCascadeImpact(odd, "g1").changing).toBe(2);
    });
});

// --- #351: the flatten guard ----------------------------------------------
//
// #350 confirmed on the CLEAR direction only. That was the wrong test.
// What matters is whether the move can be taken back: a project stores
// ONE goal_id, so once several goals have been collapsed into one there
// is nowhere left holding the old spread. Dragging the project back
// restores a single-goal move exactly, and cannot restore a multi-goal
// one at all.

describe("goalProjectCascadeImpact — fromGoals and flattening", () => {
    test("one source goal is NOT flattening — the move is reversible", () => {
        // Every task sits on g1. Drag to g2 and back and they all
        // return to g1, so there is nothing to warn about.
        const tasks = [
            { id: "t1", goal_id: "g1" },
            { id: "t2", goal_id: "g1" },
        ];
        const im = goalProjectCascadeImpact(tasks, "g2");
        expect(im.fromGoals).toEqual([{ goalId: "g1", count: 2 }]);
        expect(im.flattening).toBe(false);
        expect(goalProjectMoveNeedsConfirm(im)).toBe(false);
    });

    test("two source goals IS flattening, even moving TO a goal", () => {
        // This is the case #350 shipped blind: nothing is cleared, so
        // the old guard stayed silent while two goals were overwritten.
        const tasks = [
            { id: "t1", goal_id: "g1" },
            { id: "t2", goal_id: "g2" },
        ];
        const im = goalProjectCascadeImpact(tasks, "g3");
        expect(im.clearing).toBe(0);
        expect(im.flattening).toBe(true);
        expect(goalProjectMoveNeedsConfirm(im)).toBe(true);
    });

    test("tasks with no goal do not count as a source goal", () => {
        // Going from "no goal" to a goal ADDS information. A project
        // that is half-unfiled and half on one goal is still reversible.
        const tasks = [
            { id: "t1", goal_id: null },
            { id: "t2", goal_id: "g1" },
            { id: "t3", goal_id: "" },
        ];
        const im = goalProjectCascadeImpact(tasks, "g2");
        expect(im.changing).toBe(3);
        expect(im.fromGoals).toEqual([{ goalId: "g1", count: 1 }]);
        expect(im.flattening).toBe(false);
    });

    test("the destination goal is not listed as a source", () => {
        // Tasks already on g2 are untouched, so g2 is not losing
        // anything and must not appear in the dialog.
        const tasks = [
            { id: "t1", goal_id: "g1" },
            { id: "t2", goal_id: "g2" },
            { id: "t3", goal_id: "g2" },
        ];
        const im = goalProjectCascadeImpact(tasks, "g2");
        expect(im.fromGoals).toEqual([{ goalId: "g1", count: 1 }]);
        expect(im.flattening).toBe(false);
    });

    test("fromGoals is ordered biggest-loss first", () => {
        const tasks = [
            { id: "a", goal_id: "small" },
            { id: "b", goal_id: "big" },
            { id: "c", goal_id: "big" },
            { id: "d", goal_id: "big" },
            { id: "e", goal_id: "mid" },
            { id: "f", goal_id: "mid" },
        ];
        const im = goalProjectCascadeImpact(tasks, "dest");
        expect(im.fromGoals.map((r) => r.goalId)).toEqual(["big", "mid", "small"]);
    });

    test("the live BAU shape: 4 goals, no clear, must still confirm", () => {
        // The real numbers from prod on 2026-10-01, which is why this
        // guard exists. The project's own goal_id was NULL, so dropping
        // it on any card cleared nothing and raised no dialog while
        // rewriting four goals at once.
        const tasks = [].concat(
            Array.from({ length: 209 }, (_, i) => ({ id: "n" + i, goal_id: null })),
            Array.from({ length: 122 }, (_, i) => ({ id: "w" + i, goal_id: "workbau" })),
            Array.from({ length: 59 }, (_, i) => ({ id: "p" + i, goal_id: "persbau" })),
            Array.from({ length: 3 }, (_, i) => ({ id: "h" + i, goal_id: "health" })),
            [{ id: "pg0", goal_id: "growth" }],
        );
        const im = goalProjectCascadeImpact(tasks, "persbau");
        expect(im.changing).toBe(335);          // 394 - the 59 already there
        expect(im.clearing).toBe(0);            // nothing is being cleared
        expect(im.flattening).toBe(true);       // ...but three goals vanish
        expect(im.fromGoals).toEqual([
            { goalId: "workbau", count: 122 },
            { goalId: "health", count: 3 },
            { goalId: "growth", count: 1 },
        ]);
        expect(goalProjectMoveNeedsConfirm(im)).toBe(true);
    });

    test("goalProjectMoveNeedsConfirm survives a missing impact", () => {
        expect(goalProjectMoveNeedsConfirm(null)).toBe(false);
        expect(goalProjectMoveNeedsConfirm(undefined)).toBe(false);
    });
});

// --- #352: recurring templates are part of the cascade --------------------

describe("goalProjectCascadeImpact — recurring templates", () => {
    test("templates are counted separately from tasks", () => {
        const tasks = [{ id: "t1", goal_id: "g1" }];
        const rec = [{ id: "r1", goal_id: "g1" }, { id: "r2", goal_id: null }];
        const im = goalProjectCascadeImpact(tasks, "g2", rec);
        expect(im.changing).toBe(1);
        expect(im.recurringChanging).toBe(2);
    });

    test("a template's goal counts toward the flatten check", () => {
        // A template is a goal choice that keeps paying out — the
        // spawner copies goal_id onto every task it creates — so losing
        // one is losing strictly more than losing a single task.
        const tasks = [{ id: "t1", goal_id: "g1" }];
        const rec = [{ id: "r1", goal_id: "g2" }];
        const im = goalProjectCascadeImpact(tasks, "g3", rec);
        expect(im.flattening).toBe(true);
        expect(im.fromGoals).toEqual([
            { goalId: "g1", count: 1 },
            { goalId: "g2", count: 1 },
        ]);
    });

    test("a template already on the destination is not counted", () => {
        const rec = [{ id: "r1", goal_id: "g2" }];
        expect(goalProjectCascadeImpact([], "g2", rec).recurringChanging).toBe(0);
    });

    test("omitting the template list is not a crash", () => {
        // Older call sites, and the touch path before it was updated.
        const im = goalProjectCascadeImpact([{ id: "t", goal_id: "g1" }], "g2");
        expect(im.recurringChanging).toBe(0);
        expect(im.changing).toBe(1);
    });

    test("clearing does not count templates — they are not 'tasks cleared'", () => {
        // `clearing` drives the "this cannot be undone" copy about
        // TASKS; templates get their own clause so the sentence stays
        // true either way.
        const im = goalProjectCascadeImpact(
            [{ id: "t", goal_id: "g1" }], null, [{ id: "r", goal_id: "g1" }]);
        expect(im.clearing).toBe(1);
        expect(im.recurringChanging).toBe(1);
    });
});

// --- The confirm copy ------------------------------------------------------
//
// Under test because the dialog's entire job is to state the blast
// radius. A count that disagrees with what the server then does is
// worse than showing no dialog at all.

describe("goalProjectConfirmMessage", () => {
    const titles = { g1: "Work BAU", g2: "Personal BAU", g3: "Get fit" };
    const proj = { id: "p1", name: "BAU" };

    test("a clear names the project and says it cannot be undone", () => {
        const im = goalProjectCascadeImpact([{ id: "t", goal_id: "g1" }], null);
        const msg = goalProjectConfirmMessage(proj, null, im, titles);
        expect(msg).toContain('Take "BAU" out of its goal?');
        expect(msg).toContain("clears the goal on 1 task");
        expect(msg).toContain("cannot be undone");
    });

    test("a flatten names the destination and every goal being overwritten", () => {
        const tasks = [
            { id: "a", goal_id: "g1" },
            { id: "b", goal_id: "g1" },
            { id: "c", goal_id: "g3" },
        ];
        const im = goalProjectCascadeImpact(tasks, "g2");
        const msg = goalProjectConfirmMessage(
            proj, { id: "g2", title: "Personal BAU" }, im, titles);
        expect(msg).toContain('Move "BAU" to "Personal BAU"?');
        expect(msg).toContain("sets the goal on 3 tasks");
        expect(msg).toContain("across 2 goals");
        expect(msg).toContain("2  Work BAU");
        expect(msg).toContain("1  Get fit");
        // The reversibility claim is the actual argument for stopping.
        expect(msg).toContain("will NOT restore that split");
    });

    test("singular and plural both read correctly", () => {
        const one = goalProjectCascadeImpact([{ id: "a", goal_id: "g1" }], null);
        expect(goalProjectConfirmMessage(proj, null, one, titles))
            .toContain("on 1 task.");
        const two = goalProjectCascadeImpact(
            [{ id: "a", goal_id: "g1" }, { id: "b", goal_id: "g1" }], null);
        expect(goalProjectConfirmMessage(proj, null, two, titles))
            .toContain("on 2 tasks.");
    });

    test("repeating tasks get their own clause when there are any", () => {
        const im = goalProjectCascadeImpact(
            [{ id: "t", goal_id: "g1" }], "g2", [{ id: "r", goal_id: "g1" }]);
        const msg = goalProjectConfirmMessage(
            proj, { id: "g2", title: "Personal BAU" }, im, titles);
        expect(msg).toContain("1 task and 1 repeating task");
    });

    test("no repeating tasks means no mention of them", () => {
        const im = goalProjectCascadeImpact([{ id: "t", goal_id: "g1" }], "g2");
        const msg = goalProjectConfirmMessage(
            proj, { id: "g2", title: "Personal BAU" }, im, titles);
        expect(msg).not.toContain("repeating");
    });

    test("an archived source goal reads as prose, never a raw UUID", () => {
        // /goals loads goals with is_active=all, but a goal can be
        // hard-deleted or simply missing from the map. A bare UUID in a
        // destructive dialog tells the user nothing.
        const tasks = [
            { id: "a", goal_id: "g1" },
            { id: "b", goal_id: "7f3c9a21-dead-4beef-0000-000000000000" },
        ];
        const im = goalProjectCascadeImpact(tasks, "g2");
        const msg = goalProjectConfirmMessage(
            proj, { id: "g2", title: "Personal BAU" }, im, titles);
        expect(msg).toContain("a goal you can no longer see");
        expect(msg).not.toContain("7f3c9a21");
    });

    test("a missing title map does not throw", () => {
        const im = goalProjectCascadeImpact(
            [{ id: "a", goal_id: "g1" }, { id: "b", goal_id: "g2" }], "g3");
        expect(() => goalProjectConfirmMessage(proj, { id: "g3" }, im))
            .not.toThrow();
    });

    test("the live BAU dialog states every goal and the real counts", () => {
        // Prod, 2026-10-01. The "BAU" project: 394 tasks spread
        // 209 unfiled / 122 Work BAU / 59 Personal BAU / 3 Health /
        // 1 Personal Growth, with the project's own goal_id NULL. Four
        // recurring templates live on it, and "Evening prep" is the one
        // sitting on the WORK goal — the single mis-set template that
        // stamped all 122 of those task rows.
        const liveTitles = {
            g1: "Work BAU",
            g2: "Personal BAU",
            g3: "Health Improvements for 2026",
            g4: "Personal Growth Improvements by 2026",
        };
        const tasks = [].concat(
            Array.from({ length: 209 }, (_, i) => ({ id: "n" + i, goal_id: null })),
            Array.from({ length: 122 }, (_, i) => ({ id: "w" + i, goal_id: "g1" })),
            Array.from({ length: 59 }, (_, i) => ({ id: "p" + i, goal_id: "g2" })),
            Array.from({ length: 3 }, (_, i) => ({ id: "h" + i, goal_id: "g3" })),
            [{ id: "pg0", goal_id: "g4" }],
        );
        expect(tasks).toHaveLength(394);
        const rec = [
            { id: "evening", goal_id: "g1" },
            { id: "morning", goal_id: null },
            { id: "laundry", goal_id: null },
            { id: "rehab", goal_id: "g2" },
        ];
        const im = goalProjectCascadeImpact(tasks, "g2", rec);
        const msg = goalProjectConfirmMessage(
            proj, { id: "g2", title: "Personal BAU" }, im, liveTitles);
        // 394 - the 59 already on Personal BAU. Templates: all but
        // "rehab", which is already there.
        expect(msg).toContain("335 tasks and 3 repeating tasks");
        expect(msg).toContain("127 of them are on a different goal");
        expect(msg).toContain("across 3 goals");
        expect(msg).toContain("123  Work BAU");   // 122 tasks + the template
        expect(msg).toContain("3  Health Improvements for 2026");
        expect(msg).toContain("1  Personal Growth Improvements by 2026");
        // Nothing is cleared, so #350's guard would have shown nothing.
        expect(im.clearing).toBe(0);
    });
});
