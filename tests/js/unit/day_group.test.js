/**
 * Unit tests for groupTasksByWeekday (static/day_group.js).
 * Pure function, no DOM needed — runs in Jest's default node env.
 */
"use strict";

const { groupTasksByWeekday } = require("../../../static/day_group.js");

// Helper: build a minimal task shape
function task(due_date, id) {
    return { id: id || due_date || "x", due_date: due_date || null };
}

describe("groupTasksByWeekday", () => {
    test("empty input returns empty array", () => {
        expect(groupTasksByWeekday([])).toEqual([]);
    });

    test("all tasks without due_date land in single 'No date' group", () => {
        const tasks = [task(null, "a"), task(null, "b")];
        const groups = groupTasksByWeekday(tasks);
        expect(groups).toHaveLength(1);
        expect(groups[0].label).toBe("No date");
        expect(groups[0].tasks).toHaveLength(2);
    });

    test("groups tasks by weekday, Monday-first order", () => {
        // 2026-04-20 = Monday, 2026-04-22 = Wednesday, 2026-04-24 = Friday
        const tasks = [
            task("2026-04-24", "fri"),
            task("2026-04-20", "mon"),
            task("2026-04-22", "wed"),
        ];
        const groups = groupTasksByWeekday(tasks);
        expect(groups.map((g) => g.label)).toEqual([
            "Monday", "Wednesday", "Friday",
        ]);
    });

    test("preserves per-day task order as given", () => {
        const t1 = task("2026-04-20", "first");
        const t2 = task("2026-04-20", "second");
        const t3 = task("2026-04-20", "third");
        const groups = groupTasksByWeekday([t1, t2, t3]);
        expect(groups).toHaveLength(1);
        expect(groups[0].tasks.map((t) => t.id)).toEqual(
            ["first", "second", "third"],
        );
    });

    test("Sunday renders last among days (Monday-first order)", () => {
        // 2026-04-19 is Sunday, 2026-04-20 is Monday, 2026-04-21 Tuesday
        const tasks = [
            task("2026-04-19", "sun"),
            task("2026-04-20", "mon"),
            task("2026-04-21", "tue"),
        ];
        const groups = groupTasksByWeekday(tasks);
        expect(groups.map((g) => g.label)).toEqual([
            "Monday", "Tuesday", "Sunday",
        ]);
    });

    test("empty days are omitted (no empty headings)", () => {
        // Only Tuesday + Friday → only those two headings
        const tasks = [task("2026-04-21", "tue"), task("2026-04-24", "fri")];
        const groups = groupTasksByWeekday(tasks);
        expect(groups).toHaveLength(2);
        expect(groups.map((g) => g.label)).toEqual(["Tuesday", "Friday"]);
    });

    test("mix of dated + undated — 'No date' comes last", () => {
        const tasks = [
            task(null, "u1"),
            task("2026-04-20", "mon"),
            task(null, "u2"),
        ];
        const groups = groupTasksByWeekday(tasks);
        expect(groups.map((g) => g.label)).toEqual(["Monday", "No date"]);
        expect(groups[1].tasks.map((t) => t.id)).toEqual(["u1", "u2"]);
    });

    test("malformed due_date string falls into 'No date' bucket", () => {
        // Don't crash — degrade gracefully
        const tasks = [task("not-a-date", "bad"), task("2026-04-20", "good")];
        const groups = groupTasksByWeekday(tasks);
        expect(groups.map((g) => g.label)).toEqual(["Monday", "No date"]);
    });

    test("date parsed as local-time, not UTC", () => {
        // 2026-04-20 should be Monday regardless of tz. If parsed as
        // UTC midnight, a PT viewer would get Sunday (UTC-7 rolls back).
        const tasks = [task("2026-04-20", "mon")];
        const groups = groupTasksByWeekday(tasks);
        expect(groups).toHaveLength(1);
        expect(groups[0].label).toBe("Monday");
    });
});
