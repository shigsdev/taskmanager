/**
 * Jest tests for #436 — the PATCH body for one /plan suggestion row.
 *
 * A "move" with no date used to send `due_date: null`, which wiped the
 * task's date and skipped the server's Today / Tomorrow date rules.
 */
const { planRowPayload } = require("../../../static/plan_helpers.js");

const blank = { tier: null, due_date: null, project: null, goal: null };
const move = (extra) => Object.assign({ task_id: "t1", action: "move" }, extra);

describe("planRowPayload (#436)", () => {
    test("a move with no date anywhere sends no due_date", () => {
        const body = planRowPayload(move({ suggested_tier: "this_week", suggested_due_date: null }), blank);
        expect(body).toEqual({ tier: "this_week" });
        expect("due_date" in body).toBe(false);
    });

    test("a move whose suggestion has no date key sends no due_date", () => {
        expect(planRowPayload(move({ suggested_tier: "today" }), blank)).toEqual({ tier: "today" });
    });

    test("the suggested date is used when the date box is empty", () => {
        const body = planRowPayload(move({ suggested_tier: "next_week", suggested_due_date: "2026-10-21" }), blank);
        expect(body).toEqual({ tier: "next_week", due_date: "2026-10-21" });
    });

    test("what the user picked beats the suggestion", () => {
        const body = planRowPayload(
            move({ suggested_tier: "next_week", suggested_due_date: "2026-10-21" }),
            { tier: "this_week", due_date: "2026-10-15", project: null, goal: null });
        expect(body).toEqual({ tier: "this_week", due_date: "2026-10-15" });
    });

    test("freeze and delete are unchanged", () => {
        expect(planRowPayload({ action: "freeze" }, blank)).toEqual({ tier: "freezer" });
        expect(planRowPayload({ action: "delete" }, blank)).toEqual({ _delete: true });
    });

    test("keep with nothing picked sends nothing", () => {
        expect(planRowPayload({ action: "keep" }, blank)).toEqual({});
    });

    test("a picked project / goal is sent; a blank one is left alone", () => {
        expect(planRowPayload({ action: "keep" }, { tier: null, due_date: null, project: "p1", goal: "g1" }))
            .toEqual({ project_id: "p1", goal_id: "g1" });
        expect(planRowPayload({ action: "keep" }, { tier: null, due_date: null, project: "p1", goal: null }))
            .toEqual({ project_id: "p1" });
    });
});

// #473: /plan holds off a deploy reload while a suggestion is still undecided.
const { hasPendingRows } = require("../../../static/plan_helpers.js");

describe("hasPendingRows (#473)", () => {
    test("nothing shown yet: no rows, nothing pending", () => {
        expect(hasPendingRows({})).toBe(false);
        expect(hasPendingRows(null)).toBe(false);
        expect(hasPendingRows(undefined)).toBe(false);
    });

    test("one row still pending", () => {
        expect(hasPendingRows({ a: "accepted", b: "pending" })).toBe(true);
    });

    test("every row accepted or ignored: nothing left to lose", () => {
        expect(hasPendingRows({ a: "accepted", b: "ignored" })).toBe(false);
    });
});
