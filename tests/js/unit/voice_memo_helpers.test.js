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
