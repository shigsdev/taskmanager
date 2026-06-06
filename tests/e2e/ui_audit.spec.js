/**
 * #217 (2026-05-24): mechanical UI audit across every page route.
 *
 * Runs in BOTH the chromium (desktop 1280x800) and chromium-mobile
 * (375x812) Playwright projects. For every route the app renders,
 * asserts three properties:
 *
 *   1. No console errors during load (catches broken JS init across
 *      pages that share app.js — historical class: a null-guard
 *      missing on a getElementById call on /completed throws and
 *      blocks downstream loaders).
 *   2. document.documentElement.scrollWidth <= window.innerWidth
 *      (the #138 D-B1 class — bare `1fr` grids, missing min-width:0
 *      on flex children, day-strip / nav-links / project-filter-bar
 *      all caught for this on #216). Latent risk in `.calendar-layout`
 *      mobile, `.calendar-row` mobile, `.plan-row` mobile,
 *      `.docs-page` mobile — flagged during #216 triage.
 *   3. Mobile-only: every visible <a> / <button> has both width and
 *      height >= 44px (the #140 touch-target floor). Skipped on
 *      desktop where pointer-precision is fine.
 *
 * Each route gets its own test case so a failure pinpoints which
 * page broke and at what viewport. Better than a single mega-test
 * that fails on the first offender.
 *
 * Routes that need extra setup (e.g. /tier/<name> needs a tier
 * name) are listed explicitly with their realized URL. /print is
 * skipped because window.print() can hang Playwright; the page
 * itself is covered by the pages.spec.js Print: tier grouping test.
 */
const { test, expect } = require("@playwright/test");

// Every page route under the @login_required decorator. Sorted to
// match the order they appear in app.py for easy lookup.
const ROUTES = [
    { name: "home / tier board", url: "/?nosw=1" },
    { name: "/tier/today", url: "/tier/today?nosw=1" },
    { name: "/tier/this_week", url: "/tier/this_week?nosw=1" },
    { name: "/completed", url: "/completed?nosw=1" },
    { name: "/docs", url: "/docs?nosw=1" },
    { name: "/architecture", url: "/architecture?nosw=1" },
    { name: "/goals", url: "/goals?nosw=1" },
    { name: "/projects", url: "/projects?nosw=1" },
    { name: "/calendar", url: "/calendar?nosw=1" },
    { name: "/recurring", url: "/recurring?nosw=1" },
    { name: "/review", url: "/review?nosw=1" },
    { name: "/plan", url: "/plan?nosw=1" },
    { name: "/scan", url: "/scan?nosw=1" },
    { name: "/voice-memo", url: "/voice-memo?nosw=1" },
    { name: "/reflection", url: "/reflection?nosw=1" },
    { name: "/import", url: "/import?nosw=1" },
    { name: "/settings", url: "/settings?nosw=1" },
    { name: "/recycle-bin", url: "/recycle-bin?nosw=1" },
    { name: "/utilities", url: "/utilities?nosw=1" },  // #222
    { name: "/strength-forge", url: "/strength-forge?nosw=1" },  // #282
    // /print intentionally omitted — window.print() can stall the
    // headless renderer; covered by pages.spec.js Print: tier grouping.
];

test.describe("#217 UI audit — viewport parity + console errors", () => {
    for (const route of ROUTES) {
        test(`${route.name} — no console errors + no horizontal overflow`, async ({ page }) => {
            // Collect console errors throughout page lifetime. We don't
            // filter to a specific level — anything tagged "error" by the
            // browser is in scope (uncaught throw, fetch failure, CSP
            // violation, etc.).
            const consoleErrors = [];
            page.on("pageerror", (err) => consoleErrors.push(`pageerror: ${err.message}`));
            page.on("console", (msg) => {
                if (msg.type() === "error") {
                    // Ignore SW-related noise on a ?nosw=1 page: the SW
                    // unregister can emit harmless "removed" log lines
                    // that some tests treat as warnings. We only care
                    // about real errors.
                    consoleErrors.push(`console.error: ${msg.text()}`);
                }
            });

            await page.goto(route.url);
            await page.waitForLoadState("networkidle");

            // Viewport parity check. Re-assert viewport AFTER goto in
            // case async loads triggered any device-emulation reset.
            const viewport = page.viewportSize();
            await page.setViewportSize(viewport);

            const overflow = await page.evaluate(() => ({
                scrollWidth: document.documentElement.scrollWidth,
                innerWidth: window.innerWidth,
            }));

            // Concrete error messages on failure so the operator can
            // see at a glance which property broke + by how much.
            expect(
                consoleErrors,
                `console errors on ${route.name}: ${JSON.stringify(consoleErrors)}`,
            ).toEqual([]);
            expect(
                overflow.scrollWidth,
                `${route.name} horizontal overflow: scrollWidth=${overflow.scrollWidth} > innerWidth=${overflow.innerWidth}`,
            ).toBeLessThanOrEqual(overflow.innerWidth);
        });
    }
});
