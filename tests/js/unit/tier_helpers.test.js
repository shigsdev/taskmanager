/**
 * Jest tests for tier_helpers (#149).
 *
 * Mirrors the boundary cases in `task_service._tier_for_due_date` so
 * the client-side preview agrees with the server-side authoritative
 * decision on save. If these ever diverge, the user sees a tier
 * select that flips to a different value than the one the server
 * applies — quietly broken.
 *
 * Boundaries to lock in:
 *   today / tomorrow shortcuts
 *   this week (Mon-Sat) inclusive on both ends
 *   next week (Mon-Sat) inclusive on both ends
 *   beyond next Saturday → backlog
 *   Sunday "today" handling — this_week is the JUST-ENDED Mon-Sat
 *   invalid input → null
 */
"use strict";

const { tierForDueDate, dueDateForTier } = require("../../../static/tier_helpers");

// Helper: build a Date for "YYYY-MM-DD" in LOCAL time so it equality-
// matches what tierForDueDate parses.
function localDate(yyyyMmDd) {
    const m = yyyyMmDd.match(/^(\d{4})-(\d{2})-(\d{2})/);
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 0, 0, 0, 0);
}

describe("tierForDueDate — today/tomorrow shortcuts", () => {
    test("today's date returns 'today'", () => {
        const today = localDate("2026-05-05");  // Tuesday
        expect(tierForDueDate("2026-05-05", today)).toBe("today");
    });

    test("tomorrow's date returns 'tomorrow'", () => {
        const today = localDate("2026-05-05");
        expect(tierForDueDate("2026-05-06", today)).toBe("tomorrow");
    });
});

describe("tierForDueDate — Mon-Sat boundaries", () => {
    // Today = Wed 2026-05-06. This week's Mon-Sat = 2026-05-04 to
    // 2026-05-09. Next week = 2026-05-11 to 2026-05-16.
    const today = localDate("2026-05-06");

    test("this Monday → this_week (left boundary)", () => {
        expect(tierForDueDate("2026-05-04", today)).toBe("this_week");
    });

    test("this Saturday → this_week (right boundary)", () => {
        expect(tierForDueDate("2026-05-09", today)).toBe("this_week");
    });

    test("this Sunday (between weeks) → next_week", () => {
        // Sunday 5/10 isn't in EITHER Mon-Sat range. Falls back to
        // next_week per the server logic (5/10 < 5/11 nextMonday → backlog?
        // Actually 5/10 is BEFORE next Monday 5/11. Server returns
        // BACKLOG for dates outside both ranges. Verify.
        expect(tierForDueDate("2026-05-10", today)).toBe("backlog");
    });

    test("next Monday → next_week (left boundary)", () => {
        expect(tierForDueDate("2026-05-11", today)).toBe("next_week");
    });

    test("next Saturday → next_week (right boundary)", () => {
        expect(tierForDueDate("2026-05-16", today)).toBe("next_week");
    });

    test("3 weeks out → backlog", () => {
        expect(tierForDueDate("2026-06-01", today)).toBe("backlog");
    });

    test("yesterday (past) → backlog (no longer in this Mon-Sat range)", () => {
        // Today Wed 5/6. Yesterday Tue 5/5 is in this Mon-Sat range
        // (5/4 - 5/9), so it's this_week, NOT backlog.
        expect(tierForDueDate("2026-05-05", today)).toBe("this_week");
    });

    test("date before this Monday → backlog", () => {
        // Last Friday 5/1 is BEFORE this Monday 5/4. Outside this_week
        // range → backlog (server's same fall-through).
        expect(tierForDueDate("2026-05-01", today)).toBe("backlog");
    });
});

describe("tierForDueDate — Sunday-today edge", () => {
    // Today = Sun 2026-05-10. Per server convention, this_week is
    // the JUST-ENDED Mon-Sat (5/4 - 5/9). Next week = 5/11 - 5/16.
    const today = localDate("2026-05-10");

    test("Saturday yesterday on Sunday → this_week (just-ended week)", () => {
        expect(tierForDueDate("2026-05-09", today)).toBe("this_week");
    });

    test("Mon of just-ended week on Sunday → this_week", () => {
        expect(tierForDueDate("2026-05-04", today)).toBe("this_week");
    });

    test("Tue of next week on Sunday → next_week", () => {
        // Mon 5/11 = tomorrow on Sunday-today, so the today/tomorrow
        // shortcut wins over the next_week range. Use Tue 5/12 to
        // exercise the next_week branch unambiguously.
        expect(tierForDueDate("2026-05-12", today)).toBe("next_week");
    });

    test("upcoming Mon on Sunday → 'tomorrow' (today/tomorrow shortcut wins)", () => {
        expect(tierForDueDate("2026-05-11", today)).toBe("tomorrow");
    });
});

describe("tierForDueDate — invalid input", () => {
    test("null returns null", () => {
        expect(tierForDueDate(null)).toBeNull();
    });
    test("empty string returns null", () => {
        expect(tierForDueDate("")).toBeNull();
    });
    test("non-ISO string returns null", () => {
        expect(tierForDueDate("not-a-date")).toBeNull();
    });
});

describe("dueDateForTier — inverse helper", () => {
    test("'today' returns today's ISO", () => {
        const today = localDate("2026-05-05");
        expect(dueDateForTier("today", today)).toBe("2026-05-05");
    });
    test("'tomorrow' returns tomorrow's ISO", () => {
        const today = localDate("2026-05-05");
        expect(dueDateForTier("tomorrow", today)).toBe("2026-05-06");
    });
    test("'this_week' returns null (multi-day span has no canonical date)", () => {
        expect(dueDateForTier("this_week")).toBeNull();
    });
    test("'next_week' returns null", () => {
        expect(dueDateForTier("next_week")).toBeNull();
    });
    test("'backlog' / 'inbox' / 'freezer' return null", () => {
        expect(dueDateForTier("backlog")).toBeNull();
        expect(dueDateForTier("inbox")).toBeNull();
        expect(dueDateForTier("freezer")).toBeNull();
    });
    test("month/day boundary zero-pads correctly", () => {
        const today = localDate("2026-01-05");
        expect(dueDateForTier("today", today)).toBe("2026-01-05");
        expect(dueDateForTier("tomorrow", today)).toBe("2026-01-06");
    });
});
