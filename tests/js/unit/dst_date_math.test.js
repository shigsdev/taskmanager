/**
 * #424: the board's date math across a daylight-saving change.
 *
 * Adding n × 86400000 ms to a local midnight is not "n days later" when the
 * clocks change in between: on 2026-11-01 (25 hours long) midnight + 24 h is
 * 23:00 the SAME day, so "tomorrow" came out as today; in March, midnight +
 * 7 × 24 h lands at 01:00, past the next Monday, so next week's Monday fell
 * into Backlog. calendar.js fixed this for its grid in #345.
 *
 * The user is in US Eastern, so the timezone is pinned here. It must be set
 * before any Date is created; Node re-reads TZ when it changes.
 */
"use strict";

process.env.TZ = "America/New_York";

const { dueDateForTier, tierForDueDate, weekBounds } = require("../../../static/tier_helpers");
const { addDays, localIsoDate } = require("../../../static/date_helpers");

// Noon local on the given date: what a user's "now" looks like mid-day.
const day = (iso) => {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d, 12, 0, 0);
};

describe("timezone pin (#424)", () => {
    test("the suite really runs in Eastern time", () => {
        // EDT is UTC-4 before the change, EST is UTC-5 after.
        expect(day("2026-10-31").getTimezoneOffset()).toBe(240);
        expect(day("2026-11-02").getTimezoneOffset()).toBe(300);
    });
});

describe("dueDateForTier across a clock change (#424)", () => {
    test("Tomorrow on 2026-11-01 (clocks go back) is Nov 2, not Nov 1", () => {
        expect(dueDateForTier("tomorrow", day("2026-11-01"))).toBe("2026-11-02");
    });
    test("Tomorrow on 2027-03-14 (clocks go forward) is Mar 15", () => {
        expect(dueDateForTier("tomorrow", day("2027-03-14"))).toBe("2027-03-15");
    });
    test("Today is unchanged on both days", () => {
        expect(dueDateForTier("today", day("2026-11-01"))).toBe("2026-11-01");
        expect(dueDateForTier("today", day("2027-03-14"))).toBe("2027-03-14");
    });
});

describe("tierForDueDate across a clock change (#424)", () => {
    test("in the week before Nov 1, next Sunday (Nov 8) is next week", () => {
        expect(tierForDueDate("2026-11-08", day("2026-10-28"))).toBe("next_week");
        expect(tierForDueDate("2026-11-02", day("2026-10-28"))).toBe("next_week");
        expect(tierForDueDate("2026-11-01", day("2026-10-28"))).toBe("this_week");
        expect(tierForDueDate("2026-11-09", day("2026-10-28"))).toBe("backlog");
    });
    test("on Nov 1 itself, Nov 2 is tomorrow", () => {
        expect(tierForDueDate("2026-11-02", day("2026-11-01"))).toBe("tomorrow");
        expect(tierForDueDate("2026-11-01", day("2026-11-01"))).toBe("today");
    });
    test("in the week before Mar 14, next Monday (Mar 15) is next week", () => {
        expect(tierForDueDate("2027-03-15", day("2027-03-10"))).toBe("next_week");
        expect(tierForDueDate("2027-03-14", day("2027-03-10"))).toBe("this_week");
        expect(tierForDueDate("2027-03-21", day("2027-03-10"))).toBe("next_week");
    });
    test("on Mar 14 itself, Mar 15 is tomorrow", () => {
        expect(tierForDueDate("2027-03-15", day("2027-03-14"))).toBe("tomorrow");
    });
});

describe("weekBounds (#424)", () => {
    const iso = (b) => ({
        thisMonday: localIsoDate(b.thisMonday),
        thisSunday: localIsoDate(b.thisSunday),
        nextMonday: localIsoDate(b.nextMonday),
        nextSunday: localIsoDate(b.nextSunday),
    });
    test("the week of the November change", () => {
        expect(iso(weekBounds(day("2026-10-28")))).toEqual({
            thisMonday: "2026-10-26", thisSunday: "2026-11-01",
            nextMonday: "2026-11-02", nextSunday: "2026-11-08",
        });
    });
    test("on the November change day (a Sunday)", () => {
        expect(iso(weekBounds(day("2026-11-01")))).toEqual({
            thisMonday: "2026-10-26", thisSunday: "2026-11-01",
            nextMonday: "2026-11-02", nextSunday: "2026-11-08",
        });
    });
    test("the week of the March change", () => {
        expect(iso(weekBounds(day("2027-03-10")))).toEqual({
            thisMonday: "2027-03-08", thisSunday: "2027-03-14",
            nextMonday: "2027-03-15", nextSunday: "2027-03-21",
        });
    });
    test("every bound is a local midnight", () => {
        for (const d of ["2026-10-28", "2026-11-01", "2027-03-10", "2027-03-14"]) {
            for (const v of Object.values(weekBounds(day(d)))) {
                expect([v.getHours(), v.getMinutes()]).toEqual([0, 0]);
            }
        }
    });
});

describe("addDays (#424)", () => {
    test("14 consecutive days across Nov 1 are 14 distinct dates", () => {
        const start = new Date(2026, 9, 26);   // Mon Oct 26, local midnight
        const dates = Array.from({ length: 14 }, (_, i) => localIsoDate(addDays(start, i)));
        expect(new Set(dates).size).toBe(14);
        expect(dates[0]).toBe("2026-10-26");
        expect(dates[13]).toBe("2026-11-08");
    });
    test("across Mar 14 too", () => {
        const start = new Date(2027, 2, 8);
        expect(localIsoDate(addDays(start, 7))).toBe("2027-03-15");
        expect(addDays(start, 7).getHours()).toBe(0);
    });
    test("negative steps and month/year ends", () => {
        expect(localIsoDate(addDays(new Date(2026, 10, 2), -1))).toBe("2026-11-01");
        expect(localIsoDate(addDays(new Date(2026, 11, 31), 1))).toBe("2027-01-01");
    });
    test("does not change the Date it was given", () => {
        const d = new Date(2026, 10, 1);
        addDays(d, 3);
        expect(localIsoDate(d)).toBe("2026-11-01");
    });
});
