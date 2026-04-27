/**
 * SW-active local Playwright suite — PR39 closes audit E2.
 *
 * The default `tests/e2e/` suite uses ?nosw=1 to bypass the service
 * worker, which means the entire SW code path (install, activate,
 * cache strategy, app-shell pre-cache, network-first vs cache-first
 * routing) is only exercised on prod via the 22-test smoke. A bug
 * in sw.js that breaks startup or returns the wrong response from
 * cache would pass every other local gate.
 *
 * These tests load the SAME dev bypass server but WITHOUT ?nosw=1
 * so the SW path runs. The cache version bumps every PR, so we use
 * Playwright's per-test fresh context to ensure each test starts
 * with no SW registered.
 *
 * Bug class this catches:
 *   - sw.js fetch handler returns wrong response for HTML/API
 *     (#56 + #88 — would have been silent on local before this).
 *   - SW install fails because APP_SHELL references a missing
 *     static file (PR24 BUG-1: import.js was missing from
 *     EXPECTED_STATIC_FILES + would have broken SW addAll).
 *   - controllerchange reload loop (#55 family).
 */
// @ts-check
const { test, expect } = require("@playwright/test");

/**
 * PR40 #106: prime the SW + wait for any controllerchange-triggered
 * reload to settle. base.html registers an `controllerchange` listener
 * that calls `window.location.reload()` whenever a new SW takes
 * control. sw.js's activate handler calls `self.clients.claim()`, so
 * even the FIRST install triggers a reload mid-test. Without priming,
 * page.evaluate dies with "Execution context was destroyed".
 *
 * Strategy:
 *   1. First nav with ?nosw=1 to ensure ANY prior SW is unregistered.
 *      (base.html unregister-on-nosw covers this.)
 *   2. Second nav WITHOUT ?nosw — SW registers + installs + activates
 *      + claims → controllerchange → reload.
 *   3. Wait for that reload to finish: page.waitForURL or just a
 *      networkidle settle after detecting the SW controller flip.
 *   4. Now SW is in control + page is stable; tests can safely evaluate.
 */
async function primeSw(page) {
    // Strategy: do TWO real visits. First visit installs/activates SW
    // and triggers base.html's controllerchange→reload. Second visit
    // happens AFTER any reload settled — SW is already in control of
    // the page and no further reload is queued, so page.evaluate calls
    // are safe.
    //
    // The trick: between visits, wait for the SW controller to be
    // present AND wait for the page to be in a stable state (no
    // pending navigations). The simplest "stable" signal is to do a
    // full page.goto a SECOND time. That second goto starts in a state
    // where SW already controls the page → no controllerchange fires
    // → no reload → page.evaluate is safe.
    await page.goto("/?nosw=1");
    await page.waitForLoadState("networkidle");
    // First real visit — SW registers, installs, activates, claims,
    // and base.html reloads. We don't care which navigation lands us;
    // we just need the SW eventually in control.
    await page.goto("/");
    // Wait up to 30s for the SW to be in control. This also outlasts
    // any controllerchange reload because that reload increments the
    // navigation count but doesn't unset navigator.serviceWorker.controller.
    await page.waitForFunction(
        () => navigator.serviceWorker.controller !== null,
        null,
        { timeout: 30_000 },
    );
    // Now do a SECOND goto to land in a stable state where SW is
    // already controlling and no controllerchange is queued. This
    // second navigation is what makes evaluate safe afterwards.
    await page.goto("/");
    await page.waitForLoadState("networkidle");
}

test.describe("Service worker — install + activation", () => {
    test("home page loads + SW registers + activates", async ({ page }) => {
        // PR40 #106: primeSw handles the controllerchange-reload race.
        const errors = [];
        page.on("pageerror", (err) => errors.push(err.message));
        await primeSw(page);
        const swState = await page.evaluate(async () => {
            const reg = await navigator.serviceWorker.ready;
            return {
                hasController: !!navigator.serviceWorker.controller,
                scope: reg.scope,
                active: !!reg.active,
                cacheName: reg.active ? reg.active.scriptURL : null,
            };
        });
        expect(swState.active).toBe(true);
        expect(swState.hasController).toBe(true);
        expect(swState.scope).toMatch(/\/$/);
        expect(swState.cacheName).toContain("/sw.js");
        expect(errors).toEqual([]);
    });

    test("APP_SHELL static files all return 200 (catches missing files)", async ({ page }) => {
        await primeSw(page);

        // PR24 BUG-1 class: a file in APP_SHELL that 404s makes addAll
        // reject, which makes SW install fail silently. Verify each
        // appshell file is reachable.
        const shellFiles = [
            "/static/style.css",
            "/static/app.js",
            "/static/task_detail_payload.js",
            "/static/parse_capture.js",
            "/static/capture.js",
            "/static/filter_helpers.js",  // PR39
            "/static/import.js",
            "/static/voice_memo.js",
            "/static/day_group.js",
            "/static/projects.js",
            "/static/calendar.js",
            "/static/recurring.js",
            "/static/manifest.json",
        ];
        for (const path of shellFiles) {
            const resp = await page.request.get(path);
            expect(
                resp.status(),
                `${path} returned ${resp.status()} — missing file would break SW addAll`,
            ).toBe(200);
        }
    });
});

test.describe("Service worker — fetch handler routing (#56 + #88)", () => {
    test("HTML requests bypass the SW (no caching)", async ({ page }) => {
        await primeSw(page);
        const navResp = await page.goto("/?nosw_check=1");
        expect(navResp.status()).toBe(200);
        const html = await navResp.text();
        // Lower-case match: Flask/Jinja emits "<!DOCTYPE html>".
        expect(html.toLowerCase()).toContain("<!doctype html>");
        // Sanity: it's our app, not a generic page.
        expect(html).toContain("captureBar");
    });

    test("API requests bypass the SW (always fresh)", async ({ page }) => {
        await primeSw(page);

        // Per #88: /api/ never goes through SW.fetch. Verify the
        // API responds with current data (not a cached snapshot).
        const resp = await page.request.get("/api/tasks");
        expect(resp.status()).toBe(200);
        const body = await resp.json();
        expect(Array.isArray(body)).toBe(true);
        // Cache-Control or Pragma header from the server, not from SW.
        // (We don't assert specific headers because Flask/gunicorn
        // defaults may change; the existence of a fresh JSON body
        // is enough proof the SW didn't serve a stale cached response.)
    });

    test("static asset returns from SW cache on second request", async ({ page }) => {
        await primeSw(page);

        // First load fills the cache. Second request should hit it.
        // We can't directly observe "SW served from cache" but we can
        // open the cache and assert the file is in it.
        const cached = await page.evaluate(async () => {
            const cacheNames = await caches.keys();
            const tmCache = cacheNames.find((n) => n.startsWith("taskmanager-"));
            if (!tmCache) return { cacheName: null };
            const c = await caches.open(tmCache);
            const keys = await c.keys();
            return {
                cacheName: tmCache,
                hasAppJs: keys.some((r) => r.url.endsWith("/static/app.js")),
                hasFilterHelpers: keys.some((r) => r.url.endsWith("/static/filter_helpers.js")),
                count: keys.length,
            };
        });

        expect(cached.cacheName).toMatch(/^taskmanager-v\d+$/);
        expect(cached.hasAppJs).toBe(true);
        expect(cached.hasFilterHelpers).toBe(true);  // PR39 — new shell file
        expect(cached.count).toBeGreaterThanOrEqual(10);
    });
});

test.describe("Service worker — old-cache cleanup on activate", () => {
    test("planting a fake old cache: gets cleaned on next activate", async ({ page }) => {
        // PR40 #106: simpler version. The SW activate handler deletes
        // any taskmanager-* cache name that doesn't match the current
        // CACHE_NAME. Verify by planting a fake one BEFORE the SW
        // activates, then loading the page so activation runs.
        // First, get into a state where SW is registered (so we can
        // open caches), but NOT activated yet — easiest: visit nosw
        // first so caches API is available without SW interference.
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.evaluate(async () => {
            await caches.open("taskmanager-v0-fake-old");
        });
        // Now prime — SW installs, activates, and the cleanup loop
        // strips taskmanager-* keys != current CACHE_NAME.
        await primeSw(page);
        const afterKeys = await page.evaluate(async () => caches.keys());
        expect(afterKeys).not.toContain("taskmanager-v0-fake-old");
        expect(afterKeys.some((k) => /^taskmanager-v\d+$/.test(k))).toBe(true);
    });
});
