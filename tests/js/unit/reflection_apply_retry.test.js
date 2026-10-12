/**
 * Jest tests for #437 — a partly failed reflection Apply can be retried.
 *
 * The server answers with summary.failed: the positions (in the request)
 * of the actions that didn't land. The page keeps exactly those rows
 * ticked, and turns the rest into "applied" rows.
 */
const H = require("../../../static/reflection_helpers.js");

const proposed = {
    explicit: [{ op: "create", target: "a" }, { op: "create", target: "b" }],
    suggested: [{ op: "delete", target: "c" }],
};

describe("selectedKeys (#437)", () => {
    test("lines up with selectedActions, position for position", () => {
        const checked = { "explicit:1": true, "suggested:0": true, "explicit:0": false };
        expect(H.selectedKeys(proposed, checked)).toEqual(["explicit:1", "suggested:0"]);
        expect(H.selectedActions(proposed, checked).map((a) => a.target)).toEqual(["b", "c"]);
    });

    test("nothing ticked, or nothing proposed", () => {
        expect(H.selectedKeys(proposed, {})).toEqual([]);
        expect(H.selectedKeys(null, null)).toEqual([]);
    });
});

describe("applyOutcome (#437)", () => {
    test("failed positions map back to their rows", () => {
        expect(H.applyOutcome(["explicit:0", "explicit:1", "suggested:0"], [1]))
            .toEqual({ applied: ["explicit:0", "suggested:0"], failed: ["explicit:1"] });
    });

    test("no failures: everything applied", () => {
        expect(H.applyOutcome(["explicit:0"], [])).toEqual({ applied: ["explicit:0"], failed: [] });
        expect(H.applyOutcome(["explicit:0"], undefined)).toEqual({ applied: ["explicit:0"], failed: [] });
    });

    test("all failed", () => {
        expect(H.applyOutcome(["explicit:0", "explicit:1"], [0, 1]))
            .toEqual({ applied: [], failed: ["explicit:0", "explicit:1"] });
    });
});

describe("partialApplyText (#437)", () => {
    test("counts read naturally", () => {
        expect(H.partialApplyText(1, 1)).toMatch(/^1 change was applied; 1 didn't save\./);
        expect(H.partialApplyText(3, 2)).toMatch(/^3 changes were applied; 2 didn't save\./);
        expect(H.partialApplyText(0, 1)).toMatch(/^That change didn't save\. The ones/);
        expect(H.partialApplyText(0, 2)).toMatch(/^2 changes didn't save\. The ones/);
    });
});

describe("appliedBadge (#437)", () => {
    test("applied, partly applied, or nothing", () => {
        expect(H.appliedBadge({ applied_at: "2026-10-12T00:00:00Z" })).toBe(" ✓ applied");
        expect(H.appliedBadge({ applied_at: null, applied_actions: { actions: [{}] } })).toBe(" ◐ partly applied");
        expect(H.appliedBadge({ applied_at: null, applied_actions: { actions: [] } })).toBe("");
        expect(H.appliedBadge({ applied_at: null, applied_actions: null })).toBe("");
        expect(H.appliedBadge(null)).toBe("");
    });
});
