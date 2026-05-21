/**
 * Service Worker E2E tests.
 *
 * These test the real SW lifecycle in a real browser — something Jest/jsdom
 * cannot do because jsdom has no SW support.
 *
 * Tests run against the local bypass server on port 5111.
 */
// @ts-check
const { test, expect } = require("@playwright/test");

/**
 * Register a fresh SW and wait for the install+activate+claim cycle to
 * fully settle, including the page reload that base.html triggers on
 * `controllerchange` (templates/base.html:176-180).
 *
 * Without this, the SW's `clients.claim()` fires `controllerchange`
 * → base.html reloads the page → any subsequent `page.evaluate` races
 * the reload and dies with "Execution context was destroyed, most
 * likely because of a navigation". This was #205's bite — flagged
 * after the v140 CACHE_VERSION bump made every SW test hit the race.
 */
async function setupFreshSW(page) {
    // 1. ?nosw=1 in base.html unregisters any prior SW before the
    //    new page-script runs. Wait for that page to settle.
    await page.goto("/?nosw=1");
    await page.waitForLoadState("networkidle");
    // 2. Belt-and-braces: explicitly unregister + clear caches from JS
    //    in case ?nosw=1 left anything behind.
    await page.evaluate(async () => {
        const regs = await navigator.serviceWorker.getRegistrations();
        await Promise.all(regs.map((r) => r.unregister()));
        const keys = await caches.keys();
        await Promise.all(keys.map((k) => caches.delete(k)));
    });
    // 3. Navigate to register the new SW. The activate handler calls
    //    `clients.claim()`, which fires `controllerchange` → base.html
    //    reloads. Wait for the SW to be the controller AND the reload
    //    to settle before returning control to the test.
    await page.goto("/");
    await page.waitForFunction(
        () => navigator.serviceWorker.controller !== null,
        { timeout: 10000 },
    );
    // controllerchange → reload may happen now. Two waits in series to
    // catch the reload's network activity + any post-reload requests.
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    await page.waitForLoadState("networkidle");
}

test.describe("Service Worker lifecycle", () => {
    test("SW registers and activates on first visit", async ({ page }) => {
        // Navigate WITHOUT ?nosw=1 so the SW registers
        await page.goto("/");
        // Wait for SW to register, then wait for activation to complete
        const swState = await page.evaluate(async () => {
            if (!("serviceWorker" in navigator)) return "unsupported";
            const reg = await navigator.serviceWorker.ready;
            if (!reg.active) return "no-active";
            if (reg.active.state === "activated") return "activated";
            // Wait for the activating → activated transition
            return new Promise((resolve) => {
                reg.active.addEventListener("statechange", () => {
                    resolve(reg.active.state);
                });
                // Timeout fallback in case it's already activated
                setTimeout(() => resolve(reg.active.state), 3000);
            });
        });
        expect(swState).toBe("activated");
    });

    test("SW caches app shell files", async ({ page }) => {
        // #205 (2026-05-21): use the shared setupFreshSW helper so
        // CACHE_VERSION bumps don't make this test flaky.
        await setupFreshSW(page);

        // Check that the cache exists and contains expected files
        const cachedUrls = await page.evaluate(async () => {
            const keys = await caches.keys();
            const tmCache = keys.find((k) => k.startsWith("taskmanager-"));
            if (!tmCache) return [];
            const cache = await caches.open(tmCache);
            const requests = await cache.keys();
            return requests.map((r) => new URL(r.url).pathname);
        });
        expect(cachedUrls).toContain("/static/app.js");
        expect(cachedUrls).toContain("/static/style.css");
        expect(cachedUrls).toContain("/static/parse_capture.js");
        expect(cachedUrls).toContain("/static/capture.js");
    });

    test("?nosw=1 unregisters any existing SW", async ({ page }) => {
        // First register the SW
        await page.goto("/");
        await page.evaluate(async () => {
            await navigator.serviceWorker.ready;
        });
        // Now navigate with ?nosw=1
        await page.goto("/?nosw=1");
        // Give it a moment to unregister
        await page.waitForTimeout(1000);
        const regCount = await page.evaluate(async () => {
            const regs = await navigator.serviceWorker.getRegistrations();
            return regs.length;
        });
        expect(regCount).toBe(0);
    });

    test("SW responds to CLEAR_CACHE message", async ({ page }) => {
        // #205 (2026-05-21): use the shared setupFreshSW helper that
        // handles the controllerchange → reload race so this test
        // doesn't flake on CACHE_VERSION bumps.
        await setupFreshSW(page);

        // Verify cache exists
        let cacheCount = await page.evaluate(async () => {
            const keys = await caches.keys();
            return keys.filter((k) => k.startsWith("taskmanager-")).length;
        });
        expect(cacheCount).toBeGreaterThan(0);

        // Send CLEAR_CACHE message + wait for the SW handler's
        // event.waitUntil to complete the cache.delete chain (#205
        // fix in static/sw.js).
        await page.evaluate(async () => {
            if (navigator.serviceWorker.controller) {
                navigator.serviceWorker.controller.postMessage({
                    type: "CLEAR_CACHE",
                });
            }
            await new Promise((r) => setTimeout(r, 1500));
        });

        cacheCount = await page.evaluate(async () => {
            const keys = await caches.keys();
            return keys.filter((k) => k.startsWith("taskmanager-")).length;
        });
        expect(cacheCount).toBe(0);
    });
});
