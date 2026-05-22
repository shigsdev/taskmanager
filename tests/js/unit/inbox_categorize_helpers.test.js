/**
 * Jest tests for static/inbox_categorize_helpers.js.
 *
 * Bug under guard (user-reported 2026-05-22, BACKLOG #208): the
 * Auto-categorize Inbox Apply path always sent `due_date: null`, which
 * suppressed the server-side tier→date auto-fill — so every
 * auto-categorized Today task landed with NO due date.
 *
 * These exercise the actual decision logic (anti-pattern #3 — never a
 * string-match against source). `todayISO` is passed in so the date
 * math is deterministic without mocking the clock.
 */
"use strict";

const {
    addDaysIso,
    dueDateForTier,
    resolveDueForTier,
    shouldSendDue,
} = require("../../../static/inbox_categorize_helpers");

const TODAY = "2026-05-22"; // a Friday

describe("addDaysIso", () => {
    test("adds a day within a month", () => {
        expect(addDaysIso("2026-05-22", 1)).toBe("2026-05-23");
    });

    test("rolls across a month boundary", () => {
        expect(addDaysIso("2026-05-31", 1)).toBe("2026-06-01");
    });

    test("rolls across a year boundary", () => {
        expect(addDaysIso("2026-12-31", 1)).toBe("2027-01-01");
    });

    test("handles a leap day", () => {
        expect(addDaysIso("2028-02-28", 1)).toBe("2028-02-29");
    });

    test("zero-pads single-digit month and day", () => {
        expect(addDaysIso("2026-01-08", 1)).toBe("2026-01-09");
    });
});

describe("dueDateForTier — mirrors _auto_fill_tier_due_date", () => {
    test("today → today", () => {
        expect(dueDateForTier("today", TODAY)).toBe("2026-05-22");
    });

    test("tomorrow → today + 1", () => {
        expect(dueDateForTier("tomorrow", TODAY)).toBe("2026-05-23");
    });

    test.each(["this_week", "next_week", "backlog", "freezer"])(
        "%s → null (no server auto-fill for this tier)",
        (tier) => {
            expect(dueDateForTier(tier, TODAY)).toBeNull();
        },
    );

    test("an unknown tier → null", () => {
        expect(dueDateForTier("inbox", TODAY)).toBeNull();
        expect(dueDateForTier(undefined, TODAY)).toBeNull();
    });
});

describe("resolveDueForTier", () => {
    test("an explicit value wins and is NOT auto", () => {
        // Claude suggested a date — keep it, even for a Today row.
        expect(resolveDueForTier("2026-06-15", "today", TODAY)).toEqual({
            value: "2026-06-15", auto: false,
        });
    });

    test("no explicit value + today tier → derived + auto", () => {
        expect(resolveDueForTier(null, "today", TODAY)).toEqual({
            value: "2026-05-22", auto: true,
        });
    });

    test("no explicit value + tomorrow tier → derived + auto", () => {
        expect(resolveDueForTier("", "tomorrow", TODAY)).toEqual({
            value: "2026-05-23", auto: true,
        });
    });

    test("no explicit value + a non-auto-fill tier → empty, not auto", () => {
        expect(resolveDueForTier(null, "next_week", TODAY)).toEqual({
            value: "", auto: false,
        });
        expect(resolveDueForTier("", "backlog", TODAY)).toEqual({
            value: "", auto: false,
        });
    });
});

describe("shouldSendDue — apply-payload policy", () => {
    test("a real explicit value IS sent", () => {
        expect(shouldSendDue("2026-06-15", false)).toBe(true);
    });

    test("an auto-derived placeholder is OMITTED (server auto-fills)", () => {
        // The core #208 fix: a Today row showing the derived date must
        // NOT send due_date, so the server's auto-fill is the
        // authoritative source.
        expect(shouldSendDue("2026-05-22", true)).toBe(false);
    });

    test("an empty field is OMITTED", () => {
        expect(shouldSendDue("", false)).toBe(false);
        expect(shouldSendDue("", true)).toBe(false);
    });
});

describe("#208 end-to-end policy — a Today row Claude left dateless", () => {
    test("modal shows today, but Apply omits due_date so the server fills it", () => {
        // Claude returned suggested_due_date = null for a Today task.
        const resolved = resolveDueForTier(null, "today", TODAY);
        // The modal pre-fills the visible date so the user sees it.
        expect(resolved.value).toBe("2026-05-22");
        expect(resolved.auto).toBe(true);
        // ...but Apply must NOT send it — otherwise `due_date: <date>`
        // (or the old `null`) reaches the PATCH and, while a date would
        // technically work, omitting keeps the server as the single
        // authoritative source for the tier→date rule.
        expect(shouldSendDue(resolved.value, resolved.auto)).toBe(false);
    });

    test("a user override on that row IS sent", () => {
        // User typed their own date → the input listener clears the
        // auto flag → readRow treats it as explicit.
        expect(shouldSendDue("2026-07-01", false)).toBe(true);
    });
});
