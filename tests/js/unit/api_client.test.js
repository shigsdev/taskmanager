/**
 * Jest unit tests for static/api_client.js — closes the PR67 audit fix
 * #132 by exercising apiFetch's success + retry + 401 + error paths.
 *
 * Why these matter: 7 JS files now share this single wrapper; a regression
 * in retry / recovery / FormData detection here breaks every page at once.
 */
const apiClient = require("../../../static/api_client");
const { apiFetch, _resetRecoveryFlag } = apiClient;

beforeEach(() => {
    // Reset module-level state between tests so prompt singleton from
    // one test doesn't leak into the next.
    if (typeof _resetRecoveryFlag === "function") _resetRecoveryFlag();
    global.fetch = undefined;
    // Stub confirm so prompts don't block the test runner.
    global.confirm = jest.fn(() => false);
    global.setTimeout = (fn) => fn();  // collapse retry delays
});

afterEach(() => {
    jest.restoreAllMocks();
});

describe("apiFetch — success path", () => {
    test("GET returns parsed JSON on 200", async () => {
        global.fetch = jest.fn(async () => ({
            status: 200,
            ok: true,
            json: async () => ({ tasks: [{ id: "x" }] }),
        }));
        const data = await apiFetch("/api/tasks");
        expect(data).toEqual({ tasks: [{ id: "x" }] });
        expect(global.fetch).toHaveBeenCalledTimes(1);
    });

    test("204 No Content returns null", async () => {
        global.fetch = jest.fn(async () => ({ status: 204, ok: true }));
        const data = await apiFetch("/api/tasks/abc", { method: "DELETE" });
        expect(data).toBeNull();
    });
});

describe("apiFetch — JSON Content-Type defaulting", () => {
    test("default Content-Type is application/json", async () => {
        global.fetch = jest.fn(async () => ({
            status: 200, ok: true, json: async () => ({}),
        }));
        await apiFetch("/api/tasks");
        const callOpts = global.fetch.mock.calls[0][1];
        expect(callOpts.headers["Content-Type"]).toBe("application/json");
    });

    test("FormData body skips Content-Type so browser sets multipart boundary", async () => {
        global.fetch = jest.fn(async () => ({
            status: 200, ok: true, json: async () => ({}),
        }));
        const fd = new FormData();
        fd.append("file", "x");
        await apiFetch("/api/scan/upload", { method: "POST", body: fd });
        const callOpts = global.fetch.mock.calls[0][1];
        expect(callOpts.headers["Content-Type"]).toBeUndefined();
    });

    test("caller-provided Content-Type wins over default", async () => {
        global.fetch = jest.fn(async () => ({
            status: 200, ok: true, json: async () => ({}),
        }));
        await apiFetch("/api/x", { headers: { "Content-Type": "text/plain" } });
        expect(global.fetch.mock.calls[0][1].headers["Content-Type"]).toBe(
            "text/plain"
        );
    });
});

describe("apiFetch — TypeError auto-retry (PR47/PR67 stale-tab class)", () => {
    test("first TypeError triggers ONE retry; second succeeds", async () => {
        let attempt = 0;
        global.fetch = jest.fn(async () => {
            attempt += 1;
            if (attempt === 1) {
                const err = new TypeError("Failed to fetch");
                throw err;
            }
            return { status: 200, ok: true, json: async () => ({ ok: true }) };
        });
        const data = await apiFetch("/api/tasks");
        expect(data).toEqual({ ok: true });
        expect(global.fetch).toHaveBeenCalledTimes(2);
    });

    test("second TypeError throws (no infinite retry loop)", async () => {
        global.fetch = jest.fn(async () => {
            throw new TypeError("Failed to fetch");
        });
        await expect(apiFetch("/api/tasks")).rejects.toThrow(TypeError);
        // Two attempts: original + 1 retry. No more.
        expect(global.fetch).toHaveBeenCalledTimes(2);
    });

    test("non-TypeError (e.g. AbortError) does NOT retry", async () => {
        global.fetch = jest.fn(async () => {
            const err = new Error("aborted");
            err.name = "AbortError";
            throw err;
        });
        await expect(apiFetch("/api/tasks")).rejects.toThrow();
        expect(global.fetch).toHaveBeenCalledTimes(1);
    });
});

describe("apiFetch — error paths", () => {
    test("401 throws Authentication required (and shows prompt)", async () => {
        global.fetch = jest.fn(async () => ({ status: 401, ok: false }));
        await expect(apiFetch("/api/tasks")).rejects.toThrow(/Authentication/);
        expect(global.confirm).toHaveBeenCalled();
    });

    test("403 throws Authentication required", async () => {
        global.fetch = jest.fn(async () => ({ status: 403, ok: false }));
        await expect(apiFetch("/api/tasks")).rejects.toThrow(/Authentication/);
    });

    test("500 with body.error throws server's error message", async () => {
        global.fetch = jest.fn(async () => ({
            status: 500,
            ok: false,
            statusText: "Internal Server Error",
            json: async () => ({ error: "DB connection lost" }),
        }));
        await expect(apiFetch("/api/tasks")).rejects.toThrow("DB connection lost");
    });

    test("500 without JSON body throws statusText fallback", async () => {
        global.fetch = jest.fn(async () => ({
            status: 500,
            ok: false,
            statusText: "Internal Server Error",
            json: async () => { throw new Error("not json"); },
        }));
        await expect(apiFetch("/api/tasks")).rejects.toThrow("Internal Server Error");
    });
});

describe("apiFetch — recovery prompt singleton (PR52 #115)", () => {
    test("two concurrent failures fire only ONE prompt", async () => {
        // For this test we need the dismiss-reset setTimeout to NOT
        // fire immediately (otherwise the flag clears between prompts).
        // Use a setTimeout that only runs the retry-delay (250ms) callbacks,
        // and lets the dismiss-reset (5000ms) sit forever.
        global.setTimeout = (fn, ms) => {
            if (ms < 1000) fn();
            // else: never fires — simulates the dismiss flag lingering
        };
        global.fetch = jest.fn(async () => {
            throw new TypeError("Failed to fetch");
        });
        const p1 = apiFetch("/api/tasks").catch(() => {});
        const p2 = apiFetch("/api/goals").catch(() => {});
        await Promise.all([p1, p2]);
        // Only one confirm() call across both failed fetches.
        expect(global.confirm).toHaveBeenCalledTimes(1);
    });
});
