/**
 * #328 — the pure logic behind the reflection's context-file list.
 *
 * What is tested here is what the user READS: how an attachment is
 * described, whether truncation is stated out loud, and whether an
 * obviously-wrong pick is refused before a 10MB upload. The server
 * re-validates everything — the preflight is a courtesy, never the gate
 * — so these assert the MESSAGES, which is the part only the client can
 * get wrong.
 */
"use strict";

const H = require("../../../static/reflection_helpers");

describe("attachmentLabel — how one attached file reads", () => {
    test("name and meta come back separately so the DOM can style them", () => {
        const out = H.attachmentLabel({
            filename: "job-description.pdf", kind: "pdf", chars: 4200,
        });
        expect(out.name).toBe("job-description.pdf");
        expect(out.meta).toBe("PDF · 4,200 characters");
    });

    test("character counts are grouped at every magnitude", () => {
        expect(H.attachmentLabel({ filename: "a", kind: "txt", chars: 999 }).meta)
            .toBe("TXT · 999 characters");
        expect(H.attachmentLabel({ filename: "a", kind: "txt", chars: 1000 }).meta)
            .toBe("TXT · 1,000 characters");
        expect(
            H.attachmentLabel({ filename: "a", kind: "txt", chars: 1234567 }).meta
        ).toBe("TXT · 1,234,567 characters");
    });

    test("truncation is stated, with the original size", () => {
        // The whole point: a user must never believe Claude read all 84k
        // characters when it only got 20k.
        const out = H.attachmentLabel({
            filename: "handbook.pdf", kind: "pdf",
            chars: 20000, source_chars: 84312, truncated: true,
        });
        expect(out.meta).toBe(
            "PDF · 20,000 characters (shortened from 84,312)"
        );
    });

    test("truncated without a usable original still says shortened", () => {
        const out = H.attachmentLabel({
            filename: "x.pdf", kind: "pdf", chars: 20000, truncated: true,
        });
        expect(out.meta).toBe("PDF · 20,000 characters (shortened)");
    });

    test("a missing filename never renders as blank", () => {
        expect(H.attachmentLabel({ kind: "txt", chars: 5 }).name)
            .toBe("attachment");
        expect(H.attachmentLabel({ filename: "   ", chars: 5 }).name)
            .toBe("attachment");
    });

    test("zero chars and unknown kind degrade quietly", () => {
        const out = H.attachmentLabel({ filename: "mystery" });
        expect(out.name).toBe("mystery");
        expect(out.meta).toBe("");
    });

    test("junk input returns empty rather than throwing", () => {
        expect(H.attachmentLabel(null)).toBe("");
        expect(H.attachmentLabel(undefined)).toBe("");
        expect(H.attachmentLabel("a string")).toBe("");
    });
});

describe("attachmentSummary — the budget line", () => {
    test("stays silent with nothing attached", () => {
        // A fresh reflection should show an invitation, not an empty
        // state announcing "0 of 5 files".
        expect(H.attachmentSummary([], 5, 60000)).toBe("");
        expect(H.attachmentSummary(null, 5, 60000)).toBe("");
    });

    test("singular for one file", () => {
        expect(H.attachmentSummary([{ chars: 1200 }], 5, 60000)).toBe(
            "1 of 5 file · 1,200 of 60,000 characters of context"
        );
    });

    test("sums the characters across files", () => {
        expect(
            H.attachmentSummary([{ chars: 1200 }, { chars: 800 }], 5, 60000)
        ).toBe("2 of 5 files · 2,000 of 60,000 characters of context");
    });

    test("a file with no char count doesn't corrupt the total", () => {
        expect(
            H.attachmentSummary([{ chars: 1000 }, {}, { chars: null }], 5, 60000)
        ).toBe("3 of 5 files · 1,000 of 60,000 characters of context");
    });

    test("falls back to the shipped caps when none are supplied", () => {
        expect(H.attachmentSummary([{ chars: 10 }])).toBe(
            "1 of 5 file · 10 of 60,000 characters of context"
        );
    });
});

describe("attachmentPreflight — refusing an obviously-wrong pick", () => {
    const ok = { name: "plan.md", size: 2048 };

    test("accepts every supported extension", () => {
        H.ATTACHMENT_EXTENSIONS.forEach((ext) => {
            expect(
                H.attachmentPreflight({ name: "file" + ext, size: 10 })
            ).toBeNull();
        });
    });

    test("extension matching is case-insensitive", () => {
        expect(H.attachmentPreflight({ name: "OFFER.PDF", size: 10 })).toBeNull();
        expect(H.attachmentPreflight({ name: "Photo.JPEG", size: 10 })).toBeNull();
    });

    test("rejects an unsupported type and says what IS supported", () => {
        const msg = H.attachmentPreflight({ name: "payload.exe", size: 10 });
        expect(msg).toMatch(/isn't supported/);
        expect(msg).toContain(".pdf");
    });

    test("a bare extension as the whole filename is not a match", () => {
        // ".pdf" alone is a dotfile, not a PDF — endsWith() would say yes.
        expect(H.attachmentPreflight({ name: ".pdf", size: 10 }))
            .toMatch(/isn't supported/);
    });

    test("an extension appearing mid-name is not a match", () => {
        expect(H.attachmentPreflight({ name: "report.pdf.exe", size: 10 }))
            .toMatch(/isn't supported/);
    });

    test("rejects an oversize file with the cap in megabytes", () => {
        const msg = H.attachmentPreflight(
            { name: "huge.pdf", size: 11 * 1024 * 1024 }, 10 * 1024 * 1024
        );
        expect(msg).toBe("That file is too large (max 10 MB).");
    });

    test("a file exactly at the cap is allowed", () => {
        expect(
            H.attachmentPreflight({ name: "edge.pdf", size: 10 }, 10)
        ).toBeNull();
    });

    test("rejects an empty file", () => {
        expect(H.attachmentPreflight({ name: "blank.txt", size: 0 }))
            .toBe("That file is empty.");
    });

    test("no file selected is refused rather than uploaded", () => {
        expect(H.attachmentPreflight(null)).toBe("No file selected.");
    });

    test("a file with no size property is allowed through to the server", () => {
        // Some browsers omit size; the server has the real cap, so the
        // client must not invent a failure here.
        expect(H.attachmentPreflight({ name: "x.md" })).toBeNull();
    });

    test("a custom allow-list overrides the default", () => {
        expect(H.attachmentPreflight(ok, 999999, [".pdf"]))
            .toMatch(/isn't supported/);
        expect(H.attachmentPreflight(ok, 999999, [".md"])).toBeNull();
    });
});
