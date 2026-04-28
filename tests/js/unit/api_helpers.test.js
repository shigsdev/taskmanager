/**
 * Jest unit tests for static/api_helpers.js — closes the PR47 audit
 * gap where the apiFetch error-path was only "tested" via string-match
 * on the bundled source. These actually exercise the logic.
 */
const {
    shouldAutoRetry,
    classifyResponse,
    buildRecoveryUrl,
} = require("../../../static/api_helpers");

describe("shouldAutoRetry", () => {
    test("TypeError on first attempt → retry", () => {
        const err = new TypeError("Failed to fetch");
        expect(shouldAutoRetry(err, false)).toBe(true);
    });
    test("TypeError on second attempt → don't retry (avoid infinite loop)", () => {
        const err = new TypeError("Failed to fetch");
        expect(shouldAutoRetry(err, true)).toBe(false);
    });
    test("non-TypeError (e.g. user abort) → don't retry", () => {
        const err = new Error("AbortError");
        err.name = "AbortError";
        expect(shouldAutoRetry(err, false)).toBe(false);
    });
    test("null err → don't retry", () => {
        expect(shouldAutoRetry(null, false)).toBe(false);
        expect(shouldAutoRetry(undefined, false)).toBe(false);
    });
});

describe("classifyResponse", () => {
    test("200 OK → ok", () => {
        expect(classifyResponse({ status: 200 })).toBe("ok");
    });
    test("201 Created → ok", () => {
        expect(classifyResponse({ status: 201 })).toBe("ok");
    });
    test("204 No Content → no-content (special case for empty bodies)", () => {
        expect(classifyResponse({ status: 204 })).toBe("no-content");
    });
    test("401 → auth-fail", () => {
        expect(classifyResponse({ status: 401 })).toBe("auth-fail");
    });
    test("403 → auth-fail", () => {
        expect(classifyResponse({ status: 403 })).toBe("auth-fail");
    });
    test("422 validation error → error (caller surfaces body.error)", () => {
        expect(classifyResponse({ status: 422 })).toBe("error");
    });
    test("500 → error", () => {
        expect(classifyResponse({ status: 500 })).toBe("error");
    });
    test("null response → error (defensive)", () => {
        expect(classifyResponse(null)).toBe("error");
        expect(classifyResponse(undefined)).toBe("error");
    });
    // PR49 #113: opaqueredirect detection was DROPPED because of false
    // positives. The classifier should NOT special-case status 0 — it
    // falls through to "error" which lets the TypeError-recovery path
    // handle it cleanly via the normal failure prompt.
    test("status 0 (opaqueredirect / blocked) → error (not a special case)", () => {
        expect(classifyResponse({ status: 0 })).toBe("error");
    });
});

describe("buildRecoveryUrl", () => {
    test("clean path gets ?nosw=1", () => {
        const loc = { pathname: "/", search: "" };
        expect(buildRecoveryUrl(loc)).toBe("/?nosw=1");
    });
    test("path with existing ?query gets &nosw=1", () => {
        const loc = { pathname: "/tier/today", search: "?filter=urgent" };
        expect(buildRecoveryUrl(loc)).toBe("/tier/today?filter=urgent&nosw=1");
    });
    test("non-root path with no query", () => {
        const loc = { pathname: "/calendar", search: "" };
        expect(buildRecoveryUrl(loc)).toBe("/calendar?nosw=1");
    });
    test("does not double-add nosw — caller's responsibility (one-shot recovery)", () => {
        const loc = { pathname: "/", search: "?nosw=1" };
        // Spec: helper is naive; caller invokes once. This documents
        // the current behavior so a future caller knows to check.
        expect(buildRecoveryUrl(loc)).toBe("/?nosw=1&nosw=1");
    });
});
