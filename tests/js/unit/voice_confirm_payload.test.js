/**
 * #425: what the voice memo review screen sends on Add All / Add Selected,
 * and what it tells you afterwards.
 *
 * The server routes each candidate on `route` (goal / project / task),
 * files goals under `category`, and turns a candidate with `repeat` into a
 * recurring template. The screen let you set all three but never sent them,
 * so every dictated goal, project and recurring item became an Inbox task.
 * The server tests posted these fields by hand, so nothing caught it.
 */
"use strict";

const {
    buildConfirmPayload, repeatProblem, confirmSummary,
} = require("../../../static/voice_memo_helpers");

const cand = (over) => ({
    title: "Something", type: "personal", tier: "inbox", due_date: null,
    project_id: null, goal_id: null, route: "task", category: "personal_growth",
    included: true, ...over,
});

describe("buildConfirmPayload (#425)", () => {
    test("forwards route, category and repeat", () => {
        const repeat = { frequency: "weekly", day_of_week: 0, day_of_month: null, end_date: null };
        const out = buildConfirmPayload([
            cand({ title: "Run a marathon", route: "goal", category: "health" }),
            cand({ title: "Kitchen remodel", route: "project", type: "personal" }),
            cand({ title: "Water the plants", repeat }),
        ], false);
        expect(out).toHaveLength(3);
        expect(out[0]).toMatchObject({ title: "Run a marathon", route: "goal", category: "health" });
        expect(out[1]).toMatchObject({ title: "Kitchen remodel", route: "project", type: "personal" });
        expect(out[2]).toMatchObject({ title: "Water the plants", route: "task", repeat });
    });

    test("keeps the fields the server already used", () => {
        const [row] = buildConfirmPayload([cand({
            title: "  Call Bob  ", type: "work", tier: "today", due_date: "2026-10-12",
            project_id: "p1", goal_id: "g1",
        })], false);
        expect(row).toEqual({
            title: "Call Bob", type: "work", tier: "today", due_date: "2026-10-12",
            project_id: "p1", goal_id: "g1", route: "task", category: "personal_growth",
            included: true,
        });
    });

    test("no repeat key unless the row was made recurring", () => {
        const [row] = buildConfirmPayload([cand({})], false);
        expect("repeat" in row).toBe(false);
    });

    test("defaults: route task, type personal, tier inbox, null dates and links", () => {
        const [row] = buildConfirmPayload([{ title: "Bare" }], false);
        expect(row).toMatchObject({
            route: "task", type: "personal", tier: "inbox",
            due_date: null, project_id: null, goal_id: null, included: true,
        });
    });

    test("Add Selected drops unticked rows; Add All keeps them", () => {
        const rows = [cand({ title: "A" }), cand({ title: "B", included: false })];
        expect(buildConfirmPayload(rows, true).map((r) => r.title)).toEqual(["A"]);
        expect(buildConfirmPayload(rows, false).map((r) => r.title)).toEqual(["A", "B"]);
    });

    test("blank titles are dropped", () => {
        expect(buildConfirmPayload([cand({ title: "   " }), cand({ title: "" })], false)).toEqual([]);
    });
});

describe("repeatProblem (#425)", () => {
    test("complete repeats are fine", () => {
        expect(repeatProblem({ frequency: "daily" })).toBeNull();
        expect(repeatProblem({ frequency: "weekdays" })).toBeNull();
        expect(repeatProblem({ frequency: "weekly", day_of_week: 0 })).toBeNull();
        expect(repeatProblem({ frequency: "weekly", day_of_week: 6 })).toBeNull();
        expect(repeatProblem({ frequency: "monthly_date", day_of_month: 31 })).toBeNull();
        expect(repeatProblem({
            frequency: "monthly_nth_weekday", week_of_month: 2, day_of_week: 1,
        })).toBeNull();
    });
    test("Weekly needs a day", () => {
        expect(repeatProblem({ frequency: "weekly", day_of_week: null })).toMatch(/day of the week/i);
    });
    test("Monthly by date needs a day 1-31", () => {
        expect(repeatProblem({ frequency: "monthly_date", day_of_month: null })).toMatch(/day of the month/i);
        expect(repeatProblem({ frequency: "monthly_date", day_of_month: 0 })).toMatch(/day of the month/i);
        expect(repeatProblem({ frequency: "monthly_date", day_of_month: 32 })).toMatch(/day of the month/i);
    });
    test("Monthly by Nth weekday needs a week and a day", () => {
        expect(repeatProblem({ frequency: "monthly_nth_weekday", day_of_week: 1 }))
            .toMatch(/which week/i);
        expect(repeatProblem({ frequency: "monthly_nth_weekday", week_of_month: 5, day_of_week: 1 }))
            .toMatch(/which week/i);
        expect(repeatProblem({ frequency: "monthly_nth_weekday", week_of_month: 1 }))
            .toMatch(/day of the week/i);
    });
});

describe("confirmSummary (#425)", () => {
    test("names every kind that was created", () => {
        expect(confirmSummary({
            tasks: [{}, {}], goals: [{}], projects: [{}], recurring: [{}],
        })).toBe("Added 2 tasks, 1 goal, 1 project and 1 recurring task.");
    });
    test("one kind, singular and plural", () => {
        expect(confirmSummary({ tasks: [{}] })).toBe("Added 1 task.");
        expect(confirmSummary({ goals: [{}, {}] })).toBe("Added 2 goals.");
        expect(confirmSummary({ tasks: [], recurring: [{}, {}] })).toBe("Added 2 recurring tasks.");
    });
    test("two kinds join with 'and'", () => {
        expect(confirmSummary({ tasks: [{}], projects: [{}, {}] }))
            .toBe("Added 1 task and 2 projects.");
    });
    test("nothing created", () => {
        expect(confirmSummary({ tasks: [], goals: [] })).toBe("Nothing was added.");
        expect(confirmSummary(null)).toBe("Nothing was added.");
    });
    test("the server's warning is shown after the summary", () => {
        expect(confirmSummary({ tasks: [{}], warning: "1 recurring item couldn't be created." }))
            .toBe("Added 1 task. 1 recurring item couldn't be created.");
    });
});
