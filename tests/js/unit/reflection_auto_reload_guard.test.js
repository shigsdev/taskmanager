/**
 * #331 - which capture states must block the service worker's
 * auto-reload.
 *
 * The incident: a deploy bumped CACHE_VERSION while the user was
 * dictating a reflection. base.html polls for a new service worker every
 * 60s and applies it immediately unless `userIsBusy()` objects - and that
 * guard only knew about a focused input/textarea/select or an open detail
 * panel. Someone SPEAKING has no focused field, so the page reloaded and
 * destroyed the live MediaRecorder mid-sentence.
 */
"use strict";

const H = require("../../../static/reflection_helpers");

describe("blocksAutoReload", () => {
    test("live audio blocks", () => {
        // The state the incident happened in.
        expect(H.blocksAutoReload("recording")).toBe(true);
    });

    test("an in-flight paid upload blocks", () => {
        // Reloading here abandons a Whisper call the user already paid for.
        expect(H.blocksAutoReload("transcribing")).toBe(true);
    });

    test("a paused session blocks", () => {
        // Text survives a reload, but the Resume affordance does not -
        // which is exactly what left the user stranded on 2026-09-24.
        expect(H.blocksAutoReload("paused")).toBe(true);
    });

    test("the voice-memo equivalents block too", () => {
        expect(H.blocksAutoReload("processing")).toBe(true);
        expect(H.blocksAutoReload("review")).toBe(true);
    });

    test("idle does not block", () => {
        // Nothing in flight: the update should apply silently, as before.
        expect(H.blocksAutoReload("idle")).toBe(false);
    });

    test("an errored segment does not block", () => {
        expect(H.blocksAutoReload("error")).toBe(false);
    });

    test("unknown and junk states do not block", () => {
        // Fail OPEN: a typo'd state must not wedge the updater forever,
        // leaving the user on stale code with no way to know.
        [undefined, null, "", "Recording", 1, {}, [], "done"].forEach((s) => {
            expect(H.blocksAutoReload(s)).toBe(false);
        });
    });

    test("the blocking set is exactly the documented five", () => {
        expect([...H.AUTO_RELOAD_BLOCKING_STATES].sort()).toEqual(
            ["paused", "processing", "recording", "review", "transcribing"]
        );
    });
});
