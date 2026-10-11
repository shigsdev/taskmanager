/**
 * #427: goal links silently wiped.
 *
 * The rule: when a task's project changes, a goal that came from the old
 * project goes with it, and a goal you set yourself stays.
 *
 * goalAfterProjectChange — what the task panel's and Auto-categorize's Goal
 * select become when Project changes. It used to reset to the new project's
 * goal or "— None —", blanking a goal set by hand.
 *
 * categorizeApplyPayload — what 💡 Auto-categorize's Apply sends. It used to
 * send type / project_id / goal_id for every row, so a blank select became
 * `null` on the server and wiped the task's own project and goal.
 */
"use strict";

const { goalAfterProjectChange } = require("../../../static/filter_helpers");
const { categorizeApplyPayload } = require("../../../static/inbox_categorize_helpers");

const projects = [
    { id: "p-roadmap", goal_id: "g-ship" },
    { id: "p-bau", goal_id: null },
    { id: "p-other", goal_id: "g-other" },
];
const allowed = new Set(["", "g-ship", "g-other", "g-mine"]);

describe("goalAfterProjectChange (#427)", () => {
    test("a new project with a goal brings it (the existing cascade)", () => {
        expect(goalAfterProjectChange("", "p-roadmap", null, projects, allowed)).toBe("g-ship");
        expect(goalAfterProjectChange("p-bau", "p-other", "g-mine", projects, allowed)).toBe("g-other");
    });

    test("no project: a goal from the old project goes with it", () => {
        expect(goalAfterProjectChange("p-roadmap", "", "g-ship", projects, allowed)).toBeNull();
    });

    test("no project: a goal set by hand stays", () => {
        expect(goalAfterProjectChange("p-roadmap", "", "g-mine", projects, allowed)).toBe("g-mine");
        expect(goalAfterProjectChange("", "", "g-mine", projects, allowed)).toBe("g-mine");
        expect(goalAfterProjectChange(null, "", "g-mine", projects, allowed)).toBe("g-mine");
    });

    test("a project with no goal: the old project's goal goes (2026-05-04), yours stays", () => {
        expect(goalAfterProjectChange("p-roadmap", "p-bau", "g-ship", projects, allowed)).toBeNull();
        expect(goalAfterProjectChange("p-roadmap", "p-bau", "g-mine", projects, allowed)).toBe("g-mine");
    });

    test("an old project the page doesn't know (archived) counts the goal as yours", () => {
        expect(goalAfterProjectChange("p-gone", "", "g-ship", projects, allowed)).toBe("g-ship");
    });

    test("no goal in, no goal out", () => {
        expect(goalAfterProjectChange("p-roadmap", "", null, projects, allowed)).toBeNull();
        expect(goalAfterProjectChange("p-roadmap", "", "", projects, allowed)).toBeNull();
    });
});

describe("categorizeApplyPayload (#427)", () => {
    const current = { type: "work", project_id: "p-roadmap", goal_id: "g-ship" };
    const row = (over) => ({
        tier: "this_week", type: "work", project: "p-roadmap", goal: "g-ship",
        due: "", dueAuto: false, ...over,
    });

    test("nothing changed: only the section is sent", () => {
        expect(categorizeApplyPayload(row({}), current)).toEqual({ tier: "this_week" });
    });

    test("a changed type is sent, an unchanged one isn't", () => {
        expect(categorizeApplyPayload(row({ type: "personal" }), current))
            .toEqual({ tier: "this_week", type: "personal" });
    });

    test("a changed project sends the goal too, so the cascade can't override the row", () => {
        expect(categorizeApplyPayload(row({ project: "p-other", goal: "g-mine" }), current))
            .toEqual({ tier: "this_week", project_id: "p-other", goal_id: "g-mine" });
        expect(categorizeApplyPayload(row({ project: "p-other" }), current))
            .toEqual({ tier: "this_week", project_id: "p-other", goal_id: "g-ship" });
    });

    test("clearing a select you changed still clears it", () => {
        expect(categorizeApplyPayload(row({ project: "", goal: "" }), current))
            .toEqual({ tier: "this_week", project_id: null, goal_id: null });
        expect(categorizeApplyPayload(row({ goal: "" }), current))
            .toEqual({ tier: "this_week", goal_id: null });
    });

    test("filling a blank is sent", () => {
        const blank = { type: "personal", project_id: null, goal_id: null };
        expect(categorizeApplyPayload(
            row({ type: "personal", project: "p-other", goal: "g-other" }), blank,
        )).toEqual({ tier: "this_week", project_id: "p-other", goal_id: "g-other" });
        expect(categorizeApplyPayload(row({ type: "personal", project: "", goal: "" }), blank))
            .toEqual({ tier: "this_week" });
    });

    test("due date: an explicit date is sent, an auto placeholder is not (#208)", () => {
        expect(categorizeApplyPayload(row({ due: "2026-10-20" }), current))
            .toEqual({ tier: "this_week", due_date: "2026-10-20" });
        expect(categorizeApplyPayload(row({ tier: "today", due: "2026-10-11", dueAuto: true }), current))
            .toEqual({ tier: "today" });
    });

    test("no current values (an older server): blank selects are left alone", () => {
        expect(categorizeApplyPayload(row({ project: "", goal: "" }), {}))
            .toEqual({ tier: "this_week", type: "work" });
    });
});
