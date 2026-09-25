/**
 * #335 — the pure logic behind reading several reflections together.
 *
 * All three of these produce COPY, which is the part only the client can
 * get wrong and the part that decides whether the user understands what
 * a paid button is about to do. The selection rule matters most: the
 * button's label and its enabled state are derived from one function, so
 * a disabled button can never sit under a label promising to run.
 */
"use strict";

const H = require("../../../static/reflection_helpers");

describe("combinedSelectionText — the selection bar", () => {
    test("nothing selected produces no bar at all", () => {
        const out = H.combinedSelectionText(0);
        expect(out.summary).toBe("");
        expect(out.enabled).toBe(false);
    });

    test("one selected says what is missing rather than failing later", () => {
        const out = H.combinedSelectionText(1);
        expect(out.summary).toMatch(/pick at least one more/);
        expect(out.enabled).toBe(false);
    });

    test("a workable set names the count in the button", () => {
        const out = H.combinedSelectionText(3);
        expect(out.buttonLabel).toBe("Analyze 3 together");
        expect(out.summary).toBe("3 reflections selected.");
        expect(out.enabled).toBe(true);
    });

    test("exactly at the cap is still allowed", () => {
        expect(H.combinedSelectionText(H.MAX_COMBINED).enabled).toBe(true);
    });

    test("over the cap refuses and explains why the limit exists", () => {
        // "Ten max" with no reason reads as an arbitrary restriction. The
        // real reason — the reply is capped however much goes in — is what
        // stops the user feeling cheated out of a bigger look-back.
        const out = H.combinedSelectionText(H.MAX_COMBINED + 1);
        expect(out.enabled).toBe(false);
        expect(out.summary).toContain("10 is the most");
        expect(out.summary).toMatch(/thinner answer/);
    });

    test("a custom cap overrides the default", () => {
        expect(H.combinedSelectionText(3, 2).enabled).toBe(false);
        expect(H.combinedSelectionText(2, 2).enabled).toBe(true);
    });

    test("the label and the enabled flag never disagree", () => {
        // The failure this prevents: a button reading "Analyze 12
        // together" that does nothing when pressed.
        for (let n = 0; n <= 12; n++) {
            const out = H.combinedSelectionText(n);
            if (out.enabled) {
                expect(out.buttonLabel).toBe("Analyze " + n + " together");
            } else {
                expect(out.buttonLabel).not.toMatch(/Analyze \d+ together/);
            }
        }
    });

    test("junk input degrades to the empty state rather than throwing", () => {
        expect(H.combinedSelectionText(null).enabled).toBe(false);
        expect(H.combinedSelectionText(undefined).summary).toBe("");
        expect(H.combinedSelectionText(-4).summary).toBe("");
        expect(H.combinedSelectionText("3").summary).toBe("");
    });
});

describe("combinedReviewNote — framing the proposals", () => {
    test("says how many sittings were read, and in full", () => {
        const out = H.combinedReviewNote(4);
        expect(out).toContain("Read across 4 reflections, in full.");
    });

    test("repeats that nothing happens until confirmed", () => {
        // Proposals drawn from weeks of material feel higher-stakes than
        // one week's; the reassurance is worth the words.
        expect(H.combinedReviewNote(3)).toMatch(/nothing changes until you confirm/);
    });

    test("truncation is stated, naming the sittings affected", () => {
        // The whole point of this feature is full transcripts. If one was
        // cut, the user must not believe otherwise.
        const out = H.combinedReviewNote(3, ["2026-09-14", "2026-09-21 · Week one"]);
        expect(out).toContain("2026-09-14, 2026-09-21 · Week one");
        expect(out).toContain("were");
        expect(out).toMatch(/shortened/);
    });

    test("one shortened sitting reads as singular", () => {
        expect(H.combinedReviewNote(2, ["2026-09-14"])).toContain("was");
    });

    test("no truncation says nothing about it", () => {
        expect(H.combinedReviewNote(3)).not.toMatch(/shortened/);
        expect(H.combinedReviewNote(3, [])).not.toMatch(/shortened/);
    });

    test("a zero or junk count produces no note", () => {
        expect(H.combinedReviewNote(0)).toBe("");
        expect(H.combinedReviewNote(null)).toBe("");
        expect(H.combinedReviewNote("4")).toBe("");
    });
});

describe("synthesisBadge — marking a combined row in history", () => {
    test("counts the sources it was built from", () => {
        expect(H.synthesisBadge({ synthesis_of: ["a", "b", "c"] }))
            .toBe("🔗 Combined analysis of 3 reflections");
    });

    test("one source reads as singular", () => {
        expect(H.synthesisBadge({ synthesis_of: ["a"] }))
            .toBe("🔗 Combined analysis of 1 reflection");
    });

    test("an ordinary reflection gets no badge", () => {
        expect(H.synthesisBadge({ synthesis_of: null })).toBe("");
        expect(H.synthesisBadge({ synthesis_of: [] })).toBe("");
        expect(H.synthesisBadge({})).toBe("");
    });

    test("junk input returns empty rather than throwing", () => {
        expect(H.synthesisBadge(null)).toBe("");
        expect(H.synthesisBadge("x")).toBe("");
        expect(H.synthesisBadge({ synthesis_of: "abc" })).toBe("");
    });
});
