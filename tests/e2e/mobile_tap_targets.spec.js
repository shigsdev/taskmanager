/**
 * #398 + #354 (2026-10-08): mobile tap targets reach the 44px floor.
 *
 * Measured at 375x812 before the fix: /docs and /architecture TOC links
 * were 20px tall (~5px apart), the /goals filter selects 31px and the
 * /projects filter selects 32px. CLAUDE.md's floor for tappable controls on
 * mobile is 44px. Mobile only: on desktop these are mouse targets.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const SURFACES = [
    { path: "/docs", selector: ".docs-toc a", min: 30 },
    { path: "/architecture", selector: ".docs-toc a", min: 11 },
    { path: "/goals", selector: ".goals-filters select", min: 5 },
    { path: "/projects", selector: ".projects-filters select", min: 3 },
    // #399: the rest of the sub-44px selects, and the inputs/buttons sharing
    // their rows (measured 33/34/40/21px at 375x812 before the fix).
    { path: "/", selector: ".capture-bar select, .capture-bar input[type=\"text\"]", min: 2 },
    { path: "/", selector: ".weekly-focus-slot select, .weekly-focus-slot input, .weekly-focus-slot button", min: 6 },
    { path: "/utilities", selector: ".pg-goal-select", min: 1 },
];

test.describe("#398 + #354 + #399 mobile tap targets", () => {
    for (const { path, selector, min } of SURFACES) {
        test(`${path}: every ${selector} is at least 44px tall`, async ({ page, viewport }) => {
            test.skip(viewport.width >= 700, "mobile-only: desktop targets are mouse targets");

            await page.goto(`${path}?nosw=1`);
            await expect(page.locator(selector).first()).toBeVisible();

            const m = await page.evaluate((sel) => ({
                heights: [...document.querySelectorAll(sel)]
                    .map((el) => el.getBoundingClientRect().height)
                    .filter((h) => h > 0),
                sw: document.documentElement.scrollWidth,
                iw: window.innerWidth,
            }), selector);

            expect(m.heights.length).toBeGreaterThanOrEqual(min);
            expect(Math.min(...m.heights)).toBeGreaterThanOrEqual(44);
            expect(m.sw).toBeLessThanOrEqual(m.iw);
        });
    }
});
