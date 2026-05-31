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
const {
    bucketTasks,
    calendarReorderIds,
} = require("../../../static/calendar_bucket_helpers");

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

describe("bucketTasks — #231 subtask scheduling rules (refined 2026-05-25)", () => {
    test("scheduled subtask (parent_id + due_date set) IS rendered on its day, alongside the parent", () => {
        // User clarification 2026-05-25: "i did not want the subtasks to
        // go away from the calender ... they should be on the day i
        // scheduled them." If both parent and subtask happen to share a
        // due_date, both render on that day's cell — the user did the
        // explicit scheduling and deserves to see it.
        const tasks = [
            { id: "parent", title: "Ski trip", due_date: "2026-05-28", tier: "this_week", parent_id: null },
            { id: "sub", title: "Buy boots", due_date: "2026-05-28", tier: "this_week", parent_id: "parent" },
        ];
        const { byDate } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(byDate["2026-05-28"]).toHaveLength(2);
        const ids = byDate["2026-05-28"].map(t => t.id).sort();
        expect(ids).toEqual(["parent", "sub"]);
    });

    test("scheduled subtask on its OWN distinct day renders on that day", () => {
        // Parent on Thu, subtask explicitly scheduled to Mon — each lands
        // on its own day.
        const tasks = [
            { id: "p", title: "Move", due_date: "2026-05-28", tier: "this_week", parent_id: null },
            { id: "s", title: "Reserve truck", due_date: "2026-05-25", tier: "today", parent_id: "p" },
        ];
        const { byDate } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(byDate["2026-05-28"]).toHaveLength(1);
        expect(byDate["2026-05-28"][0].id).toBe("p");
        expect(byDate["2026-05-25"]).toHaveLength(1);
        expect(byDate["2026-05-25"][0].id).toBe("s");
    });

    test("subtask with tier=today (no due_date) renders on today's cell via the tier fallback", () => {
        // Same tier-fallback rule as for top-level tasks — a subtask
        // explicitly tier-routed to today/tomorrow is "scheduled" in the
        // user's mental model even without an explicit date.
        const tasks = [
            { id: "p", title: "Ship dark theme", due_date: TODAY, tier: "today", parent_id: null },
            { id: "s", title: "Audit nav CSS at 375px", due_date: null, tier: "today", parent_id: "p" },
        ];
        const { byDate, unscheduled } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(byDate[TODAY]).toHaveLength(2);
        expect(unscheduled).toHaveLength(0);
    });

    test("subtask with NO scheduled day is SUPPRESSED from Unscheduled (the actual user-reported bug)", () => {
        // Exact 2026-05-25 user repro: an unscheduled subtask (no
        // due_date, tier=backlog) used to surface as a standalone row in
        // the Unscheduled aside. The parent was already on a day cell, so
        // the user saw what felt like the same task in two places. After
        // the fix, the subtask is hidden from /calendar entirely (it
        // remains visible nested under its parent's detail card on the
        // home board).
        const tasks = [
            { id: "parent", title: "Ski trip", due_date: "2026-05-28", tier: "this_week", parent_id: null },
            { id: "sub", title: "Buy boots", due_date: null, tier: "backlog", parent_id: "parent" },
        ];
        const { byDate, unscheduled } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(byDate["2026-05-28"]).toHaveLength(1);
        expect(byDate["2026-05-28"][0].id).toBe("parent");
        expect(unscheduled).toHaveLength(0);
    });

    test("mixed bag: scheduled subtasks render on their days, unscheduled subtasks are hidden", () => {
        const tasks = [
            { id: "p", title: "Move", due_date: "2026-06-01", tier: "next_week", parent_id: null },
            { id: "s1", title: "Pack kitchen", due_date: null, tier: "backlog", parent_id: "p" },           // hidden
            { id: "s2", title: "Reserve truck", due_date: "2026-05-30", tier: "this_week", parent_id: "p" }, // visible on 5-30
            { id: "s3", title: "Forward mail", due_date: null, tier: "today", parent_id: "p" },             // visible today
        ];
        const { byDate, unscheduled } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(byDate["2026-06-01"]).toHaveLength(1);                    // parent
        expect(byDate["2026-06-01"][0].id).toBe("p");
        expect(byDate["2026-05-30"]).toHaveLength(1);                    // s2
        expect(byDate["2026-05-30"][0].id).toBe("s2");
        expect(byDate[TODAY]).toHaveLength(1);                           // s3
        expect(byDate[TODAY][0].id).toBe("s3");
        expect(unscheduled).toHaveLength(0);                             // s1 suppressed
    });

    test("parent_id === undefined (older serializer) is treated as top-level — still goes to Unscheduled when no day", () => {
        // Defensive: if a task row arrives without a parent_id key at all
        // (legacy data, partial response), we treat it as top-level.
        const tasks = [
            { id: "a", title: "Top-level no day", due_date: null, tier: "backlog" },
        ];
        const { byDate, unscheduled } = bucketTasks(tasks, TODAY, TOMORROW);
        expect(Object.keys(byDate)).toHaveLength(0);
        expect(unscheduled).toHaveLength(1);
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

describe("calendarReorderIds — within-cell drag-reorder math (#267)", () => {
    // Three rows, each ~20px tall, midpoints at 10 / 30 / 50.
    const items = [
        { id: "a", mid: 10 },
        { id: "b", mid: 30 },
        { id: "c", mid: 50 },
    ];

    test("drop above the first item → dragged goes to the front", () => {
        expect(calendarReorderIds(items, "c", 5)).toEqual(["c", "a", "b"]);
    });

    test("drop below the last item → dragged appended to the end", () => {
        expect(calendarReorderIds(items, "a", 60)).toEqual(["b", "c", "a"]);
    });

    test("drop into the gap between two items → inserted at that gap", () => {
        // y=35 sits just below b's midpoint (30) and above c's (50):
        // insert before c.
        expect(calendarReorderIds(items, "a", 35)).toEqual(["b", "a", "c"]);
    });

    test("dropping an item back on its own midpoint is a no-op order", () => {
        expect(calendarReorderIds(items, "b", 30)).toEqual(["a", "b", "c"]);
    });

    test("result preserves length and contains every id exactly once", () => {
        const out = calendarReorderIds(items, "b", 5);
        expect(out).toHaveLength(items.length);
        expect(new Set(out)).toEqual(new Set(["a", "b", "c"]));
    });

    test("two items — drop above vs below the single other row", () => {
        const two = [{ id: "a", mid: 10 }, { id: "b", mid: 30 }];
        expect(calendarReorderIds(two, "b", 5)).toEqual(["b", "a"]);   // above a
        expect(calendarReorderIds(two, "b", 25)).toEqual(["a", "b"]);  // below a's center
    });

    test("dragged id absent from items → inserted at the drop position (defensive)", () => {
        // In practice the dragged id is always one of the measured rows;
        // if it isn't, the helper still just inserts at the drop position.
        expect(calendarReorderIds(items, "zzz", 999)).toEqual(["a", "b", "c", "zzz"]); // below all → end
        expect(calendarReorderIds(items, "zzz", 5)).toEqual(["zzz", "a", "b", "c"]);   // above all → front
    });
});
