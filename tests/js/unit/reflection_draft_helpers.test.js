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

describe("shouldAutosaveDraft — the voice audit trail (#330)", () => {
    // Why these exist: judging a save on TEXT ALONE is what made #330
    // unrepairable. A draft that was one segment behind stayed behind for
    // the rest of the sitting, because the visibilitychange safety net
    // asked "did the text change?", got no, and returned false.
    test("a segment landing with IDENTICAL text still saves", () => {
        // The repair path. The server holds 1 segment, we hold 2, and the
        // words are byte-identical (the user had already typed them).
        expect(shouldAutosaveDraft("same words", "same words", 1, 2)).toBe(true);
    });

    test("no drift means no save, exactly as before", () => {
        expect(shouldAutosaveDraft("same words", "same words", 2, 2)).toBe(false);
    });

    test("a shrink does NOT save", () => {
        // A shrink means the draft was reset; both counters move together
        // there. Saving on it would PUT a shorter list over a longer one.
        expect(shouldAutosaveDraft("same words", "same words", 3, 1)).toBe(false);
    });

    test("counts may be the arrays themselves, not just numbers", () => {
        // The caller holds an array; making it pass .length is one more
        // place to get it wrong.
        const seg = (n) => Array.from({ length: n }, (_, i) => ({ text: "s" + i }));
        expect(shouldAutosaveDraft("t", "t", seg(1), seg(2))).toBe(true);
        expect(shouldAutosaveDraft("t", "t", seg(2), seg(2))).toBe(false);
    });

    test("omitting the counts keeps the #324 text-only rule intact", () => {
        // Every pre-#330 caller passes two arguments. None of them may
        // change behaviour.
        expect(shouldAutosaveDraft("hello", "hello")).toBe(false);
        expect(shouldAutosaveDraft("hello", "hello world")).toBe(true);
        expect(shouldAutosaveDraft(null, "")).toBe(false);
        expect(shouldAutosaveDraft("notes", "")).toBe(true);
    });

    test("junk counts can neither manufacture nor suppress a save", () => {
        // A drifted count must never be the reason an empty box creates a
        // phantom draft, nor the reason a real text edit is skipped.
        [null, undefined, NaN, -1, "2", {}, () => 2].forEach((bad) => {
            expect(shouldAutosaveDraft(null, "", bad, bad)).toBe(false);
            expect(shouldAutosaveDraft("a", "b", bad, bad)).toBe(true);
            expect(shouldAutosaveDraft("a", "a", bad, bad)).toBe(false);
        });
    });

    test("a segment drift on a never-saved EMPTY box is still a no-op", () => {
        // Guards the ordering inside the helper: the empty-nothing-to-erase
        // rule has to win, or a stray count creates a draft from nothing.
        expect(shouldAutosaveDraft(null, "", 0, 3)).toBe(false);
        expect(shouldAutosaveDraft("", "   ", 0, 3)).toBe(false);
    });

    test("text change AND segment growth together save once", () => {
        // The normal voice path: a segment lands, appending its words.
        expect(shouldAutosaveDraft("one", "one two", 1, 2)).toBe(true);
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

/**
 * #326 — longer voice segments.
 *
 * The binding constraint is Whisper's 25MB per-request limit, which is a
 * SIZE limit; the clock cap is secondary comfort. These pin that
 * ordering and the "show the cap" timer, because being cut off
 * mid-sentence with no warning was the original complaint.
 */
describe("autoPauseReason", () => {
    const { autoPauseReason } = require("../../../static/reflection_helpers");
    const MB = 1024 * 1024;

    test("under both limits keeps recording", () => {
        expect(autoPauseReason(5 * MB, 20 * MB, 60000, 1800000)).toBeNull();
    });

    test("size limit stops recording", () => {
        expect(autoPauseReason(20 * MB, 20 * MB, 1000, 1800000)).toBe("size");
    });

    test("time limit stops recording", () => {
        expect(autoPauseReason(1 * MB, 20 * MB, 1800000, 1800000)).toBe("time");
    });

    test("SIZE wins when both are hit — it's the one that loses the audio", () => {
        // Blowing the byte budget means Whisper rejects the request
        // outright; running out of clock is merely an interruption.
        expect(autoPauseReason(30 * MB, 20 * MB, 9999999, 1800000)).toBe("size");
    });

    test("boundaries are inclusive — at the limit is AT the limit", () => {
        expect(autoPauseReason(20 * MB - 1, 20 * MB, 0, Infinity)).toBeNull();
        expect(autoPauseReason(20 * MB, 20 * MB, 0, Infinity)).toBe("size");
    });

    test("missing/!finite inputs never spuriously pause a recording", () => {
        expect(autoPauseReason(undefined, 20 * MB, undefined, 1800000)).toBeNull();
        expect(autoPauseReason(NaN, 20 * MB, NaN, 1800000)).toBeNull();
        expect(autoPauseReason(5 * MB, 0, 1000, 0)).toBeNull();
    });
});

describe("formatRecordingTime", () => {
    const { formatRecordingTime } = require("../../../static/reflection_helpers");
    const CAP = 30 * 60 * 1000;

    test("shows elapsed AND the cap, so the budget is visible", () => {
        const t = formatRecordingTime(90 * 1000, CAP, 120);
        expect(t.text).toBe("1:30 / 30:00");
        expect(t.warn).toBe(false);
        expect(t.remainingSec).toBe(28 * 60 + 30);
    });

    test("zero-pads seconds", () => {
        expect(formatRecordingTime(65 * 1000, CAP).text).toBe("1:05 / 30:00");
        expect(formatRecordingTime(0, CAP).text).toBe("0:00 / 30:00");
    });

    test("warns in the final two minutes, not before", () => {
        expect(formatRecordingTime((30 * 60 - 121) * 1000, CAP, 120).warn).toBe(false);
        expect(formatRecordingTime((30 * 60 - 120) * 1000, CAP, 120).warn).toBe(true);
        expect(formatRecordingTime((30 * 60 - 5) * 1000, CAP, 120).warn).toBe(true);
    });

    test("past the cap clamps remaining at 0 and stays warning", () => {
        const t = formatRecordingTime((31 * 60) * 1000, CAP, 120);
        expect(t.remainingSec).toBe(0);
        expect(t.warn).toBe(true);
    });

    test("no cap falls back to a plain count-up", () => {
        const t = formatRecordingTime(65 * 1000, null);
        expect(t.text).toBe("1:05");
        expect(t.warn).toBe(false);
        expect(t.remainingSec).toBeNull();
    });

    test("negative / non-finite elapsed reads 0:00 rather than garbage", () => {
        expect(formatRecordingTime(-5000, CAP).text).toBe("0:00 / 30:00");
        expect(formatRecordingTime(NaN, CAP).text).toBe("0:00 / 30:00");
    });

    test("long durations render minutes past 60 correctly", () => {
        expect(formatRecordingTime(75 * 60 * 1000, null).text).toBe("75:00");
    });
});
