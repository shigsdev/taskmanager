/**
 * apiFetch error-path helpers — extracted from app.js so Jest can
 * actually exercise the failure modes instead of relying on
 * string-match assertions on the bundled source (PR47 audit gap).
 *
 * Same dual-export pattern as filter_helpers.js + parse_capture.js.
 * Browser: window.apiHelpers; Node (Jest): module.exports.
 */
"use strict";

/**
 * Decide whether an apiFetch failure should auto-retry once.
 * - Browser-level network failure (TypeError) on the first attempt → retry.
 * - Anything else (or a second-attempt failure) → don't retry, prompt
 *   the user to recover.
 */
function shouldAutoRetry(err, alreadyRetried) {
    if (alreadyRetried) return false;
    if (!err) return false;
    return err.name === "TypeError";
}

/**
 * Map a fetch Response status code to a recovery action.
 * Returns one of:
 *   "ok"            — pass through, return resp.json()
 *   "no-content"    — 204, return null
 *   "auth-fail"     — 401/403, surface clean prompt
 *   "error"         — any other non-2xx, throw with body.error
 */
function classifyResponse(resp) {
    if (!resp) return "error";
    if (resp.status === 204) return "no-content";
    if (resp.status === 401 || resp.status === 403) return "auth-fail";
    if (resp.status >= 200 && resp.status < 300) return "ok";
    return "error";
}

/**
 * Build the recovery URL — appends ?nosw=1 (or &nosw=1) to the
 * current location so a stuck SW can't immediately re-intercept on
 * the recovery navigation. Pure: takes the location-shaped object as
 * an arg so Jest can pass a fake.
 */
function buildRecoveryUrl(loc) {
    const sep = (loc.search && loc.search.length > 0) ? "&" : "?";
    return loc.pathname + (loc.search || "") + sep + "nosw=1";
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        shouldAutoRetry,
        classifyResponse,
        buildRecoveryUrl,
    };
} else if (typeof window !== "undefined") {
    window.apiHelpers = {
        shouldAutoRetry,
        classifyResponse,
        buildRecoveryUrl,
    };
}
