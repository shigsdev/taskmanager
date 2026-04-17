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
        // Start with clean state to avoid controllerchange reload issues
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        // Now navigate without ?nosw=1 to register the SW
        await page.goto("/");
        await page.waitForLoadState("networkidle");
        await page.waitForTimeout(2000);

        // Wait for SW to be fully activated
        await page.evaluate(async () => {
            const reg = await navigator.serviceWorker.ready;
            if (reg.active && reg.active.state !== "activated") {
                await new Promise((resolve) => {
                    reg.active.addEventListener("statechange", () => {
                        if (reg.active.state === "activated") resolve();
                    });
                    setTimeout(resolve, 3000);
                });
            }
        });

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
        // Use ?nosw=1 first to ensure a clean state, then navigate
        // without it to register the SW fresh
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.goto("/");
        // Wait for SW to fully activate and settle
        await page.waitForLoadState("networkidle");
        await page.waitForTimeout(2000);

        await page.evaluate(async () => {
            const reg = await navigator.serviceWorker.ready;
            // Wait until the SW is fully activated
            if (reg.active && reg.active.state !== "activated") {
                await new Promise((resolve) => {
                    reg.active.addEventListener("statechange", () => {
                        if (reg.active.state === "activated") resolve();
                    });
                    setTimeout(resolve, 3000);
                });
            }
        });

        // Verify cache exists
        let cacheCount = await page.evaluate(async () => {
            const keys = await caches.keys();
            return keys.filter((k) => k.startsWith("taskmanager-")).length;
        });
        expect(cacheCount).toBeGreaterThan(0);

        // Send CLEAR_CACHE message
        await page.evaluate(async () => {
            if (navigator.serviceWorker.controller) {
                navigator.serviceWorker.controller.postMessage({
                    type: "CLEAR_CACHE",
                });
            }
            await new Promise((r) => setTimeout(r, 1000));
        });

        cacheCount = await page.evaluate(async () => {
            const keys = await caches.keys();
            return keys.filter((k) => k.startsWith("taskmanager-")).length;
        });
        expect(cacheCount).toBe(0);
    });
});
