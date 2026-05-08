/**
 * Jest tests for static/reorder_helpers.js — bulk move-up / move-down
 * within a tier. Boundary cases the UI feature has to get right:
 *   - single selected at the top can't move up further
 *   - single selected at the bottom can't move down further
 *   - contiguous block stays a block (single-step shift)
 *   - non-contiguous selection moves independently
 *   - empty / spans-tiers cases classified for the UI
 */
"use strict";

const {
    reorderSelectionWithinTier,
    classifySelectionForReorder,
} = require("../../../static/reorder_helpers");

describe("reorderSelectionWithinTier — move up", () => {
    test("single selected swaps with predecessor", () => {
        expect(
            reorderSelectionWithinTier(["a", "b", "c"], ["b"], "up")
        ).toEqual(["b", "a", "c"]);
    });

    test("selected at top stays put", () => {
        expect(
            reorderSelectionWithinTier(["a", "b", "c"], ["a"], "up")
        ).toEqual(["a", "b", "c"]);
    });

    test("contiguous block of two shifts up by one (block stays a block)", () => {
        // [a b c d] select {b, c} → [b c a d]
        expect(
            reorderSelectionWithinTier(["a", "b", "c", "d"], ["b", "c"], "up")
        ).toEqual(["b", "c", "a", "d"]);
    });

    test("contiguous block at top stays put", () => {
        expect(
            reorderSelectionWithinTier(["a", "b", "c"], ["a", "b"], "up")
        ).toEqual(["a", "b", "c"]);
    });

    test("non-contiguous selection — each moves up over a non-selected neighbor", () => {
        // [a b c d e] select {b, d} → [b a d c e]
        expect(
            reorderSelectionWithinTier(["a", "b", "c", "d", "e"], ["b", "d"], "up")
        ).toEqual(["b", "a", "d", "c", "e"]);
    });

    test("does not mutate input", () => {
        const input = ["a", "b", "c"];
        reorderSelectionWithinTier(input, ["b"], "up");
        expect(input).toEqual(["a", "b", "c"]);
    });
});

describe("reorderSelectionWithinTier — move down", () => {
    test("single selected swaps with successor", () => {
        expect(
            reorderSelectionWithinTier(["a", "b", "c"], ["b"], "down")
        ).toEqual(["a", "c", "b"]);
    });

    test("selected at bottom stays put", () => {
        expect(
            reorderSelectionWithinTier(["a", "b", "c"], ["c"], "down")
        ).toEqual(["a", "b", "c"]);
    });

    test("contiguous block shifts down by one", () => {
        // [a b c d] select {b, c} → [a d b c]
        expect(
            reorderSelectionWithinTier(["a", "b", "c", "d"], ["b", "c"], "down")
        ).toEqual(["a", "d", "b", "c"]);
    });

    test("contiguous block at bottom stays put", () => {
        expect(
            reorderSelectionWithinTier(["a", "b", "c"], ["b", "c"], "down")
        ).toEqual(["a", "b", "c"]);
    });

    test("non-contiguous selection — each moves down over a non-selected neighbor", () => {
        // [a b c d e] select {b, d} → [a c b e d]
        expect(
            reorderSelectionWithinTier(["a", "b", "c", "d", "e"], ["b", "d"], "down")
        ).toEqual(["a", "c", "b", "e", "d"]);
    });
});

describe("reorderSelectionWithinTier — degenerate inputs", () => {
    test("empty selection returns a copy of input", () => {
        const input = ["a", "b", "c"];
        const out = reorderSelectionWithinTier(input, [], "up");
        expect(out).toEqual(input);
        expect(out).not.toBe(input);  // new array, not the same ref
    });

    test("Set selection works the same as array", () => {
        expect(
            reorderSelectionWithinTier(["a", "b", "c"], new Set(["b"]), "up")
        ).toEqual(["b", "a", "c"]);
    });

    test("rejects bad direction", () => {
        expect(() =>
            reorderSelectionWithinTier(["a"], ["a"], "sideways")
        ).toThrow();
    });
});

describe("classifySelectionForReorder", () => {
    const tasks = [
        { id: "a", tier: "today" },
        { id: "b", tier: "today" },
        { id: "c", tier: "tomorrow" },
        { id: "d", tier: "tomorrow" },
    ];

    test("empty selection returns reason 'empty'", () => {
        expect(classifySelectionForReorder(tasks, [])).toEqual({
            ok: false, reason: "empty",
        });
    });

    test("single tier returns ok with tier", () => {
        expect(classifySelectionForReorder(tasks, ["a", "b"])).toEqual({
            ok: true, tier: "today",
        });
    });

    test("spans multiple tiers returns reason 'multiple_tiers'", () => {
        expect(classifySelectionForReorder(tasks, ["a", "c"])).toEqual({
            ok: false, reason: "multiple_tiers",
        });
    });

    test("Set selection works", () => {
        expect(
            classifySelectionForReorder(tasks, new Set(["a", "b"]))
        ).toEqual({ ok: true, tier: "today" });
    });

    test("ids not in the task list are ignored", () => {
        expect(
            classifySelectionForReorder(tasks, ["a", "b", "ghost-id"])
        ).toEqual({ ok: true, tier: "today" });
    });
});
