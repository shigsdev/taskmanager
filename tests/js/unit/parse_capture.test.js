/**
 * Jest tests for parseCapture() — mirrors tests/test_capture_parse.py.
 *
 * This is the authoritative JS test suite for the capture parser. If
 * parse_capture.js changes, these tests must be updated to match, and
 * the Python mirror in test_capture_parse.py should be updated too.
 *
 * Run: npm test
 */
"use strict";

const { parseCapture } = require("../../../static/parse_capture");

// ---------------------------------------------------------------------------
// Tier shortcuts: #today, #week, #backlog, #freezer
// ---------------------------------------------------------------------------

describe("parseCapture — tier shortcuts", () => {
    test("default tier is inbox", () => {
        const r = parseCapture("Buy groceries");
        expect(r.tier).toBe("inbox");
        expect(r.title).toBe("Buy groceries");
    });

    test("#today sets tier to today", () => {
        const r = parseCapture("Fix bug #today");
        expect(r.tier).toBe("today");
        expect(r.title).toBe("Fix bug");
    });

    test("#week sets tier to this_week", () => {
        const r = parseCapture("Write docs #week");
        expect(r.tier).toBe("this_week");
        expect(r.title).toBe("Write docs");
    });

    test("#backlog sets tier to backlog", () => {
        const r = parseCapture("Learn Rust #backlog");
        expect(r.tier).toBe("backlog");
        expect(r.title).toBe("Learn Rust");
    });

    test("#freezer sets tier to freezer", () => {
        const r = parseCapture("Someday project #freezer");
        expect(r.tier).toBe("freezer");
        expect(r.title).toBe("Someday project");
    });

    test("tier tag is case insensitive", () => {
        const r = parseCapture("Task #TODAY");
        expect(r.tier).toBe("today");
    });

    test("tier tag mid-string", () => {
        const r = parseCapture("Do #today the thing");
        expect(r.tier).toBe("today");
        expect(r.title).toBe("Do  the thing"); // double space is expected
    });
});

// ---------------------------------------------------------------------------
// Type shortcuts: #work, #personal
// ---------------------------------------------------------------------------

describe("parseCapture — type shortcuts", () => {
    test("#work sets type to work", () => {
        const r = parseCapture("Deploy app #work");
        expect(r.type).toBe("work");
        expect(r.title).toBe("Deploy app");
    });

    test("#personal sets type to personal", () => {
        const r = parseCapture("Call dentist #personal");
        expect(r.type).toBe("personal");
        expect(r.title).toBe("Call dentist");
    });

    test("type tag is case insensitive", () => {
        const r = parseCapture("Task #WORK");
        expect(r.type).toBe("work");
    });

    test("no type by default", () => {
        const r = parseCapture("Plain task");
        expect(r.type).toBeUndefined();
    });
});

// ---------------------------------------------------------------------------
// Repeat shortcuts: #daily, #weekdays, #weekly, #monthly
// ---------------------------------------------------------------------------

describe("parseCapture — repeat shortcuts", () => {
    test("#daily sets frequency to daily", () => {
        const r = parseCapture("Standup #daily");
        expect(r.repeat.frequency).toBe("daily");
        expect(r.title).toBe("Standup");
    });

    test("#weekdays sets frequency to weekdays", () => {
        const r = parseCapture("Check email #weekdays");
        expect(r.repeat.frequency).toBe("weekdays");
        expect(r.title).toBe("Check email");
    });

    test("#weekly sets frequency to weekly with day_of_week", () => {
        const r = parseCapture("Team sync #weekly");
        expect(r.repeat.frequency).toBe("weekly");
        expect(r.repeat).toHaveProperty("day_of_week");
        expect(r.title).toBe("Team sync");
    });

    test("#monthly sets frequency to monthly_date with day_of_month", () => {
        const r = parseCapture("Budget review #monthly");
        expect(r.repeat.frequency).toBe("monthly_date");
        expect(r.repeat.day_of_month).toBe(new Date().getDate());
        expect(r.title).toBe("Budget review");
    });

    test("repeat tag is case insensitive", () => {
        const r = parseCapture("Task #DAILY");
        expect(r.repeat.frequency).toBe("daily");
    });
});

// ---------------------------------------------------------------------------
// URL detection and title extraction
// ---------------------------------------------------------------------------

describe("parseCapture — URL detection", () => {
    test("URL only — title falls back to URL", () => {
        const r = parseCapture("https://example.com/article");
        expect(r.url).toBe("https://example.com/article");
        expect(r.title).toBe("https://example.com/article");
    });

    test("URL with title before", () => {
        const r = parseCapture("Read this https://example.com/article");
        expect(r.url).toBe("https://example.com/article");
        expect(r.title).toBe("Read this");
        expect(r._titleProvided).toBe(true);
    });

    test("URL with title after", () => {
        const r = parseCapture("https://example.com good article");
        expect(r.url).toBe("https://example.com");
        expect(r.title).toBe("good article");
    });

    test("http:// URL (not just https://)", () => {
        const r = parseCapture("http://legacy.example.com");
        expect(r.url).toBe("http://legacy.example.com");
    });
});

// ---------------------------------------------------------------------------
// PREFIX COLLISION tests — these catch the bugs we found
// ---------------------------------------------------------------------------

describe("parseCapture — prefix collisions", () => {
    test("#weekly is NOT eaten by #week", () => {
        const r = parseCapture("Team sync #weekly");
        expect(r.repeat.frequency).toBe("weekly");
        expect(r.title).toBe("Team sync");
        // #week should NOT have matched — tier stays inbox
        expect(r.tier).toBe("inbox");
        // No leftover "ly" in the title
        expect(r.title).not.toContain("ly");
    });

    test("#weekdays is NOT eaten by #week", () => {
        const r = parseCapture("Standup #weekdays");
        expect(r.repeat.frequency).toBe("weekdays");
        expect(r.title).toBe("Standup");
        expect(r.tier).toBe("inbox");
        expect(r.title).not.toContain("days");
    });

    test("#weekly + #today both work independently", () => {
        const r = parseCapture("Sync #weekly #today");
        expect(r.repeat.frequency).toBe("weekly");
        expect(r.tier).toBe("today");
        expect(r.title).toBe("Sync");
    });

    test("#weekdays + #backlog both work", () => {
        const r = parseCapture("Email check #weekdays #backlog");
        expect(r.repeat.frequency).toBe("weekdays");
        expect(r.tier).toBe("backlog");
        expect(r.title).toBe("Email check");
    });

    test("#work is NOT eaten by #week", () => {
        const r = parseCapture("Deploy #work #today");
        expect(r.type).toBe("work");
        expect(r.tier).toBe("today");
        expect(r.title).toBe("Deploy");
    });

    test("#personal is checked before #work", () => {
        const r = parseCapture("Gym #personal");
        expect(r.type).toBe("personal");
        expect(r.title).toBe("Gym");
    });

    test("all shortcut types combined", () => {
        const r = parseCapture("Big task #daily #work #today");
        expect(r.repeat.frequency).toBe("daily");
        expect(r.type).toBe("work");
        expect(r.tier).toBe("today");
        expect(r.title).toBe("Big task");
    });

    test("URL + tier + type all parsed correctly", () => {
        const r = parseCapture("Read https://example.com #work #week");
        expect(r.url).toBe("https://example.com");
        expect(r.type).toBe("work");
        expect(r.tier).toBe("this_week");
        expect(r.title).toBe("Read");
    });
});

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

describe("parseCapture — edge cases", () => {
    test("empty string", () => {
        const r = parseCapture("");
        expect(r.title).toBe("");
        expect(r.tier).toBe("inbox");
    });

    test("only whitespace — title preserved (caller trims before calling)", () => {
        // Note: submitCapture() in capture.js calls input.value.trim()
        // before passing to parseCapture, so whitespace-only input never
        // reaches the parser in practice. The parser itself does not trim
        // its initial input.
        const r = parseCapture("   ");
        expect(r.title).toBe("   ");
        expect(r.tier).toBe("inbox");
    });

    test("multiple tier tags — last one wins", () => {
        // The tier loop doesn't break, so both match; last write wins
        const r = parseCapture("Task #today #backlog");
        expect(r.tier).toBe("backlog");
    });

    test("tag embedded in word is still matched", () => {
        // e.g. "my#today" — the includes() check will match
        const r = parseCapture("my#today task");
        expect(r.tier).toBe("today");
    });

    test("URL with query parameters preserved", () => {
        const r = parseCapture("https://example.com/path?q=test&page=2");
        expect(r.url).toBe("https://example.com/path?q=test&page=2");
    });

    test("URL with fragment preserved", () => {
        const r = parseCapture("https://example.com/page#section");
        expect(r.url).toBe("https://example.com/page#section");
    });
});
