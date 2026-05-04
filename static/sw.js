/**
 * Service Worker — caches app shell for offline access and fast loads.
 *
 * Strategy: Network-first for API calls, cache-first for static assets.
 * Bump CACHE_VERSION when deploying new static files.
 */

var CACHE_VERSION = "v112";
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
    "/static/day_group.js",
    "/static/projects.js",
    "/static/calendar.js",
    "/static/recurring.js",
    "/static/inbox_categorize.js",
    "/static/plan.js",
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

// Message — handle skip-waiting and cache-clear requests
self.addEventListener("message", function (event) {
    if (event.data && event.data.type === "SKIP_WAITING") {
        self.skipWaiting();
    }
    if (event.data && event.data.type === "CLEAR_CACHE") {
        caches.keys().then(function (keys) {
            return Promise.all(
                keys
                    .filter(function (key) { return key.startsWith("taskmanager-"); })
                    .map(function (key) { return caches.delete(key); })
            );
        });
    }
});

// Fetch — network-first for API and pages, cache-first for static assets
self.addEventListener("fetch", function (event) {
    var url = new URL(event.request.url);

    // Skip non-GET requests
    if (event.request.method !== "GET") return;

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
                if (response.ok) {
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
