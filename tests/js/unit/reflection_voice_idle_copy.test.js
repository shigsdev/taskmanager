/**
 * #332 - what the Record tab says when it is not recording.
 *
 * The bug this prevents: a user returning to a half-finished reflection
 * (or bounced out by a page reload) saw "Start recording" sitting over
 * thousands of words they had already dictated, read it as "this will
 * start over", and stopped. The Record tab hides the transcript, so the
 * button and this note are the ONLY evidence the earlier work survived.
 * These assert the words the user actually reads.
 */
"use strict";

const H = require("../../../static/reflection_helpers");

describe("voiceIdleCopy - a genuinely new reflection", () => {
    test("says Start, and adds no note", () => {
        const c = H.voiceIdleCopy("");
        expect(c.label).toBe("Start recording");
        expect(c.note).toBe("");
        expect(c.resuming).toBe(false);
    });

    test("whitespace-only text is still new", () => {
        // A draft holding only a stray newline must not claim words exist.
        expect(H.voiceIdleCopy("   \n\t  ").label).toBe("Start recording");
        expect(H.voiceIdleCopy("   \n\t  ").note).toBe("");
    });

    test("junk input degrades to the new-reflection copy", () => {
        [null, undefined, 42, {}, []].forEach((bad) => {
            expect(H.voiceIdleCopy(bad).label).toBe("Start recording");
            expect(H.voiceIdleCopy(bad).resuming).toBe(false);
        });
    });
});

describe("voiceIdleCopy - resuming", () => {
    test("says Resume once there is anything at all", () => {
        const c = H.voiceIdleCopy("word");
        expect(c.label).toBe("Resume recording");
        expect(c.resuming).toBe(true);
    });

    test("the note states the size and that nothing is replaced", () => {
        const c = H.voiceIdleCopy("one two three four five");
        expect(c.note).toContain("5 words so far");
        expect(c.note).toContain("added to the end");
        // The load-bearing reassurance: the user's fear is losing work.
        expect(c.note).toContain("nothing you have already said is replaced");
    });

    test("one word is singular in both the note and the aria label", () => {
        const c = H.voiceIdleCopy("solo");
        expect(c.note).toContain("1 word so far");
        expect(c.note).not.toContain("1 words");
        expect(c.aria).toContain("1 word already captured");
    });

    test("word counts are grouped at thousands", () => {
        const c = H.voiceIdleCopy(Array(1234).fill("x").join(" "));
        expect(c.note).toContain("1,234 words so far");
        expect(c.aria).toContain("1,234 words already captured");
    });

    test("counts words, not characters, across messy whitespace", () => {
        const c = H.voiceIdleCopy("  one\n\ntwo\t\tthree   ");
        expect(c.note).toContain("3 words so far");
    });

    test("the aria label carries the same promise as the visible button", () => {
        const c = H.voiceIdleCopy("a b");
        expect(c.aria).toMatch(/^Resume recording/);
        expect(c.label).toBe("Resume recording");
    });
});
