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
 *   this week (Mon-Sun ISO) inclusive on both ends
 *   next week (Mon-Sun ISO) inclusive on both ends
 *   beyond next Sunday → backlog
 *   Sunday "today" — last day of THIS_WEEK (#218: was just-ended Mon-Sat
 *                    under #72; orphaned Sunday-dated tasks to BACKLOG)
 *   invalid input → null
 */
"use strict";

const { tierForDueDate, dueDateForTier, tierForFiledDate, candidateSection } = require("../../../static/tier_helpers");

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

describe("tierForDueDate — Mon-Sun ISO-week boundaries (#218)", () => {
    // Today = Wed 2026-05-06. This week's Mon-Sun = 2026-05-04 to
    // 2026-05-10. Next week = 2026-05-11 to 2026-05-17.
    const today = localDate("2026-05-06");

    test("this Monday → this_week (left boundary)", () => {
        expect(tierForDueDate("2026-05-04", today)).toBe("this_week");
    });

    test("this Saturday → this_week (mid-week)", () => {
        expect(tierForDueDate("2026-05-09", today)).toBe("this_week");
    });

    test("this Sunday → this_week (right boundary — #218: was backlog under #72)", () => {
        // #218: Sunday is now the LAST day of THIS_WEEK. Under the old
        // Mon-Sat design (#72) a Sunday due_date fell outside both this
        // and next week ranges and was orphaned to BACKLOG — that's
        // the bug the user reported.
        expect(tierForDueDate("2026-05-10", today)).toBe("this_week");
    });

    test("next Monday → next_week (left boundary)", () => {
        expect(tierForDueDate("2026-05-11", today)).toBe("next_week");
    });

    test("next Saturday → next_week (mid-week)", () => {
        expect(tierForDueDate("2026-05-16", today)).toBe("next_week");
    });

    test("next Sunday → next_week (right boundary — #218: was backlog under #72)", () => {
        expect(tierForDueDate("2026-05-17", today)).toBe("next_week");
    });

    test("3 weeks out → backlog", () => {
        expect(tierForDueDate("2026-06-01", today)).toBe("backlog");
    });

    test("two days ago on Wed → this_week (in this Mon-Sun range)", () => {
        // Today Wed 5/6. Mon 5/4 is in this_week range. Still in week,
        // not backlog.
        expect(tierForDueDate("2026-05-04", today)).toBe("this_week");
    });

    test("date before this Monday → backlog", () => {
        // Last Friday 5/1 is BEFORE this Monday 5/4. Outside this_week
        // range → backlog (server's same fall-through).
        expect(tierForDueDate("2026-05-01", today)).toBe("backlog");
    });
});

describe("tierForDueDate — Sunday-today edge (#218 fix)", () => {
    // Today = Sun 2026-05-10. Under #218 Mon-Sun, today is the LAST day
    // of THIS_WEEK (5/4 - 5/10). Next week = 5/11 - 5/17.
    // Under the old #72 Mon-Sat, this_week was the just-ENDED 5/4-5/9
    // (Sunday was the planning pivot, OUTSIDE both weeks).
    const today = localDate("2026-05-10");

    test("today (Sunday) → 'today' (shortcut wins over this_week range)", () => {
        expect(tierForDueDate("2026-05-10", today)).toBe("today");
    });

    test("Saturday yesterday on Sunday → this_week", () => {
        expect(tierForDueDate("2026-05-09", today)).toBe("this_week");
    });

    test("Mon of this week on Sunday → this_week", () => {
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

    test("next Sunday on Sunday-today → next_week (#218: was backlog under #72)", () => {
        expect(tierForDueDate("2026-05-17", today)).toBe("next_week");
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

describe("tierForFiledDate — #386 overdue files to today", () => {
    // Today = Wed 2026-05-06 (this week Mon 05-04 .. Sun 05-10).
    const today = localDate("2026-05-06");

    test("yesterday (earlier this week) → 'today', not 'this_week'", () => {
        expect(tierForDueDate("2026-05-05", today)).toBe("this_week");
        expect(tierForFiledDate("2026-05-05", today)).toBe("today");
    });
    test("last month → 'today', not 'backlog'", () => {
        expect(tierForDueDate("2026-04-01", today)).toBe("backlog");
        expect(tierForFiledDate("2026-04-01", today)).toBe("today");
    });
    test("today / tomorrow / later agree with tierForDueDate", () => {
        for (const d of ["2026-05-06", "2026-05-07", "2026-05-09", "2026-05-13", "2026-06-30"]) {
            expect(tierForFiledDate(d, today)).toBe(tierForDueDate(d, today));
        }
    });
    test("accepts a Date as well as an ISO string", () => {
        expect(tierForFiledDate(localDate("2026-05-01"), today)).toBe("today");
        expect(tierForFiledDate(localDate("2026-05-12"), today)).toBe("next_week");
    });
    test("year boundary: Dec 31 is overdue on Jan 2", () => {
        expect(tierForFiledDate("2025-12-31", localDate("2026-01-02"))).toBe("today");
    });
    test("invalid input → null", () => {
        expect(tierForFiledDate("", today)).toBeNull();
        expect(tierForFiledDate("not-a-date", today)).toBeNull();
        expect(tierForFiledDate(null, today)).toBeNull();
    });
});

describe("candidateSection — #390 review-screen Section control", () => {
    // Today = Wed 2026-05-06 (this week Mon 05-04 .. Sun 05-10).
    const today = localDate("2026-05-06");

    test("a dated row shows the date's section and is locked", () => {
        expect(candidateSection("this_week", "2026-06-30", today))
            .toEqual({ tier: "backlog", setByDate: true });
        expect(candidateSection("inbox", "2026-05-07", today))
            .toEqual({ tier: "tomorrow", setByDate: true });
    });
    test("overdue → today (same as the server's filed-date rule)", () => {
        expect(candidateSection("backlog", "2026-04-01", today))
            .toEqual({ tier: "today", setByDate: true });
    });
    test("Freezer loses to the date on these paths", () => {
        expect(candidateSection("freezer", "2026-05-12", today))
            .toEqual({ tier: "next_week", setByDate: true });
    });
    test("no date → the row's own section, unlocked", () => {
        for (const d of [null, undefined, ""]) {
            expect(candidateSection("freezer", d, today))
                .toEqual({ tier: "freezer", setByDate: false });
        }
    });
    test("unparseable date → own section, unlocked", () => {
        expect(candidateSection("today", "soon", today))
            .toEqual({ tier: "today", setByDate: false });
    });
});
