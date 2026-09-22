/**
 * Jest tests for static/recurring_helpers.js — the #266 recurring-editor
 * payload shaper. The load-bearing behaviour: each frequency sets only
 * its own day fields, and ALL four frequency-specific fields are always
 * present (null when not relevant) so switching frequency clears the
 * stale shape server-side.
 */
"use strict";

const {
    buildRecurringEditPayload,
    blankRecurringDraft,
    recurringSubmitTarget,
} = require("../../../static/recurring_helpers");

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


/**
 * #323 — creating a template from /recurring. The same panel now serves
 * both verbs, so the create-vs-edit split and the blank draft's defaults
 * are real branches that need real assertions.
 */
describe("recurringSubmitTarget", () => {
    test("no id → POST the collection (create)", () => {
        expect(recurringSubmitTarget(null)).toEqual({
            method: "POST", url: "/api/recurring",
        });
    });

    test("an id → PATCH that template (edit)", () => {
        expect(recurringSubmitTarget("abc-123")).toEqual({
            method: "PATCH", url: "/api/recurring/abc-123",
        });
    });

    test("blank / whitespace id counts as create, not PATCH /api/recurring/", () => {
        // A stray "" must not build "/api/recurring/" — that's a 404 route,
        // and silently failing to save is worse than obviously creating.
        for (const blank of ["", "   ", undefined, null]) {
            expect(recurringSubmitTarget(blank).method).toBe("POST");
            expect(recurringSubmitTarget(blank).url).toBe("/api/recurring");
        }
    });

    test("id is trimmed into the URL", () => {
        expect(recurringSubmitTarget("  xyz  ").url).toBe("/api/recurring/xyz");
    });
});

describe("blankRecurringDraft", () => {
    test("empty text fields and safe frequency/type defaults", () => {
        const d = blankRecurringDraft(new Date(2026, 8, 22));  // Tue 22 Sep 2026
        expect(d.title).toBe("");
        expect(d.url).toBe("");
        expect(d.notes).toBe("");
        expect(d.endDate).toBe("");
        expect(d.projectId).toBe("");
        expect(d.goalId).toBe("");
        expect(d.frequency).toBe("daily");
        expect(d.type).toBe("work");
        expect(d.daysOfWeek).toEqual([]);
        expect(d.weekOfMonth).toBe(1);
    });

    test("dayOfWeek uses 0=Monday, NOT JS getDay()'s 0=Sunday", () => {
        // The app stores Python weekday() convention. Getting this wrong
        // schedules every new weekly template one day early.
        expect(blankRecurringDraft(new Date(2026, 8, 21)).dayOfWeek).toBe(0); // Mon
        expect(blankRecurringDraft(new Date(2026, 8, 22)).dayOfWeek).toBe(1); // Tue
        expect(blankRecurringDraft(new Date(2026, 8, 26)).dayOfWeek).toBe(5); // Sat
        expect(blankRecurringDraft(new Date(2026, 8, 27)).dayOfWeek).toBe(6); // Sun
    });

    test("dayOfMonth is today's date", () => {
        expect(blankRecurringDraft(new Date(2026, 8, 22)).dayOfMonth).toBe(22);
        expect(blankRecurringDraft(new Date(2026, 0, 1)).dayOfMonth).toBe(1);
    });

    test("falls back to the real clock when no date is injected", () => {
        const d = blankRecurringDraft();
        expect(d.dayOfWeek).toBeGreaterThanOrEqual(0);
        expect(d.dayOfWeek).toBeLessThanOrEqual(6);
        expect(d.dayOfMonth).toBeGreaterThanOrEqual(1);
        expect(d.dayOfMonth).toBeLessThanOrEqual(31);
    });

    test("a non-Date argument is ignored rather than crashing", () => {
        expect(() => blankRecurringDraft("2026-09-22")).not.toThrow();
        expect(blankRecurringDraft("2026-09-22").frequency).toBe("daily");
    });

    test("the draft feeds buildRecurringEditPayload into a valid create body", () => {
        // End-to-end on the pure layer: blank draft -> payload the POST
        // endpoint accepts (title is the only thing the user must supply).
        const d = blankRecurringDraft(new Date(2026, 8, 22));
        d.title = "  Water the plants  ";
        d.frequency = "weekly";
        const body = buildRecurringEditPayload(d);
        expect(body.title).toBe("Water the plants");   // trimmed
        expect(body.frequency).toBe("weekly");
        expect(body.type).toBe("work");
        expect(body.day_of_week).toBe(1);              // Tue
        expect(body.days_of_week).toBeNull();
        expect(body.day_of_month).toBeNull();
        expect(body.end_date).toBeNull();
    });
});
