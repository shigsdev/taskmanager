/**
 * #334 — the pure logic behind continuing a past reflection.
 *
 * What is tested here is what the user READS and what the client REFUSES.
 * The forking itself is server work with its own route tests; these cover
 * the two client-side branches that can only go wrong here:
 *
 *   1. The continuation banner. While writing a fork the screen looks
 *      identical to a restored draft, so the copy is the only thing
 *      telling the user those words are a past reflection's and that
 *      finishing will save a NEW row rather than overwrite the original.
 *   2. The pre-flight refusal. The server 409s when a draft holding work
 *      is already open; the client checks too so the user reads WHY
 *      before a request fires. Drafts are hard-deleted with no recycle
 *      bin, which is exactly why a false "go ahead" here would be costly.
 */
"use strict";

const H = require("../../../static/reflection_helpers");

// The lineage block the API serialises onto a continued row: exactly the
// fields reflectionLabel() reads.
const PARENT = {
    id: "p1",
    title: null,
    iso_week: "2026-W39",
    input_mode: "voice",
    created_at: "2026-09-21T14:05:00Z",
};

describe("continuationNote — the banner while writing a fork", () => {
    test("names the sitting and states that the original survives", () => {
        const out = H.continuationNote({ ...PARENT, title: "Sunday planning" });
        expect(out).toContain("Continuing Sunday planning");
        // The load-bearing half of the sentence. Without it the user has
        // no way to know they aren't editing the row they clicked.
        expect(out).toContain("NEW reflection");
        expect(out).toContain("left exactly as it is");
    });

    test("falls back to the generated label when unnamed", () => {
        // Same rule as the history row — one naming implementation.
        const out = H.continuationNote(PARENT);
        expect(out).toContain("Continuing " + H.reflectionLabel(PARENT));
        expect(out).toContain("2026-W39");
    });

    test("stays silent for a draft that is not a continuation", () => {
        // "" is also the signal to keep the banner hidden, so a plain
        // restored draft must never produce copy here.
        expect(H.continuationNote(null)).toBe("");
        expect(H.continuationNote(undefined)).toBe("");
    });

    test("junk input returns empty rather than throwing", () => {
        expect(H.continuationNote("a string")).toBe("");
        expect(H.continuationNote(42)).toBe("");
    });

    test("a lineage row with nothing to name it by stays silent", () => {
        // reflectionLabel always appends input_mode so a history row never
        // renders blank. Alone that safety net reads as the sentence
        // "Continuing typed" — worse than no banner at all.
        expect(H.continuationNote({})).toBe("");
        expect(H.continuationNote({ id: "p1", input_mode: "typed" })).toBe("");
        expect(H.continuationNote({ id: "p1", title: "   " })).toBe("");
    });
});

describe("lineageNote — the line under a forked history row", () => {
    test("points at the parent by its name", () => {
        expect(H.lineageNote({
            id: "c1", continued_from: { ...PARENT, title: "Sunday planning" },
        })).toBe("↳ continues Sunday planning");
    });

    test("uses the generated label when the parent is unnamed", () => {
        const out = H.lineageNote({ id: "c1", continued_from: PARENT });
        expect(out).toBe("↳ continues " + H.reflectionLabel(PARENT));
    });

    test("an ordinary reflection gets no lineage line", () => {
        expect(H.lineageNote({ id: "c1", continued_from: null })).toBe("");
        expect(H.lineageNote({ id: "c1" })).toBe("");
    });

    test("junk input returns empty rather than throwing", () => {
        expect(H.lineageNote(null)).toBe("");
        expect(H.lineageNote("x")).toBe("");
        expect(H.lineageNote({ continued_from: "not an object" })).toBe("");
        // Same guard as the banner: never "↳ continues typed".
        expect(H.lineageNote({ continued_from: {} })).toBe("");
    });
});

describe("continueBlockedReason — protecting an open draft", () => {
    test("no draft at all is fine", () => {
        expect(H.continueBlockedReason(null)).toBeNull();
        expect(H.continueBlockedReason(undefined)).toBeNull();
    });

    test("an empty shell left by the autosave loop is fine", () => {
        // The moment the user clears the box a row with "" exists. Refusing
        // on that would make Continue look broken for no reason.
        expect(H.continueBlockedReason({ transcript: "" })).toBeNull();
        expect(H.continueBlockedReason({ transcript: "   " })).toBeNull();
        expect(H.continueBlockedReason({
            transcript: "", raw_segments: [], context_files: [],
        })).toBeNull();
    });

    test("text blocks it and says so", () => {
        const msg = H.continueBlockedReason({ transcript: "Two hours of this." });
        expect(msg).toContain("already have a reflection in progress");
        expect(msg).toContain("text");
        expect(msg).toContain("Finish or discard");
    });

    test("recorded audio blocks it even with no text yet", () => {
        // Dictated-but-not-yet-typed work is the easiest thing to lose.
        const msg = H.continueBlockedReason({
            transcript: "", raw_segments: [{ text: "spoken" }],
        });
        expect(msg).toContain("recorded audio");
    });

    test("an attachment alone blocks it", () => {
        const msg = H.continueBlockedReason({
            transcript: "", context_files: [{ id: "a" }],
        });
        expect(msg).toContain("1 attached document");
    });

    test("several attachments are pluralised", () => {
        const msg = H.continueBlockedReason({
            transcript: "", context_files: [{ id: "a" }, { id: "b" }],
        });
        expect(msg).toContain("2 attached documents");
    });

    test("everything at once is listed in one sentence", () => {
        const msg = H.continueBlockedReason({
            transcript: "words",
            raw_segments: [{ text: "spoken" }],
            context_files: [{ id: "a" }],
        });
        expect(msg).toContain("text, recorded audio, 1 attached document");
    });

    test("non-array segment/file fields are ignored, not trusted", () => {
        // A malformed payload must not invent a block that strands the
        // user with no way to continue anything.
        expect(H.continueBlockedReason({
            transcript: "", raw_segments: "nope", context_files: 7,
        })).toBeNull();
    });

    test("a non-string transcript does not count as text", () => {
        expect(H.continueBlockedReason({ transcript: 12345 })).toBeNull();
    });
});
