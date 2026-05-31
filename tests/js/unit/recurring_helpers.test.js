/**
 * Jest tests for static/recurring_helpers.js — the #266 recurring-editor
 * payload shaper. The load-bearing behaviour: each frequency sets only
 * its own day fields, and ALL four frequency-specific fields are always
 * present (null when not relevant) so switching frequency clears the
 * stale shape server-side.
 */
"use strict";

const { buildRecurringEditPayload } = require(
    "../../../static/recurring_helpers"
);

const BASE = {
    title: "Standup",
    type: "work",
    projectId: "p1",
    goalId: "g1",
    url: "",
    notes: "",
    endDate: "",
    dayOfWeek: 2,
    daysOfWeek: [0, 2, 4],
    dayOfMonth: 15,
    weekOfMonth: 1,
};

describe("buildRecurringEditPayload — common fields", () => {
    test("trims title; empty url/notes/endDate → null; ids passthrough", () => {
        const p = buildRecurringEditPayload({
            ...BASE, frequency: "daily", title: "  Standup  ",
            url: "  ", notes: "", endDate: "",
        });
        expect(p.title).toBe("Standup");
        expect(p.url).toBeNull();
        expect(p.notes).toBeNull();
        expect(p.end_date).toBeNull();
        expect(p.project_id).toBe("p1");
        expect(p.goal_id).toBe("g1");
        expect(p.type).toBe("work");
    });

    test("blank project/goal → null", () => {
        const p = buildRecurringEditPayload({ ...BASE, frequency: "daily", projectId: "", goalId: "" });
        expect(p.project_id).toBeNull();
        expect(p.goal_id).toBeNull();
    });

    test("non-empty url/notes/endDate pass through", () => {
        const p = buildRecurringEditPayload({
            ...BASE, frequency: "daily",
            url: "https://x", notes: "hi", endDate: "2026-09-01",
        });
        expect(p.url).toBe("https://x");
        expect(p.notes).toBe("hi");
        expect(p.end_date).toBe("2026-09-01");
    });
});

describe("buildRecurringEditPayload — frequency branching + stale clearing", () => {
    test("daily sets NO day fields (all four null)", () => {
        const p = buildRecurringEditPayload({ ...BASE, frequency: "daily" });
        expect(p.frequency).toBe("daily");
        expect(p.day_of_week).toBeNull();
        expect(p.days_of_week).toBeNull();
        expect(p.day_of_month).toBeNull();
        expect(p.week_of_month).toBeNull();
    });

    test("weekdays sets NO day fields", () => {
        const p = buildRecurringEditPayload({ ...BASE, frequency: "weekdays" });
        expect(p.day_of_week).toBeNull();
        expect(p.days_of_week).toBeNull();
    });

    test("weekly sets ONLY day_of_week", () => {
        const p = buildRecurringEditPayload({ ...BASE, frequency: "weekly" });
        expect(p.day_of_week).toBe(2);
        expect(p.days_of_week).toBeNull();
        expect(p.day_of_month).toBeNull();
        expect(p.week_of_month).toBeNull();
    });

    test("multi_day_of_week sets ONLY days_of_week", () => {
        const p = buildRecurringEditPayload({ ...BASE, frequency: "multi_day_of_week" });
        expect(p.days_of_week).toEqual([0, 2, 4]);
        expect(p.day_of_week).toBeNull();
        expect(p.day_of_month).toBeNull();
        expect(p.week_of_month).toBeNull();
    });

    test("multi_day_of_week with no days → empty array (backend 422s)", () => {
        const p = buildRecurringEditPayload({ ...BASE, frequency: "multi_day_of_week", daysOfWeek: [] });
        expect(p.days_of_week).toEqual([]);
    });

    test("monthly_date sets ONLY day_of_month", () => {
        const p = buildRecurringEditPayload({ ...BASE, frequency: "monthly_date" });
        expect(p.day_of_month).toBe(15);
        expect(p.day_of_week).toBeNull();
        expect(p.days_of_week).toBeNull();
        expect(p.week_of_month).toBeNull();
    });

    test("monthly_nth_weekday sets week_of_month + day_of_week", () => {
        const p = buildRecurringEditPayload({ ...BASE, frequency: "monthly_nth_weekday" });
        expect(p.week_of_month).toBe(1);
        expect(p.day_of_week).toBe(2);
        expect(p.days_of_week).toBeNull();
        expect(p.day_of_month).toBeNull();
    });

    test("the #266 reported flow: weekly → multi-day clears day_of_week", () => {
        // The exact regression we verified in Phase 6: editing a weekly
        // template to multi-day must null out the old day_of_week.
        const p = buildRecurringEditPayload({ ...BASE, frequency: "multi_day_of_week", daysOfWeek: [0, 2] });
        expect(p.frequency).toBe("multi_day_of_week");
        expect(p.days_of_week).toEqual([0, 2]);
        expect(p.day_of_week).toBeNull();
    });

    test("missing input object is safe", () => {
        const p = buildRecurringEditPayload();
        expect(p.title).toBe("");
        expect(p.day_of_week).toBeNull();
    });
});
