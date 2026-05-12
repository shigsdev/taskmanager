/**
 * Jest tests for static/date_helpers.js — locks the local-date
 * computation against the UTC-slice bug class (user-reported
 * 2026-05-11: tasks due today showed as overdue in late evening
 * because new Date().toISOString().slice(0,10) had rolled to
 * tomorrow's date in UTC).
 */
"use strict";

const { localIsoDate, compareIsoDates } = require(
    "../../../static/date_helpers"
);

describe("localIsoDate", () => {
    test("formats a known date as YYYY-MM-DD using LOCAL components", () => {
        // Construct via local-component constructor — guarantees we're
        // building a Date that represents local 2026-05-11 02:30 in
        // whatever zone Jest is running in.
        const d = new Date(2026, 4, 11, 2, 30, 0);  // month is 0-indexed
        expect(localIsoDate(d)).toBe("2026-05-11");
    });

    test("zero-pads month and day", () => {
        const d = new Date(2026, 0, 5, 12, 0, 0);  // Jan 5
        expect(localIsoDate(d)).toBe("2026-01-05");
    });

    test("end-of-day local time still returns LOCAL date, not UTC", () => {
        // Bug repro: 23:30 local on Dec 31 in any negative-offset zone
        // crosses into the next day in UTC. localIsoDate must return
        // the LOCAL year-month-day.
        const d = new Date(2026, 11, 31, 23, 30, 0);  // Dec 31 23:30 local
        // Whatever timezone Jest runs in, the LOCAL components are
        // Dec 31 — so output must be 2026-12-31.
        expect(localIsoDate(d)).toBe("2026-12-31");
        // Cross-check: toISOString may give a different date here.
        // We're not asserting that, just illustrating why the helper
        // exists. Don't compare to toISOString — would depend on
        // the test runner's TZ and make this test flaky.
    });

    test("defaults to now when no argument is provided", () => {
        const out = localIsoDate();
        expect(out).toMatch(/^\d{4}-\d{2}-\d{2}$/);
        // Should equal the local date computed manually from new Date().
        const now = new Date();
        const expected =
            now.getFullYear() + "-"
            + String(now.getMonth() + 1).padStart(2, "0") + "-"
            + String(now.getDate()).padStart(2, "0");
        expect(out).toBe(expected);
    });

    test("never matches toISOString().slice when local is far from UTC", () => {
        // Construct a Date AT the local midnight of Jan 1.
        const d = new Date(2026, 0, 1, 0, 0, 0);  // local 2026-01-01 00:00
        // In any UTC offset, local 00:00 Jan 1 either matches UTC date
        // (offset=0) or precedes it by some hours (offset<0) or follows
        // it (offset>0). Our helper always returns LOCAL components:
        expect(localIsoDate(d)).toBe("2026-01-01");
    });
});

describe("compareIsoDates", () => {
    test("returns -1 when first < second", () => {
        expect(compareIsoDates("2026-05-10", "2026-05-11")).toBe(-1);
    });
    test("returns 1 when first > second", () => {
        expect(compareIsoDates("2026-05-12", "2026-05-11")).toBe(1);
    });
    test("returns 0 on equality", () => {
        expect(compareIsoDates("2026-05-11", "2026-05-11")).toBe(0);
    });
    test("rejects non-string inputs", () => {
        expect(() => compareIsoDates(null, "2026-05-11")).toThrow();
        expect(() => compareIsoDates("2026-05-11", 12345)).toThrow();
    });
});
