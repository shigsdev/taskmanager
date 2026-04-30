// PR67 audit fix #132: shared apiFetch wrapper used by every page-level
// JS file (app.js, calendar.js, import.js, recurring.js, recycle_bin.js,
// scan.js, settings.js, voice_memo.js).
//
// Previously apiFetch lived only in app.js. Sister pages used raw fetch(),
// bypassing the entire stale-tab retry + recovery prompt that PR47/49/52
// added to fix bugs #112/#113/#115. A user on /calendar with a stale tab
// would hit a TypeError, see no recovery prompt, and just stare at empty
// data — the very class of bug those PRs were supposed to extinguish.
//
// This module is the single source of truth. It depends on api_helpers.js
// (already loaded before app.js) for the URL-builder + classify logic.
//
// Dual-export pattern (matches api_helpers.js / parse_capture.js / etc.)
// so the pure logic is Jest-testable.

(function () {
    "use strict";

    // Module-level recovery-prompt singleton. Without this, a fan-out of
    // concurrent fetches (visibilitychange refresh re-runs ~5 loaders)
    // would each fire their own confirm() — user hits 5 OKs in a row.
    // Gate via a module-level flag so only ONE prompt is shown per
    // recovery cycle. Reset the flag after the user dismisses, or the
    // page reloads via _hardRecover.
    let _recoveryPromptShown = false;

    function _maybePromptRecovery(message) {
        if (_recoveryPromptShown) return;
        _recoveryPromptShown = true;
        // eslint-disable-next-line no-alert
        const ok = (typeof confirm === "function") ? confirm(message) : false;
        if (ok) {
            _hardRecover();  // navigation kills _recoveryPromptShown anyway
        } else {
            // User dismissed — reset after a beat so they can try again.
            setTimeout(() => { _recoveryPromptShown = false; }, 5_000);
        }
    }

    // Reset the prompt flag — used by tests and by callers that have
    // explicitly recovered (e.g. successful navigation).
    function _resetRecoveryFlag() {
        _recoveryPromptShown = false;
    }

    // PR49 #113: hard-recover from a stuck SW. location.reload() can hang
    // when the SW controller is in a weird state — its fetch handler may
    // intercept the navigation and never resolve. Unregister the SW
    // first so the next navigation goes straight to the network.
    async function _hardRecover() {
        try {
            if (typeof navigator !== "undefined" && "serviceWorker" in navigator) {
                const regs = await navigator.serviceWorker.getRegistrations();
                await Promise.all(regs.map((r) => r.unregister().catch(() => {})));
            }
        } catch (_) { /* never block recovery on unregister failure */ }
        if (typeof window !== "undefined" && window.apiHelpers) {
            window.location.href = window.apiHelpers.buildRecoveryUrl(window.location);
        }
    }

    async function apiFetch(url, opts = {}) {
        // PR47 #112 + PR49 #113: stale-tab fetch failure recovery.
        // Causes for "TypeError: Failed to fetch" on a long-idle tab:
        //  (a) Mobile browser killed the page's network connection
        //      during tab suspension; first wake-up fetch dies before
        //      reconnect.
        //  (b) Service worker controller went stale during sleep.
        //  (c) Flask OAuth session expired (24h sliding) — redirect to
        //      /login/google → cross-origin → browser blocks.
        // Recovery: auto-retry once on TypeError. If retry also fails,
        // prompt to reload via _hardRecover() (unregisters SW first so
        // the reload can't hang on a stuck SW).
        // Default Content-Type is application/json EXCEPT for FormData
        // bodies — those need the browser's auto-generated multipart
        // boundary, which it won't add if Content-Type is preset.
        const isFormData = (typeof FormData !== "undefined")
            && opts.body instanceof FormData;
        const defaultHeaders = isFormData ? {} : { "Content-Type": "application/json" };
        const mergedHeaders = { ...defaultHeaders, ...(opts.headers || {}) };

        let resp;
        try {
            resp = await fetch(url, {
                ...opts,
                headers: mergedHeaders,
            });
        } catch (err) {
            // Auto-retry once before bothering the user — covers the
            // "stale-tab first-wake" class, which usually succeeds on
            // retry once the connection / SW rebinds.
            if (err && err.name === "TypeError" && !opts._retried) {
                await new Promise((r) => setTimeout(r, 250));
                return apiFetch(url, { ...opts, _retried: true });
            }
            // PR52 #115 single-prompt guard.
            _maybePromptRecovery(
                "Network request failed (this can happen on a tab that's " +
                "been idle for a while). Reload the page to recover?"
            );
            throw err;
        }
        if (resp.status === 204) return null;
        // 401/403 — actual auth failure. Surface a clean message instead
        // of dumping a JSON parse + raw statusText. Still throw so the
        // caller can decide what to do.
        if (resp.status === 401 || resp.status === 403) {
            _maybePromptRecovery("Authentication failed. Reload to sign in again?");
            throw new Error("Authentication required");
        }
        if (!resp.ok) {
            const body = await resp.json().catch(() => ({}));
            throw new Error(body.error || resp.statusText);
        }
        return resp.json();
    }

    const api = {
        apiFetch,
        _hardRecover,
        _maybePromptRecovery,
        _resetRecoveryFlag,
    };

    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    }
    if (typeof window !== "undefined") {
        window.apiClient = api;
        // Convenience: pages that just want `apiFetch` (most of them)
        // can call window.apiFetch directly. Doesn't shadow Node tests
        // because they use module.exports.
        window.apiFetch = apiFetch;
    }
})();
