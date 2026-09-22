/**
 * #327 — the pure decision logic of the transient on-device audio buffer.
 *
 * The IndexedDB plumbing itself is exercised against a REAL browser in
 * tests/e2e/pages.spec.js (fake-indexeddb would only test a shim). What
 * lives here is the logic that decides WHEN audio stops being allowed to
 * exist — which is the part the ADR's "temporary, then cleaned up"
 * promise actually rests on.
 */
"use strict";

const { isExpired, describeOrphan, RETENTION_MS } = require(
    "../../../static/audio_buffer"
);

describe("isExpired — the retention promise", () => {
    const NOW = 1_700_000_000_000;
    const HOUR = 60 * 60 * 1000;

    test("retention window is 24 hours", () => {
        expect(RETENTION_MS).toBe(24 * HOUR);
    });

    test("fresh audio is kept", () => {
        expect(isExpired(NOW - HOUR, NOW)).toBe(false);
        expect(isExpired(NOW - 23 * HOUR, NOW)).toBe(false);
    });

    test("past the window it expires", () => {
        expect(isExpired(NOW - 25 * HOUR, NOW)).toBe(true);
    });

    test("the boundary itself expires — 'temporary' must actually bite", () => {
        expect(isExpired(NOW - 24 * HOUR, NOW)).toBe(true);
        expect(isExpired(NOW - 24 * HOUR + 1, NOW)).toBe(false);
    });

    test("an UNDATABLE orphan is expired, never immortal", () => {
        // A record with no usable timestamp must not linger forever just
        // because we can't tell how old it is. Fail toward deletion.
        expect(isExpired(undefined, NOW)).toBe(true);
        expect(isExpired(null, NOW)).toBe(true);
        expect(isExpired(NaN, NOW)).toBe(true);
        expect(isExpired("yesterday", NOW)).toBe(true);
    });

    test("a custom window is honoured", () => {
        expect(isExpired(NOW - 2 * HOUR, NOW, HOUR)).toBe(true);
        expect(isExpired(NOW - 30 * 60 * 1000, NOW, HOUR)).toBe(false);
    });

    test("clock skew (future timestamp) is not expired", () => {
        expect(isExpired(NOW + HOUR, NOW)).toBe(false);
    });
});

describe("describeOrphan — what the recovery prompt says", () => {
    // Duration is estimated from BYTES, not wall-clock: the recording was
    // interrupted, so "started 9 hours ago" says nothing about how much
    // audio actually exists.
    const bytesFor = (seconds, bps = 32000) => (seconds * bps) / 8;

    test("minutes for a substantial recording", () => {
        expect(describeOrphan({ bytes: bytesFor(18 * 60) }))
            .toBe("about 18 minutes of audio");
    });

    test("singular minute", () => {
        expect(describeOrphan({ bytes: bytesFor(60) }))
            .toBe("about 1 minute of audio");
    });

    test("seconds for a short one", () => {
        expect(describeOrphan({ bytes: bytesFor(12) }))
            .toBe("about 12s of audio");
    });

    test("a tiny non-zero buffer never reads as '0s'", () => {
        expect(describeOrphan({ bytes: 16 })).toBe("about 1s of audio");
    });

    test("nothing buffered produces no prompt text", () => {
        expect(describeOrphan({ bytes: 0 })).toBe("");
        expect(describeOrphan(null)).toBe("");
        expect(describeOrphan({})).toBe("");
    });

    test("a different bitrate rescales the estimate", () => {
        // Same bytes, double the bitrate -> half the audio.
        const b = bytesFor(10 * 60, 32000);
        expect(describeOrphan({ bytes: b }, 32000)).toBe("about 10 minutes of audio");
        expect(describeOrphan({ bytes: b }, 64000)).toBe("about 5 minutes of audio");
    });

    test("a bogus bitrate falls back to the pinned default", () => {
        const b = bytesFor(10 * 60, 32000);
        expect(describeOrphan({ bytes: b }, 0)).toBe("about 10 minutes of audio");
        expect(describeOrphan({ bytes: b }, -1)).toBe("about 10 minutes of audio");
    });
});
