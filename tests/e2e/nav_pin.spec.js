/**
 * #486: on a phone only the nav tabs stay pinned when you scroll.
 *  - At <=600px the whole .nav (app name, tabs, capture box) was sticky:
 *    215px, a quarter of an 812px screen. Now the app name and capture box
 *    scroll away and the tab strip sticks at the top.
 *  - The /reflection "Analyze together" bar stuck at top: 0, under the nav
 *    (z 100), at every width. It now sticks below what the nav leaves on
 *    screen (--nav-pinned-h).
 * Desktop is the quiet case: the one-row nav stays pinned as before.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

// Room to scroll whatever the seeded data is.
async function scrollDown(page, y) {
    await page.evaluate((to) => {
        const pad = document.createElement("div");
        pad.style.height = "2500px";
        document.querySelector("main").appendChild(pad);
        window.scrollTo(0, to);
    }, y);
    // Let the ResizeObserver re-measure after the page grew.
    await page.waitForTimeout(100);
}

const box = (page, sel) => page.evaluate((s) => {
    const r = document.querySelector(s).getBoundingClientRect();
    return { top: r.top, bottom: r.bottom };
}, sel);

// True when the element is the one actually under its own midpoint, i.e. on
// screen and not covered by the sticky nav.
const uncovered = (page, sel) => page.evaluate((s) => {
    const el = document.querySelector(s);
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + Math.min(20, r.width / 2), r.top + r.height / 2);
    return hit === el || el.contains(hit);
}, sel);

test.describe("#486 phone header pins only the nav tabs", () => {
    for (const path of ["/", "/settings"]) {
        test(`${path}: after a scroll only the tab strip is pinned`, async ({ page, viewport }) => {
            test.skip(viewport.width > 600, "phone layout only");
            await page.goto(`${path}?nosw=1`);
            await page.waitForLoadState("networkidle");

            if (path === "/") {
                // At the top the capture box is on screen to type into.
                expect(await uncovered(page, ".capture-bar input[type=text]")).toBe(true);
            }
            await scrollDown(page, 600);

            const tabs = await box(page, ".nav-links");
            expect(tabs.top).toBeGreaterThanOrEqual(0);
            expect(tabs.top).toBeLessThanOrEqual(8);
            expect(await uncovered(page, ".nav-tab")).toBe(true);
            // The app name (and the capture box) scrolled away.
            expect((await box(page, ".brand")).bottom).toBeLessThanOrEqual(0);
            if (path === "/") {
                expect((await box(page, ".capture-bar")).bottom).toBeLessThanOrEqual(0);
            }
            // What stays on screen is about one tab row, not 215px.
            expect((await box(page, ".nav")).bottom).toBeLessThan(70);
        });
    }

    test("desktop: the whole nav stays pinned (unchanged)", async ({ page, viewport }) => {
        test.skip(viewport.width < 700, "desktop layout only");
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        await scrollDown(page, 600);
        expect((await box(page, ".nav")).top).toBe(0);
        expect(await uncovered(page, ".capture-bar input[type=text]")).toBe(true);
    });

    test("/reflection: the Analyze together bar sticks below the nav, not under it", async ({ page }) => {
        const reflections = Array.from({ length: 30 }, (_, i) => ({
            id: `00000000-0000-0000-0000-${String(486000 + i).padStart(12, "0")}`,
            iso_week: "2026-W39", title: `Sitting ${i + 1}`, input_mode: "typed",
            transcript: "A reflection.", audio_duration_seconds: null,
            audio_cost_usd: null, ai_cost_usd: 0.01,
            proposed_actions: { explicit: [], suggested: [] },
            raw_segments: [], context_files: [],
            is_archived: false, is_active: true, is_draft: false,
            continued_from_id: null, continued_from: null, synthesis_of: null,
            applied_actions: null, applied_at: null, updated_at: null,
            created_at: "2026-09-25T09:00:00Z",
        }));
        await page.route("**/api/reflection", async (route, request) => {
            if (request.method() !== "GET") return route.fallback();
            await route.fulfill({
                status: 200, contentType: "application/json",
                body: JSON.stringify({ reflections }),
            });
        });
        await page.goto("/reflection?nosw=1");
        const boxes = page.locator(".reflection-history-select");
        await expect(boxes.first()).toBeVisible({ timeout: 10000 });
        await boxes.nth(0).click();
        await boxes.nth(1).click();
        await expect(page.locator("#reflCombineBar")).toBeVisible();

        await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
        await page.waitForTimeout(100);
        const bar = await box(page, "#reflCombineBar");
        const nav = await box(page, ".nav");
        expect(bar.top).toBeGreaterThanOrEqual(nav.bottom - 1);
        expect(await uncovered(page, "#reflCombineSummary")).toBe(true);
    });
});
