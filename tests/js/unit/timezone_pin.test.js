/**
 * #459: every Jest run is in the user's timezone (US Eastern), whatever the
 * machine's own zone — jest.config.js's globalSetup sets TZ before any
 * worker starts. Date bugs here are DST bugs (#424): a suite that ran in
 * UTC, or wherever CI happens to be, would never see a 23- or 25-hour day.
 * This file deliberately does NOT set TZ itself (dst_date_math.test.js
 * does, as a belt-and-braces for its own cases).
 */
"use strict";

test("Jest runs in America/New_York, with its DST change on 2026-11-01", () => {
    // EDT is UTC-4 before the change, EST is UTC-5 after.
    expect(new Date(2026, 9, 31, 12).getTimezoneOffset()).toBe(240);
    expect(new Date(2026, 10, 2, 12).getTimezoneOffset()).toBe(300);
});
