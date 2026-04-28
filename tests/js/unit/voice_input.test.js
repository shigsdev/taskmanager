/**
 * Jest unit tests for static/voice_input.js — closes the audit gap
 * that PR50 codified (anti-pattern #3: don't string-match, exercise
 * the path).
 */
const { voiceSupported, appendTranscript } = require("../../../static/voice_input");

describe("voiceSupported", () => {
    test("Node environment has no window → false", () => {
        // Node's global doesn't expose webkitSpeechRecognition / SpeechRecognition.
        // The helper checks `typeof window !== "undefined"` first; in Jest's
        // default jsdom env, window IS defined but neither API is.
        expect(voiceSupported()).toBe(false);
    });
});

describe("appendTranscript", () => {
    test("empty current + non-empty transcript → just the transcript", () => {
        expect(appendTranscript("", "hello world")).toBe("hello world");
    });
    test("empty current + empty transcript → empty string", () => {
        expect(appendTranscript("", "")).toBe("");
    });
    test("non-empty current + non-empty transcript → space-joined append", () => {
        expect(appendTranscript("buy milk", "and bread")).toBe("buy milk and bread");
    });
    test("trailing space in current is normalized (no double space)", () => {
        expect(appendTranscript("buy milk ", "and bread")).toBe("buy milk and bread");
    });
    test("multiple trailing whitespace also normalised", () => {
        expect(appendTranscript("hi   ", "there")).toBe("hi there");
    });
    test("transcript with leading/trailing whitespace is trimmed before append", () => {
        expect(appendTranscript("buy", "  milk  ")).toBe("buy milk");
    });
    test("empty transcript → currentValue unchanged", () => {
        expect(appendTranscript("buy milk", "")).toBe("buy milk");
        expect(appendTranscript("buy milk", "   ")).toBe("buy milk");
    });
    test("null/undefined currentValue → just transcript", () => {
        expect(appendTranscript(null, "hello")).toBe("hello");
        expect(appendTranscript(undefined, "hello")).toBe("hello");
    });
    test("null/undefined transcript → empty string when current is null", () => {
        expect(appendTranscript(null, null)).toBe("");
        expect(appendTranscript(undefined, undefined)).toBe("");
    });
});
