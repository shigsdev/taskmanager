/**
 * #495: re-opening a reflection's saved proposals from History.
 */
"use strict";

const { actionKey, landedRowKeys, canReviewSaved } = require("../../../static/reflection_helpers");

const A = { op: "create", entity: "task", target: "First", reason: "a" };
const B = { op: "update", entity: "task", target: "Second", payload: { tier: "today", title: "x" } };

describe("actionKey", () => {
    test("the same action reads the same whatever its key order", () => {
        const reordered = { payload: { title: "x", tier: "today" }, target: "Second", entity: "task", op: "update" };
        expect(actionKey(reordered)).toBe(actionKey(B));
        expect(actionKey(A)).not.toBe(actionKey(B));
    });
});

describe("landedRowKeys", () => {
    test("names the rows whose action already landed", () => {
        const proposed = { explicit: [A], suggested: [B] };
        expect(landedRowKeys(proposed, { actions: [B] })).toEqual(["suggested:0"]);
        expect(landedRowKeys(proposed, { actions: [A, B] })).toEqual(["explicit:0", "suggested:0"]);
    });

    test("nothing applied yet, or no record, lands nothing", () => {
        expect(landedRowKeys({ explicit: [A] }, null)).toEqual([]);
        expect(landedRowKeys({ explicit: [A] }, { actions: [] })).toEqual([]);
        expect(landedRowKeys(null, { actions: [A] })).toEqual([]);
    });
});

describe("canReviewSaved", () => {
    test("proposals and not fully applied", () => {
        expect(canReviewSaved({ proposed_actions: { explicit: [A] }, applied_at: null })).toBe(true);
        expect(canReviewSaved({ proposed_actions: { suggested: [B] }, applied_actions: { actions: [B] } })).toBe(true);
    });

    test("fully applied, empty, or missing → no button", () => {
        expect(canReviewSaved({ proposed_actions: { explicit: [A] }, applied_at: "2026-10-16T00:00:00Z" })).toBe(false);
        expect(canReviewSaved({ proposed_actions: { explicit: [], suggested: [] } })).toBe(false);
        expect(canReviewSaved(null)).toBe(false);
    });
});
