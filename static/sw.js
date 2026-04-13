/**
 * Service Worker — caches app shell for offline access and fast loads.
 *
 * Strategy: Network-first for API calls, cache-first for static assets.
 * Bump CACHE_VERSION when deploying new static files.
 */

var CACHE_VERSION = "v27";
var CACHE_NAME = "taskmanager-" + CACHE_VERSION;

var APP_SHELL = [
    "/",
    "/static/style.css",
    "/static/app.js",
    "/static/capture.js",
    "/static/import.js",
    "/static/manifest.json",
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

    // API calls and HTML pages: network-first with cache fallback
    var acceptHeader = event.request.headers.get("accept") || "";
    if (url.pathname.startsWith("/api/") || acceptHeader.includes("text/html")) {
        event.respondWith(
            fetch(event.request)
                .then(function (response) {
                    // Cache successful page responses for offline fallback
                    if (response.ok && acceptHeader.includes("text/html")) {
                        var clone = response.clone();
                        caches.open(CACHE_NAME).then(function (cache) {
                            cache.put(event.request, clone);
                        });
                    }
                    return response;
                })
                .catch(function () {
                    return caches.match(event.request);
                })
        );
        return;
    }

    // Static assets: cache-first with network fallback
    event.respondWith(
        caches.match(event.request).then(function (cached) {
            return cached || fetch(event.request).then(function (response) {
                if (response.ok) {
                    var clone = response.clone();
                    caches.open(CACHE_NAME).then(function (cache) {
                        cache.put(event.request, clone);
                    });
                }
                return response;
            });
        })
    );
});
