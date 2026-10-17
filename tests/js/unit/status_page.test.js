/**
 * #204 option E: the off-Railway status page (status/index.html) decides
 * up / degraded / down from one /healthz poll. These assert its outputs.
 */
const S = require("../../../status/status_helpers.js");

const ok = { status: "ok", critical_failed: [], git_sha: "d975e5b992eb", checks: {
    database: "ok", digest: "ok", tls_expiry: "skipped: TLS_EXPIRY_HOST not set",
    digest_last_send: "warn: last sent 30h ago" } };

describe("classify", () => {
    test("unreachable (network error, CORS, timeout) → down", () => {
        expect(S.classify({ reached: false }).level).toBe("down");
        expect(S.classify(null).level).toBe("down");
        expect(S.classify({ reached: false }).headline).toMatch(/Railway may be down/);
    });

    test("answered without a health report → down", () => {
        expect(S.classify({ reached: true, httpStatus: 502, body: null }).level).toBe("down");
        expect(S.classify({ reached: true, httpStatus: 200, body: { hello: 1 } }).level).toBe("down");
    });

    test("every check ok / warn / skipped → up (warn alone isn't a problem)", () => {
        const c = S.classify({ reached: true, httpStatus: 200, body: ok });
        expect(c).toEqual({ level: "up", headline: "The app is up.", problems: [] });
    });

    test("a non-critical fail on a 200 → degraded, naming it", () => {
        const body = { ...ok, status: "fail", checks: { ...ok.checks, migrations: "fail: at a expected b" } };
        const c = S.classify({ reached: true, httpStatus: 200, body });
        expect(c.level).toBe("degraded");
        expect(c.problems).toEqual(["migrations: fail: at a expected b"]);
    });

    test("a critical fail (503) → down, naming it", () => {
        const body = { ...ok, status: "fail", critical_failed: ["database"],
            checks: { ...ok.checks, database: "fail: no connection" } };
        const c = S.classify({ reached: true, httpStatus: 503, body });
        expect(c.level).toBe("down");
        expect(c.headline).toBe("The app is running but unhealthy.");
        expect(c.problems).toEqual(["database: fail: no connection"]);
    });
});

describe("ago", () => {
    const now = Date.UTC(2026, 9, 17, 12, 0, 0);
    test.each([
        [now - 10 * 1000, "just now"],
        [now - 4 * 60 * 1000, "4 min ago"],
        [now - 3 * 3600 * 1000, "3 h ago"],
        [now - 3 * 86400 * 1000, "3 days ago"],
        [now + 5000, "just now"],          // a clock a little ahead
        [NaN, "never"],
    ])("%s → %s", (then, want) => {
        expect(S.ago(then, now)).toBe(want);
    });
});

describe("shortSha", () => {
    test("first 8 characters, or unknown", () => {
        expect(S.shortSha("d975e5b992eb20959629")).toBe("d975e5b9");
        expect(S.shortSha("dev")).toBe("unknown");
        expect(S.shortSha(undefined)).toBe("unknown");
    });
});
