/**
 * #397 (2026-10-08): the /docs table of contents is reachable at any
 * scroll position.
 *
 * The TOC sidebar is `position: sticky` (#33). It grew to ~1065px tall —
 * taller than a 800-900px window — with no max-height or overflow, so it
 * stayed pinned while the page scrolled, could not scroll itself, and its
 * last ~265px of links only came into view at the very end of a 42,000px
 * page. User report: "on the left side of the page you cannot scroll up
 * and down". Desktop only: under 700px the TOC is a static block.
 */
const { test, expect } = require("@playwright/test");

test.describe("#397 /docs TOC scrolls on its own", () => {
    test("the sidebar fits the window and its last link can be reached mid-page", async ({ page, viewport }) => {
        test.skip(viewport.width < 700, "desktop-only: the TOC is static on mobile");

        await page.goto("/docs?nosw=1");
        const toc = page.locator(".docs-toc");
        await expect(toc).toBeVisible();

        // Park the page in the middle of the long docs.
        await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight / 2));

        const m = await toc.evaluate((el) => {
            const r = el.getBoundingClientRect();
            return { top: r.top, bottom: r.bottom, innerHeight: window.innerHeight,
                     scrollable: el.scrollHeight > el.clientHeight };
        });
        // Pinned and fully inside the window...
        expect(m.top).toBeGreaterThanOrEqual(0);
        expect(m.bottom).toBeLessThanOrEqual(m.innerHeight);
        // ...so a TOC taller than the window must scroll by itself.
        expect(m.scrollable).toBe(true);

        // The last link can be brought into view without moving the page.
        const pageY = await page.evaluate(() => window.scrollY);
        const last = toc.locator("a").last();
        await toc.evaluate((el) => { el.scrollTop = el.scrollHeight; });
        await expect(last).toBeInViewport();
        expect(await page.evaluate(() => window.scrollY)).toBe(pageY);
    });

    test("a sidebar too short to scroll still lets the wheel scroll the page", async ({ page, viewport }) => {
        // Behaviour guard, not a reproduced bug: capping the TOC must never
        // trap the wheel over a sidebar that has nothing to scroll
        // (/architecture's fits the window). A one-off Phase 6 reading
        // suggested `overscroll-behavior: contain` did that; it did not
        // reproduce (3/3 runs scrolled), and the fix does not use it.
        test.skip(viewport.width < 700, "desktop-only: the TOC is static on mobile");

        await page.goto("/architecture?nosw=1");
        const toc = page.locator(".docs-toc");
        await expect(toc).toBeVisible();
        expect(await toc.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(false);

        // Mid-page, so the sidebar is in its pinned (stuck) state.
        await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight / 2));
        const box = await toc.boundingBox();
        await page.mouse.move(box.x + 40, box.y + 60);
        const before = await page.evaluate(() => window.scrollY);
        await page.mouse.wheel(0, 1500);
        await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(before);
    });
});
