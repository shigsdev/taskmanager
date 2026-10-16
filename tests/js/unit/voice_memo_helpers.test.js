/**
 * Jest tests for static/voice_memo_helpers.js — #197 (anti-pattern #3).
 *
 * mimeTypeToExt was branchy classification logic inline in
 * voice_memo.js with no coverage. These exercise every branch.
 */
"use strict";

const { mimeTypeToExt } = require("../../../static/voice_memo_helpers");

describe("mimeTypeToExt", () => {
    test("audio/mp4 → mp4", () => {
        expect(mimeTypeToExt("audio/mp4")).toBe("mp4");
    });

    test("mp4 with codec params → mp4 (iOS Safari case)", () => {
        expect(mimeTypeToExt("audio/mp4;codecs=mp4a.40.2")).toBe("mp4");
    });

    test("audio/mpeg → mp3", () => {
        expect(mimeTypeToExt("audio/mpeg")).toBe("mp3");
    });

    test("audio/ogg → ogg", () => {
        expect(mimeTypeToExt("audio/ogg;codecs=opus")).toBe("ogg");
    });

    test("audio/wav → wav", () => {
        expect(mimeTypeToExt("audio/wav")).toBe("wav");
    });

    test("audio/webm → webm", () => {
        expect(mimeTypeToExt("audio/webm")).toBe("webm");
    });

    test("an unrecognised type falls back to webm", () => {
        expect(mimeTypeToExt("audio/flac")).toBe("webm");
    });

    test("empty string falls back to webm", () => {
        expect(mimeTypeToExt("")).toBe("webm");
    });

    test("null / undefined fall back to webm", () => {
        expect(mimeTypeToExt(null)).toBe("webm");
        expect(mimeTypeToExt(undefined)).toBe("webm");
    });

    test("matching is case-insensitive", () => {
        expect(mimeTypeToExt("AUDIO/MP4")).toBe("mp4");
    });

    test("first match wins — mp4 before the webm fallback", () => {
        // A type string containing "mp4" classifies as mp4 even with
        // other tokens present.
        expect(mimeTypeToExt("audio/mp4; codecs=mp4a")).toBe("mp4");
    });
});

// #470: Add All is one transaction on the server. An error the server
// answered saved nothing; a lost answer may have saved everything.
describe("confirmFailureTail (#470)", () => {
    const { confirmFailureTail } = require("../../../static/voice_memo_helpers");
    const answered = (status) => Object.assign(new Error("x"), { status, body: {} });

    test("the server answered (500, 429, 422): nothing was added — add again", () => {
        for (const status of [500, 429, 422]) {
            expect(confirmFailureTail(answered(status))).toBe(
                "Nothing was added, and your list is still here — Add All again.");
        }
    });

    test("no answer (lost connection): it may have landed — check first", () => {
        expect(confirmFailureTail(new TypeError("Failed to fetch"))).toBe(
            "Your list is still here. The connection dropped before the server answered, "
            + "so check your Inbox before adding again: it may already be there.");
        expect(confirmFailureTail(null)).toMatch(/check your Inbox/);
    });
});
