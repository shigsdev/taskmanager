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
const { test, expect } = require("./lane"); // #402: per-worker lane server

// True when the link is the element actually under its own midpoint —
// i.e. on screen AND not covered by the sticky header (.nav, z-index 100).
// toBeInViewport() alone missed the header: Phase 6 found the TOC's first
// link sitting at y≈68, inside the window but under the 91px header.
function linkIsUncovered(link) {
    const r = link.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + 5, r.top + r.height / 2);
    return hit === link || link.contains(hit);
}

test.describe("#397 /docs TOC scrolls on its own", () => {
    test("the sidebar sits below the header, fits the window, and its first and last links can be reached mid-page", async ({ page, viewport }) => {
        test.skip(viewport.width < 700, "desktop-only: the TOC is static on mobile");

        await page.goto("/docs?nosw=1");
        const toc = page.locator(".docs-toc");
        await expect(toc).toBeVisible();

        // Park the page in the middle of the long docs.
        await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight / 2));

        const m = await toc.evaluate((el) => {
            const r = el.getBoundingClientRect();
            return { top: r.top, bottom: r.bottom, innerHeight: window.innerHeight,
                     headerBottom: document.querySelector(".nav").getBoundingClientRect().bottom,
                     scrollable: el.scrollHeight > el.clientHeight };
        });
        // Pinned below the sticky header and fully inside the window...
        expect(m.top).toBeGreaterThanOrEqual(m.headerBottom);
        expect(m.bottom).toBeLessThanOrEqual(m.innerHeight);
        // ...so a TOC taller than that must scroll by itself.
        expect(m.scrollable).toBe(true);

        const pageY = await page.evaluate(() => window.scrollY);
        const first = toc.locator("a").first();
        const last = toc.locator("a").last();

        // At the top of the TOC, the first link is visible, not under the header.
        await toc.evaluate((el) => { el.scrollTop = 0; });
        expect(await first.evaluate(linkIsUncovered)).toBe(true);

        // At its end, the last link is visible — and the page never moved.
        await toc.evaluate((el) => { el.scrollTop = el.scrollHeight; });
        expect(await last.evaluate(linkIsUncovered)).toBe(true);
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

// #400 (2026-10-09): a TOC jump scrolled the section to top: 0, under the
// sticky .nav (91px desktop, 165px at <=600px), hiding the section's own
// heading — the first visible line was the next sub-heading. Both viewports:
// the header covers the target on mobile too.
test.describe("#400 a TOC jump lands with the section heading visible", () => {
    for (const path of ["/docs", "/architecture"]) {
        test(`${path}: the target heading is below the header, not under it`, async ({ page }) => {
            await page.goto(`${path}?nosw=1`);
            const links = page.locator(".docs-toc a");
            const n = await links.count();
            for (const i of [Math.floor(n / 2), n - 1]) {
                const href = await links.nth(i).getAttribute("href");
                await links.nth(i).click();
                await expect.poll(() => page.evaluate((sel) => {
                    const heading = document.querySelector(sel).querySelector("h2, h3")
                        || document.querySelector(sel);
                    const navBottom = document.querySelector(".nav").getBoundingClientRect().bottom;
                    const r = heading.getBoundingClientRect();
                    const hit = document.elementFromPoint(r.left + 5, r.top + r.height / 2);
                    return r.top >= navBottom && (hit === heading || heading.contains(hit));
                }, href), { message: `${href} heading hidden under the header` }).toBe(true);
            }
        });
    }
});
