/**
 * Jest tests for static/goal_filter_helpers.js — strict bipartition
 * of goal categories to task type sides (#142). Locks the mapping in
 * with a contract test so a future enum addition that wasn't taught
 * to the helper fails this suite loudly.
 */
"use strict";

const {
    typeForCategory, filterGoalsByType, goalsForDropdown, auditProjectGoalLinks,
} = require("../../../static/goal_filter_helpers");

describe("typeForCategory — strict bipartition (#142)", () => {
    test.each([
        ["work", "work"],
        ["bau", "work"],
        ["health", "personal"],
        ["relationships", "personal"],
        ["personal_growth", "personal"],
    ])("%s → %s", (cat, expected) => {
        expect(typeForCategory(cat)).toBe(expected);
    });

    test("unknown category defaults to personal-side", () => {
        const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
        expect(typeForCategory("future_category")).toBe("personal");
        expect(warn).toHaveBeenCalled();
        warn.mockRestore();
    });

    test("non-string input defaults to personal-side", () => {
        expect(typeForCategory(null)).toBe("personal");
        expect(typeForCategory(undefined)).toBe("personal");
        expect(typeForCategory(42)).toBe("personal");
    });
});

describe("filterGoalsByType", () => {
    const goals = [
        { id: "g1", category: "work" },
        { id: "g2", category: "bau" },
        { id: "g3", category: "health" },
        { id: "g4", category: "relationships" },
        { id: "g5", category: "personal_growth" },
    ];

    test("filterType=work returns work + bau goals only", () => {
        const out = filterGoalsByType(goals, "work");
        expect(out.map((g) => g.id).sort()).toEqual(["g1", "g2"]);
    });

    test("filterType=personal returns health + relationships + personal_growth", () => {
        const out = filterGoalsByType(goals, "personal");
        expect(out.map((g) => g.id).sort()).toEqual(["g3", "g4", "g5"]);
    });

    test("falsy filterType returns a copy of the input list", () => {
        const out = filterGoalsByType(goals, null);
        expect(out.map((g) => g.id)).toEqual(["g1", "g2", "g3", "g4", "g5"]);
        expect(out).not.toBe(goals);  // new array
    });

    test("empty / non-array input is safe", () => {
        expect(filterGoalsByType(null, "work")).toEqual([]);
        expect(filterGoalsByType(undefined, "work")).toEqual([]);
        expect(filterGoalsByType([], "work")).toEqual([]);
    });

    test("personal_growth is on personal-side ONLY (strict — not on work)", () => {
        // Locks option A vs B (where personal_growth would show on both).
        const work = filterGoalsByType(goals, "work");
        const personal = filterGoalsByType(goals, "personal");
        expect(work.find((g) => g.category === "personal_growth")).toBeUndefined();
        expect(personal.find((g) => g.category === "personal_growth")).toBeDefined();
    });
});

describe("goalsForDropdown — type scope ∪ keep set (#272)", () => {
    // Models the exact reported scenario: a Personal task whose project
    // "AI Training" links to the work-category goal "AI Upskilling".
    const goals = [
        { id: "g_work", category: "work" },        // AI Upskilling-like
        { id: "g_bau", category: "bau" },
        { id: "g_health", category: "health" },
        { id: "g_rel", category: "relationships" },
        { id: "g_growth", category: "personal_growth" },
    ];

    test("personal scope with NO keep set hides the work-side goal (the bug)", () => {
        const out = goalsForDropdown(goals, "personal", null).map((g) => g.id);
        expect(out).toEqual(["g_health", "g_rel", "g_growth"]);
        expect(out).not.toContain("g_work");
    });

    test("personal scope keeps the linked work-side goal when in the keep set (the fix)", () => {
        const out = goalsForDropdown(goals, "personal", ["g_work"]).map((g) => g.id);
        expect(out).toContain("g_work");                // cross-side linked goal surfaced
        expect(out).toEqual(["g_work", "g_health", "g_rel", "g_growth"]);  // stable order
    });

    test("keep set accepts a Set as well as an array", () => {
        const out = goalsForDropdown(goals, "personal", new Set(["g_work"])).map((g) => g.id);
        expect(out).toContain("g_work");
    });

    test("a goal that is BOTH in-scope and a keepId appears exactly once", () => {
        const out = goalsForDropdown(goals, "personal", ["g_health"]).map((g) => g.id);
        expect(out.filter((id) => id === "g_health")).toHaveLength(1);
        expect(out).toEqual(["g_health", "g_rel", "g_growth"]);
    });

    test("keepIds for a goal that doesn't exist is ignored (no phantom option)", () => {
        const out = goalsForDropdown(goals, "personal", ["g_nonexistent"]).map((g) => g.id);
        expect(out).toEqual(["g_health", "g_rel", "g_growth"]);
    });

    test("falsy filterType returns every goal — keepIds is a no-op", () => {
        const out = goalsForDropdown(goals, null, ["g_work"]).map((g) => g.id);
        expect(out).toEqual(["g_work", "g_bau", "g_health", "g_rel", "g_growth"]);
    });

    test("multiple keepIds (linked project goal + task's current goal) both surface", () => {
        // e.g. project links to g_work but the task is currently on g_bau
        const out = goalsForDropdown(goals, "personal", ["g_work", "g_bau"]).map((g) => g.id);
        expect(out).toEqual(["g_work", "g_bau", "g_health", "g_rel", "g_growth"]);
    });

    test("non-array goals is safe", () => {
        expect(goalsForDropdown(null, "personal", ["g_work"])).toEqual([]);
        expect(goalsForDropdown(undefined, "personal", null)).toEqual([]);
    });
});

describe("auditProjectGoalLinks — project→goal cleanup audit (#273)", () => {
    const goals = [
        { id: "gw", category: "work", title: "AI Upskilling" },
        { id: "gh", category: "health", title: "Run a half marathon" },
        { id: "gr", category: "relationships", title: "Family" },
    ];

    test("flags a personal project linked to a work-side goal as cross-side", () => {
        const projects = [
            { id: "p1", name: "AI Training", type: "personal", goal_id: "gw" },
        ];
        const out = auditProjectGoalLinks(projects, goals);
        expect(out.crossSide).toHaveLength(1);
        expect(out.crossSide[0].project.id).toBe("p1");
        expect(out.crossSide[0].goal.id).toBe("gw");
        expect(out.crossSide[0].projectSide).toBe("personal");
        expect(out.crossSide[0].goalSide).toBe("work");
        expect(out.unlinked).toHaveLength(0);
    });

    test("flags a work project linked to a personal-side goal as cross-side", () => {
        const projects = [
            { id: "p2", name: "Side Gig", type: "work", goal_id: "gh" },
        ];
        const out = auditProjectGoalLinks(projects, goals);
        expect(out.crossSide).toHaveLength(1);
        expect(out.crossSide[0].projectSide).toBe("work");
        expect(out.crossSide[0].goalSide).toBe("personal");
    });

    test("a same-side link is NOT flagged", () => {
        const projects = [
            { id: "p3", name: "Marathon Prep", type: "personal", goal_id: "gh" },
            { id: "p4", name: "AI Work", type: "work", goal_id: "gw" },
        ];
        const out = auditProjectGoalLinks(projects, goals);
        expect(out.crossSide).toHaveLength(0);
        expect(out.unlinked).toHaveLength(0);
    });

    test("a project with no goal is flagged unlinked", () => {
        const projects = [
            { id: "p5", name: "Home Reno", type: "personal", goal_id: null },
            { id: "p6", name: "Misc", type: "work" },  // goal_id absent
        ];
        const out = auditProjectGoalLinks(projects, goals);
        expect(out.unlinked.map((u) => u.project.id)).toEqual(["p5", "p6"]);
        expect(out.crossSide).toHaveLength(0);
    });

    test("a goal_id not present in the goals list is left unflagged (archived/unknown)", () => {
        const projects = [
            { id: "p7", name: "Ghost link", type: "personal", goal_id: "deleted" },
        ];
        const out = auditProjectGoalLinks(projects, goals);
        expect(out.crossSide).toHaveLength(0);
        expect(out.unlinked).toHaveLength(0);
    });

    test("mixed set: order follows input, both buckets populated", () => {
        const projects = [
            { id: "a", name: "A", type: "personal", goal_id: "gw" },   // cross
            { id: "b", name: "B", type: "personal", goal_id: null },    // unlinked
            { id: "c", name: "C", type: "work", goal_id: "gw" },        // same-side OK
            { id: "d", name: "D", type: "work", goal_id: "gr" },        // cross
        ];
        const out = auditProjectGoalLinks(projects, goals);
        expect(out.crossSide.map((x) => x.project.id)).toEqual(["a", "d"]);
        expect(out.unlinked.map((x) => x.project.id)).toEqual(["b"]);
    });

    test("non-array / empty inputs are safe", () => {
        expect(auditProjectGoalLinks(null, goals)).toEqual({ crossSide: [], unlinked: [] });
        expect(auditProjectGoalLinks([], goals)).toEqual({ crossSide: [], unlinked: [] });
        expect(auditProjectGoalLinks([{ id: "x", type: "work", goal_id: "gw" }], null))
            .toEqual({ crossSide: [], unlinked: [] });  // goals null → goal not found → unflagged
    });
});
