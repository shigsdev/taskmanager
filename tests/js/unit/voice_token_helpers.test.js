/**
 * Jest unit tests for static/voice_token_helpers.js (#499): the /settings
 * "Siri voice review" card — the header value, token ids, the lifetime
 * picker, list-row words and the Copy fallback for iOS.
 */
const {
    copyText,
    headerValue,
    normalizeJti,
    isValidJti,
    clampDays,
    tokenRowLabel,
    DEFAULT_DAYS,
} = require("../../../static/voice_token_helpers.js");

describe("headerValue", () => {
    test("is Bearer, a space, then the token", () => {
        expect(headerValue("abc.def")).toBe("Bearer abc.def");
    });
    test("trims what was in the field", () => {
        expect(headerValue("  abc.def\n")).toBe("Bearer abc.def");
    });
});

describe("token ids", () => {
    test("16 lowercase hex is an id", () => {
        expect(isValidJti("3f9a1c0b7d2e4a6f")).toBe(true);
    });
    test("a pasted jti= line, capitals and spaces are forgiven", () => {
        expect(normalizeJti("  jti=3F9A1C0B7D2E4A6F ")).toBe("3f9a1c0b7d2e4a6f");
        expect(isValidJti("jti=3F9A1C0B7D2E4A6F")).toBe(true);
    });
    test.each(["", "3f9a", "3f9a1c0b7d2e4a6fz", "3f9a1c0b7d2e4a6", "g".repeat(16), null, undefined])(
        "%p is not an id", (v) => {
            expect(isValidJti(v)).toBe(false);
        });
});

describe("clampDays", () => {
    test.each([[30, 30], ["90", 90], [180, 180], ["365", 365]])("%p → %p", (v, want) => {
        expect(clampDays(v)).toBe(want);
    });
    test.each([0, 7, 366, "x", null, undefined])("%p falls back to the default", (v) => {
        expect(clampDays(v)).toBe(DEFAULT_DAYS);
    });
});

describe("tokenRowLabel", () => {
    const now = new Date("2026-10-17T12:00:00Z");
    const base = {
        jti: "3f9a1c0b7d2e4a6f",
        minted: "2026-10-17T11:00:00+00:00",
        expires: "2027-01-15T11:00:00+00:00",
        revoked: null,
    };
    test("a live token is Active and can be revoked", () => {
        const l = tokenRowLabel(base, now);
        expect(l.state).toBe("Active");
        expect(l.canRevoke).toBe(true);
        expect(l.dates).toMatch(/^Made .+ · expires .+2027/);
    });
    test("a revoked token says so and can't be revoked again", () => {
        const l = tokenRowLabel({ ...base, revoked: "2026-10-17T11:30:00+00:00" }, now);
        expect(l.state).toBe("Revoked");
        expect(l.canRevoke).toBe(false);
    });
    test("an expired one (kept a day before pruning) reads Expired", () => {
        const l = tokenRowLabel({ ...base, expires: "2026-10-17T06:00:00+00:00" }, now);
        expect(l.state).toBe("Expired");
        expect(l.canRevoke).toBe(false);
    });
    test("missing dates read ? rather than Invalid Date", () => {
        const l = tokenRowLabel({ jti: base.jti }, now);
        expect(l.dates).toBe("Made ? · expires ?");
        expect(l.state).toBe("Active");
    });
});

describe("copyText", () => {
    function field() {
        return {
            focus: jest.fn(),
            select: jest.fn(),
            setSelectionRange: jest.fn(),
        };
    }

    test("navigator.clipboard → copied, no selection needed", async () => {
        const nav = { clipboard: { writeText: jest.fn().mockResolvedValue() } };
        const f = field();
        await expect(copyText("tok", f, { navigator: nav, document: {} })).resolves.toBe("copied");
        expect(nav.clipboard.writeText).toHaveBeenCalledWith("tok");
        expect(f.select).not.toHaveBeenCalled();
    });

    test("clipboard refused → select + execCommand copy", async () => {
        const nav = { clipboard: { writeText: jest.fn().mockRejectedValue(new Error("denied")) } };
        const doc = { execCommand: jest.fn().mockReturnValue(true) };
        const f = field();
        await expect(copyText("tok", f, { navigator: nav, document: doc })).resolves.toBe("copied");
        expect(f.setSelectionRange).toHaveBeenCalledWith(0, 3);
        expect(doc.execCommand).toHaveBeenCalledWith("copy");
    });

    test("no clipboard API and execCommand fails → selected (tap Copy)", async () => {
        const doc = { execCommand: jest.fn().mockReturnValue(false) };
        const f = field();
        await expect(copyText("tok", f, { navigator: {}, document: doc })).resolves.toBe("selected");
        expect(f.select).toHaveBeenCalled();
    });

    test("execCommand throwing still leaves it selected", async () => {
        const doc = { execCommand: jest.fn(() => { throw new Error("nope"); }) };
        await expect(copyText("tok", field(), { navigator: {}, document: doc })).resolves.toBe("selected");
    });

    test("nothing to select and nothing to copy with → failed", async () => {
        await expect(copyText("tok", null, { navigator: {}, document: {} })).resolves.toBe("failed");
    });

    test("writeText throwing synchronously falls back too", async () => {
        const nav = { clipboard: { writeText: () => { throw new Error("sync"); } } };
        const doc = { execCommand: jest.fn().mockReturnValue(true) };
        await expect(copyText("tok", field(), { navigator: nav, document: doc })).resolves.toBe("copied");
    });
});
