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

/**
 * #325 — the /reflection runway header.
 *
 * The countdown is the whole point of the feature, so its wording gets
 * real assertions: a passed milestone must SAY so rather than reading
 * "0 weeks left" forever, and a partially-configured milestone must
 * still show its name instead of blanking the header.
 */
describe("milestoneHeadline", () => {
    const { milestoneHeadline } = require("../../../static/reflection_helpers");

    const base = {
        configured: true, label: "New role", date: "2026-11-02",
        days_left: 41, weeks_left: 6, passed: false, warning: null,
    };

    test("unconfigured returns null so the header stays quiet", () => {
        expect(milestoneHeadline(null)).toBeNull();
        expect(milestoneHeadline({ configured: false })).toBeNull();
    });

    test("future milestone shows name, date and both units", () => {
        const h = milestoneHeadline(base);
        expect(h.title).toBe("Working toward: New role · 2 Nov 2026");
        expect(h.sub).toBe("6 weeks left · 41 days");
    });

    test("under a week drops the weeks half", () => {
        const h = milestoneHeadline({ ...base, days_left: 4, weeks_left: 1 });
        expect(h.sub).toBe("4 days left");
    });

    test("today and tomorrow read naturally, not '0 weeks'", () => {
        expect(milestoneHeadline({ ...base, days_left: 0, weeks_left: 0 }).sub)
            .toBe("That's today");
        expect(milestoneHeadline({ ...base, days_left: 1, weeks_left: 1 }).sub)
            .toBe("1 day left");
    });

    test("a PASSED milestone says so instead of clamping to zero", () => {
        const h = milestoneHeadline({
            ...base, days_left: -3, weeks_left: -1, passed: true,
        });
        expect(h.sub).toBe("That was 3 days ago");
        expect(h.sub).not.toContain("left");
    });

    test("passed today is worded separately from 'N days ago'", () => {
        expect(milestoneHeadline({
            ...base, days_left: 0, weeks_left: 0, passed: true,
        }).sub).toBe("That was today");
    });

    test("singular day ago", () => {
        expect(milestoneHeadline({
            ...base, days_left: -1, weeks_left: -1, passed: true,
        }).sub).toBe("That was 1 day ago");
    });

    test("name but no date still renders — partial config isn't blank", () => {
        const h = milestoneHeadline({
            configured: true, label: "New role", date: null,
        });
        expect(h.title).toBe("Working toward: New role");
        expect(h.sub).toBe("No date set");
    });

    test("missing label falls back rather than printing 'undefined'", () => {
        const h = milestoneHeadline({ ...base, label: null });
        expect(h.title).toContain("your milestone");
        expect(h.title).not.toContain("undefined");
    });

    test("warning is surfaced for the caller to render", () => {
        const h = milestoneHeadline({ ...base, warning: "goal was deleted" });
        expect(h.warning).toBe("goal was deleted");
    });

    test("date formatting is locale-independent", () => {
        expect(milestoneHeadline({ ...base, date: "2026-01-01" }).title)
            .toContain("1 Jan 2026");
        expect(milestoneHeadline({ ...base, date: "2026-12-31" }).title)
            .toContain("31 Dec 2026");
    });

    test("a malformed date degrades to the raw string, not a crash", () => {
        const h = milestoneHeadline({ ...base, date: "not-a-date" });
        expect(h.title).toContain("not-a-date");
    });
});
