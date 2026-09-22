/**
 * Jest tests for the #324 resumable-draft helpers in reflection_helpers.
 *
 * These back a promise the user is relying on — that a reflection written
 * across several sittings is never silently lost — so the branches get
 * real output assertions, not a string-match (CLAUDE.md anti-pattern #3).
 */
"use strict";

const {
    shouldAutosaveDraft,
    formatSavedAt,
} = require("../../../static/reflection_helpers");

describe("shouldAutosaveDraft", () => {
    test("saves when the text changed", () => {
        expect(shouldAutosaveDraft("hello", "hello world")).toBe(true);
    });

    test("does NOT save when nothing changed", () => {
        // The debounce fires on every keystroke burst; re-PUTting identical
        // text is pure noise against the server.
        expect(shouldAutosaveDraft("hello", "hello")).toBe(false);
    });

    test("first-ever content saves (no previous save)", () => {
        expect(shouldAutosaveDraft(null, "my first words")).toBe(true);
    });

    test("empty box with nothing ever saved is a no-op", () => {
        // Landing on the page and clicking into an empty textarea must not
        // create a phantom draft row.
        expect(shouldAutosaveDraft(null, "")).toBe(false);
        expect(shouldAutosaveDraft(null, "   ")).toBe(false);
    });

    test("CLEARING existing text does save — the erase was deliberate", () => {
        // The asymmetry that matters: if the user selects-all and deletes,
        // that intent must persist, or the old text resurrects on reload.
        expect(shouldAutosaveDraft("a week of notes", "")).toBe(true);
    });

    test("whitespace-only edit over existing text still saves", () => {
        expect(shouldAutosaveDraft("notes", "   ")).toBe(true);
    });

    test("non-string inputs are treated as empty, not crashed", () => {
        expect(shouldAutosaveDraft(undefined, undefined)).toBe(false);
        expect(shouldAutosaveDraft(undefined, "text")).toBe(true);
        expect(() => shouldAutosaveDraft(5, {})).not.toThrow();
    });
});

describe("formatSavedAt", () => {
    const NOW = Date.parse("2026-09-22T12:00:00Z");
    const at = (iso) => formatSavedAt(iso, NOW);

    test("very recent reads as 'just now'", () => {
        expect(at("2026-09-22T11:59:57Z")).toBe("just now");
    });

    test("seconds, minutes, hours, days", () => {
        expect(at("2026-09-22T11:59:30Z")).toBe("30s ago");
        expect(at("2026-09-22T11:30:00Z")).toBe("30 mins ago");
        expect(at("2026-09-22T09:00:00Z")).toBe("3 hours ago");
        expect(at("2026-09-19T12:00:00Z")).toBe("3 days ago");
    });

    test("singular vs plural", () => {
        expect(at("2026-09-22T11:59:00Z")).toBe("1 min ago");
        expect(at("2026-09-22T11:00:00Z")).toBe("1 hour ago");
        expect(at("2026-09-21T12:00:00Z")).toBe("1 day ago");
    });

    test("a multi-day-old draft reports in days — the case that matters", () => {
        // Resuming something from last week should say so loudly, not
        // round to a vague 'a while ago'.
        expect(at("2026-09-15T12:00:00Z")).toBe("7 days ago");
    });

    test("future timestamp (clock skew) degrades to 'just now', not negative", () => {
        expect(at("2026-09-22T12:05:00Z")).toBe("just now");
    });

    test("missing / malformed input returns empty string", () => {
        expect(at(null)).toBe("");
        expect(at("")).toBe("");
        expect(at("not-a-date")).toBe("");
        expect(formatSavedAt(undefined, NOW)).toBe("");
    });

    test("falls back to the real clock when nowMs is omitted", () => {
        const iso = new Date(Date.now() - 2000).toISOString();
        expect(formatSavedAt(iso)).toBe("just now");
    });
});
