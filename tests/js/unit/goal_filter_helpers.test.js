/**
 * Jest tests for static/goal_filter_helpers.js — strict bipartition
 * of goal categories to task type sides (#142). Locks the mapping in
 * with a contract test so a future enum addition that wasn't taught
 * to the helper fails this suite loudly.
 */
"use strict";

const { typeForCategory, filterGoalsByType } = require(
    "../../../static/goal_filter_helpers"
);

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
