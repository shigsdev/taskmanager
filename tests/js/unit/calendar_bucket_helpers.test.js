/**
 * Jest unit tests for static/calendar_bucket_helpers.js (#231).
 *
 * Closes the gap that let two /calendar bugs ship together:
 *   1. Subtasks appeared as their own top-level rows on the grid AND
 *      in the Unscheduled aside (duplicate-looking rows).
 *   2. The bucketing was inline-IIFE'd inside calendar.js so it was
 *      only exercised by Playwright; no fast Jest regression net.
 *
 * The helper is dual-exported (window + module.exports) — same code path
 * runs in production and in this test.
 */
const { bucketTasks } = require("../../../static/calendar_bucket_helpers");

const TODAY = "2026-05-25";
const TOMORROW = "2026-05-26";

describe("bucketTasks — basic routing", () => {
    test("task with explicit due_date lands in that day's cell", () => {
        const tasks = [
            { id: "a", title: "Pay rent", due_date: "2026-05-28", tier: "this_week", parent_id: null },
        ];
        const { byDate, unscheduled } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(byDate["2026-05-28"]).toHaveLength(1);
        expect(byDate["2026-05-28"][0].title).toBe("Pay rent");
        expect(unscheduled).toHaveLength(0);
    });

    test("task with no due_date and tier=backlog lands in Unscheduled", () => {
        const tasks = [
            { id: "a", title: "Research dishwashers", due_date: null, tier: "backlog", parent_id: null },
        ];
        const { byDate, unscheduled } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(Object.keys(byDate)).toHaveLength(0);
        expect(unscheduled).toHaveLength(1);
        expect(unscheduled[0].title).toBe("Research dishwashers");
    });

    test("multiple tasks with same due_date share a cell", () => {
        const tasks = [
            { id: "a", title: "A", due_date: "2026-05-28", tier: "this_week", parent_id: null },
            { id: "b", title: "B", due_date: "2026-05-28", tier: "this_week", parent_id: null },
        ];
        const { byDate } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(byDate["2026-05-28"]).toHaveLength(2);
    });
});

describe("bucketTasks — tier fallback (#100 / PR29)", () => {
    test("tier=today with no due_date falls into today's cell", () => {
        const tasks = [
            { id: "a", title: "Standup", due_date: null, tier: "today", parent_id: null },
        ];
        const { byDate, unscheduled } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(byDate[TODAY]).toHaveLength(1);
        expect(unscheduled).toHaveLength(0);
    });

    test("tier=tomorrow with no due_date falls into tomorrow's cell", () => {
        const tasks = [
            { id: "a", title: "Dentist", due_date: null, tier: "tomorrow", parent_id: null },
        ];
        const { byDate, unscheduled } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(byDate[TOMORROW]).toHaveLength(1);
        expect(unscheduled).toHaveLength(0);
    });

    test("tier=this_week with no due_date stays in Unscheduled (multi-day tier)", () => {
        const tasks = [
            { id: "a", title: "Review PRs", due_date: null, tier: "this_week", parent_id: null },
        ];
        const { byDate, unscheduled } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(Object.keys(byDate)).toHaveLength(0);
        expect(unscheduled).toHaveLength(1);
    });

    test("explicit due_date wins over tier=today when both set", () => {
        const tasks = [
            { id: "a", title: "Pinned to Friday", due_date: "2026-05-29", tier: "today", parent_id: null },
        ];
        const { byDate } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(byDate["2026-05-29"]).toHaveLength(1);
        expect(byDate[TODAY]).toBeUndefined();
    });
});

describe("bucketTasks — #231 subtask exclusion", () => {
    test("subtask (parent_id set) is excluded from the day grid", () => {
        const tasks = [
            { id: "parent", title: "Ski trip", due_date: "2026-05-28", tier: "this_week", parent_id: null },
            { id: "sub", title: "Buy boots", due_date: "2026-05-28", tier: "this_week", parent_id: "parent" },
        ];
        const { byDate } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(byDate["2026-05-28"]).toHaveLength(1);
        expect(byDate["2026-05-28"][0].id).toBe("parent");
    });

    test("subtask with no due_date is excluded from Unscheduled — does NOT duplicate the parent's slot", () => {
        // This is the exact bug the user reported on 2026-05-24:
        // a subtask without its own due_date showed up as a standalone
        // row in the Unscheduled aside, looking like a duplicate of the
        // parent (which was on a day cell).
        const tasks = [
            { id: "parent", title: "Ski trip", due_date: "2026-05-28", tier: "this_week", parent_id: null },
            { id: "sub", title: "Buy boots", due_date: null, tier: "backlog", parent_id: "parent" },
        ];
        const { byDate, unscheduled } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(byDate["2026-05-28"]).toHaveLength(1);
        expect(unscheduled).toHaveLength(0);
    });

    test("multiple subtasks under one parent: only the parent renders", () => {
        const tasks = [
            { id: "p", title: "Move", due_date: "2026-06-01", tier: "this_week", parent_id: null },
            { id: "s1", title: "Pack kitchen", due_date: null, tier: "backlog", parent_id: "p" },
            { id: "s2", title: "Reserve truck", due_date: "2026-05-30", tier: "this_week", parent_id: "p" },
            { id: "s3", title: "Forward mail", due_date: null, tier: "today", parent_id: "p" },
        ];
        const { byDate, unscheduled } = bucketTasks(tasks, TODAY, TOMORROW);
        // Only the parent's cell, nothing else.
        expect(byDate["2026-06-01"]).toHaveLength(1);
        expect(byDate["2026-06-01"][0].id).toBe("p");
        expect(byDate[TODAY]).toBeUndefined();        // s3 would have landed here
        expect(byDate["2026-05-30"]).toBeUndefined(); // s2 would have landed here
        expect(unscheduled).toHaveLength(0);          // s1 would have landed here
    });

    test("parent_id === undefined (older serializer) is treated as top-level", () => {
        // Defensive: if a task row arrives without a parent_id key at all
        // (legacy data, partial response), we don't want to filter it out.
        const tasks = [
            { id: "a", title: "Top-level", due_date: "2026-05-28", tier: "this_week" },
        ];
        const { byDate } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(byDate["2026-05-28"]).toHaveLength(1);
    });

    test("parent_id === null is treated as top-level (the common case)", () => {
        const tasks = [
            { id: "a", title: "Top-level", due_date: "2026-05-28", tier: "this_week", parent_id: null },
        ];
        const { byDate } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(byDate["2026-05-28"]).toHaveLength(1);
    });
});

describe("bucketTasks — edge cases", () => {
    test("empty input → empty result", () => {
        const { byDate, unscheduled } = bucketTasks([], TODAY, TOMORROW);
        expect(Object.keys(byDate)).toHaveLength(0);
        expect(unscheduled).toHaveLength(0);
    });

    test("all-subtasks input → empty result (and crucially: no parent leaked in)", () => {
        const tasks = [
            { id: "s1", title: "Orphan-looking sub", due_date: null, tier: "backlog", parent_id: "missing-parent" },
        ];
        const { byDate, unscheduled } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(Object.keys(byDate)).toHaveLength(0);
        expect(unscheduled).toHaveLength(0);
    });
});
