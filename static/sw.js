/**
 * Service Worker — caches app shell for offline access and fast loads.
 *
 * Strategy: Network-first for API calls, cache-first for static assets.
 * Bump CACHE_VERSION when deploying new static files.
 */

var CACHE_VERSION = "v223";
var CACHE_NAME = "taskmanager-" + CACHE_VERSION;

// HTML is intentionally NOT pre-cached (see fetch handler below — Bug #56).
// Only static assets go in here.
var APP_SHELL = [
    "/static/style.css",
    "/static/app.js",
    "/static/task_detail_payload.js",
    "/static/parse_capture.js",
    "/static/capture.js",
    "/static/filter_helpers.js",
    "/static/api_helpers.js",
    "/static/api_client.js",
    "/static/voice_input.js",
    "/static/import.js",
    "/static/voice_memo.js",
    "/static/voice_memo_helpers.js",
    "/static/day_group.js",
    "/static/projects.js",
    "/static/calendar.js",
    "/static/calendar_bucket_helpers.js",
    "/static/recurring.js",
    "/static/recurring_helpers.js",
    "/static/inbox_categorize_helpers.js",
    "/static/inbox_categorize.js",
    "/static/plan.js",
    "/static/tier_helpers.js",
    "/static/reorder_helpers.js",
    "/static/weekly_focus.js",
    "/static/reflection_helpers.js",
    "/static/reflection.js",
    "/static/goal_filter_helpers.js",
    "/static/date_helpers.js",
    // #193 (2026-05-22): these 6 page scripts are referenced by their
    // templates' <script src> but were never added here — so they
    // missed the offline app-shell cache (and the health.py
    // EXPECTED_STATIC_FILES build check). test_app_shell_covers_all_
    // referenced_scripts is the drift gate that keeps this list and
    // the templates in sync from now on.
    "/static/goals.js",
    "/static/review.js",
    "/static/scan.js",
    "/static/settings.js",
    "/static/recycle_bin.js",
    "/static/swipe.js",
    "/static/utilities.js",  // #222
    "/static/strength_forge_data.js",  // #282
    "/static/strength_forge.js",       // #282
    "/static/strength_forge_helpers.js",  // #287
    "/static/manifest.json",
    "/static/favicon.svg",
];

// Install — pre-cache the app shell. Note: no skipWaiting() here — the page
// decides when to activate (see base.html SW update handshake) so we can
// avoid interrupting the user mid-edit.
self.addEventListener("install", function (event) {
    event.waitUntil(
        caches.open(CACHE_NAME).then(function (cache) {
            return cache.addAll(APP_SHELL);
        })
    );
});

// Activate — clean up old caches
self.addEventListener("activate", function (event) {
    // Clear the in-flight flag (set by CLEAR_CACHE) so the new SW can
    // re-populate the cache from scratch.
    _clearCacheInFlight = false;
    event.waitUntil(
        caches.keys().then(function (keys) {
            return Promise.all(
                keys
                    .filter(function (key) {
                        return key.startsWith("taskmanager-") && key !== CACHE_NAME;
                    })
                    .map(function (key) {
                        return caches.delete(key);
                    })
            );
        })
    );
    self.clients.claim();
});

// CLEAR_CACHE state: set true while a clear is in flight. Suppresses the
// fetch handler from re-creating `taskmanager-*` caches in the immediate
// window after delete, which made `tests/e2e/service-worker.spec.js:89`
// flaky (#205). Resets after the next `activate` so a fresh deploy can
// re-warm the cache.
var _clearCacheInFlight = false;

// Message — handle skip-waiting and cache-clear requests
self.addEventListener("message", function (event) {
    if (event.data && event.data.type === "SKIP_WAITING") {
        self.skipWaiting();
    }
    if (event.data && event.data.type === "CLEAR_CACHE") {
        // Audit fix #205 (2026-05-21): wrap the delete chain in
        // `event.waitUntil()` so the SW lifecycle blocks on completion
        // before reporting idle, AND flip `_clearCacheInFlight` so the
        // fetch handler skips its cache.put step during the window where
        // the test (or a logout flow) expects an empty cache.
        _clearCacheInFlight = true;
        event.waitUntil(
            caches.keys().then(function (keys) {
                return Promise.all(
                    keys
                        .filter(function (key) { return key.startsWith("taskmanager-"); })
                        .map(function (key) { return caches.delete(key); })
                );
            }).then(function () {
                // Leave the flag set until the next activate clears it —
                // that's when a new deploy is reasonably starting and we
                // want to re-warm. A no-op deploy never flips it back.
            })
        );
    }
});

// Fetch — network-first for API and pages, cache-first for static assets
self.addEventListener("fetch", function (event) {
    var url = new URL(event.request.url);

    // Skip non-GET requests
    if (event.request.method !== "GET") return;

    // #235 (2026-05-25): NEVER intercept cross-origin requests. The
    // user-reported Mermaid breakage on /architecture (raw `flowchart LR`
    // source rendered as text instead of SVG diagrams) was caused by
    // this SW intercepting the ES module fetch to
    // `https://cdn.jsdelivr.net/npm/mermaid@10.9.1/...` and either
    // returning a cached old copy or falling through to the 503
    // .catch handler. iOS Safari module imports through a SW are
    // brittle — the spec'd behavior allows it but real-world breakage
    // is common (CORS, opaque-response caching, version drift).
    //
    // The blast radius matters: any future CDN-loaded asset
    // (third-party fonts, analytics, AI SDKs) would hit the same
    // failure mode. Cleanest fix is to let the browser's native
    // network stack handle EVERY cross-origin request, the same way
    // we let it handle /api/ and HTML below.
    //
    // The prod-smoke test "architecture page renders Mermaid
    // diagrams" used `?nosw=1` which BYPASSED the SW — so the test
    // happily passed while the user's iPhone (SW active by default)
    // got 503s for the Mermaid CDN. That gap was the testing miss
    // RCA'd in the BACKLOG #235 row. Mitigation: a paired prod-smoke
    // test that EXERCISES the SW path (architecture without nosw=1).
    if (url.origin !== self.location.origin) {
        return;  // browser handles cross-origin natively
    }

    // API calls and HTML pages: always network, never cached.
    //
    // Bug #56 (2026-04-24): we used to cache HTML responses for offline
    // fallback, but that created a post-deploy race — the new HTML
    // referenced new hashed-by-version assets, but a stale cached copy
    // of the HTML kept loading old asset URLs until the user did a hard
    // refresh. Pages need the API to be useful anyway, so the offline
    // HTML fallback was mostly theoretical. Drop it: HTML always comes
    // from the network. Static assets below are still cached normally.
    // #56 + bug 2026-04-26: don't intercept HTML or /api/ at all. The
    // browser handles them natively — no caching, no proxying, no
    // chance for the SW's own fetch() to reject (e.g. when an OAuth
    // redirect to accounts.google.com violates connect-src CSP, which
    // surfaced as "Failed to fetch" on /import for the user). Static
    // assets below are still cached.
    var acceptHeader = event.request.headers.get("accept") || "";
    if (url.pathname.startsWith("/api/") || acceptHeader.includes("text/html")) {
        return;  // bare return = browser handles natively
    }

    // Static assets: cache-first with network fallback. Wrapped in
    // .catch so an unreachable origin returns a 503 Response instead of
    // throwing an unhandled TypeError that surfaces as "Failed to fetch"
    // in console with no actionable message.
    event.respondWith(
        caches.match(event.request).then(function (cached) {
            if (cached) return cached;
            return fetch(event.request).then(function (response) {
                // Audit fix #205 (2026-05-21): skip cache re-population
                // while a CLEAR_CACHE is in flight — otherwise a
                // background asset fetch races the delete and the cache
                // re-appears before the test (or logout flow) sees it
                // empty. Resets on next `activate`.
                if (response.ok && !_clearCacheInFlight) {
                    var clone = response.clone();
                    caches.open(CACHE_NAME).then(function (cache) {
                        cache.put(event.request, clone);
                    });
                }
                return response;
            }).catch(function () {
                return new Response("", {
                    status: 503, statusText: "Service Unavailable",
                });
            });
        })
    );
});
