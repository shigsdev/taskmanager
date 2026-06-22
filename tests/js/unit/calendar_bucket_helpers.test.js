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
    reorderTierWithCell,
    groupUnscheduledByTier,
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

describe("reorderTierWithCell — collision-free full-tier reorder (#279)", () => {
    test("partial cell: only the cell's tasks move; other-cell tasks stay put", () => {
        // Tier this_week = [A,B,C,D] (A on Mon, B+C on Tue, D on Thu).
        // Reorder the Tuesday cell B,C → C,B. A (Mon) and D (Thu) must NOT move.
        const tier = ["A", "B", "C", "D"];
        expect(reorderTierWithCell(tier, ["C", "B"])).toEqual(["A", "C", "B", "D"]);
    });

    test("whole-cell == whole-tier: the new order is applied directly", () => {
        expect(reorderTierWithCell(["A", "B", "C"], ["C", "A", "B"]))
            .toEqual(["C", "A", "B"]);
    });

    test("dragged task moved to the end of its cell sits after its cell-mates", () => {
        // Cell = B,C,E (positions 1,2,4 in tier [A,B,C,D,E]); D (position 3) is
        // in a DIFFERENT cell. Reorder the cell to C,E,B → the cell tasks fill
        // their original positions 1,2,4 (C,E,B), D keeps position 3.
        const tier = ["A", "B", "C", "D", "E"];
        const out = reorderTierWithCell(tier, ["C", "E", "B"]);
        expect(out).toEqual(["A", "C", "E", "D", "B"]);
        // B now comes after C and E in the full order.
        expect(out.indexOf("B")).toBeGreaterThan(out.indexOf("C"));
        expect(out.indexOf("B")).toBeGreaterThan(out.indexOf("E"));
        // D (other cell) keeps its slot — untouched by the Tuesday reorder.
        expect(out[3]).toBe("D");
    });

    test("result is a permutation — same ids, no loss/dup (→ distinct sort_order after 0..N renumber)", () => {
        const tier = ["t1", "t2", "t3", "t4", "t5"];
        const out = reorderTierWithCell(tier, ["t4", "t2"]); // reorder t2,t4 cell
        expect(out).toHaveLength(tier.length);
        expect(new Set(out)).toEqual(new Set(tier));
    });

    test("non-cell tasks keep their RELATIVE order", () => {
        const tier = ["A", "B", "C", "D", "E"];
        const out = reorderTierWithCell(tier, ["E", "B"]); // cell = B,E
        // A, C, D (non-cell) keep order A < C < D.
        expect(out.indexOf("A")).toBeLessThan(out.indexOf("C"));
        expect(out.indexOf("C")).toBeLessThan(out.indexOf("D"));
    });

    test("single-task cell is a no-op shape (still returns the full tier)", () => {
        expect(reorderTierWithCell(["A", "B", "C"], ["B"])).toEqual(["A", "B", "C"]);
    });
});

describe("groupUnscheduledByTier (#292)", () => {
    const mk = (id, tier) => ({ id, title: id, tier });

    test("splits into This Week / Next Week / Backlog & Freezer in order", () => {
        const groups = groupUnscheduledByTier([
            mk("b1", "backlog"),
            mk("tw1", "this_week"),
            mk("nw1", "next_week"),
            mk("f1", "freezer"),
            mk("tw2", "this_week"),
        ]);
        expect(groups.map((g) => g.key)).toEqual(["this_week", "next_week", "other"]);
        expect(groups[0].label).toBe("This Week · no day");
        expect(groups[0].tasks.map((t) => t.id)).toEqual(["tw1", "tw2"]);
        expect(groups[1].tasks.map((t) => t.id)).toEqual(["nw1"]);
        // backlog + freezer both fall into the catch-all "other" group
        expect(groups[2].tasks.map((t) => t.id)).toEqual(["b1", "f1"]);
    });

    test("omits empty groups (only backlog → single 'other' group)", () => {
        const groups = groupUnscheduledByTier([mk("b1", "backlog"), mk("b2", "backlog")]);
        expect(groups).toHaveLength(1);
        expect(groups[0].key).toBe("other");
        expect(groups[0].tasks).toHaveLength(2);
    });

    test("only this_week → single labeled group, no 'other'", () => {
        const groups = groupUnscheduledByTier([mk("tw1", "this_week")]);
        expect(groups.map((g) => g.key)).toEqual(["this_week"]);
    });

    test("inbox / unknown tiers fall into 'other'", () => {
        const groups = groupUnscheduledByTier([mk("i1", "inbox"), mk("x1", "weird")]);
        expect(groups).toHaveLength(1);
        expect(groups[0].key).toBe("other");
        expect(groups[0].tasks.map((t) => t.id)).toEqual(["i1", "x1"]);
    });

    test("empty / non-array input → empty array", () => {
        expect(groupUnscheduledByTier([])).toEqual([]);
        expect(groupUnscheduledByTier(null)).toEqual([]);
        expect(groupUnscheduledByTier(undefined)).toEqual([]);
    });
});
