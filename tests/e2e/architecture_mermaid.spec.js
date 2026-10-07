/**
 * #391 (2026-10-06): every Mermaid diagram on /architecture renders —
 * not just the first one.
 *
 * The auto-generated ER diagram (`build_er_diagram()`) rendered mermaid
 * 10.9.1's "Syntax error in text" SVG, probably since #43, and nothing
 * noticed: the prod smoke check only asserted the FIRST `pre.mermaid svg`
 * was visible, and an error message is still an `svg`. This test walks
 * every block and fails on any that holds no SVG or holds the error text.
 *
 * Mermaid loads from cdn.jsdelivr.net, so this test needs network — the
 * same dependency the prod smoke check already has.
 */
const { test, expect } = require("@playwright/test");

test.describe("#391 /architecture Mermaid diagrams", () => {
    test("every diagram renders and none is a syntax error", async ({ page }) => {
        const errors = [];
        page.on("pageerror", (err) => errors.push(err.message));

        await page.goto("/architecture?nosw=1");

        const blocks = page.locator("pre.mermaid");
        const total = await blocks.count();
        expect(total).toBeGreaterThanOrEqual(10);

        // Mermaid marks each block it has processed — error or not —
        // with data-processed="true". Wait for all of them, so the check
        // below sees final output rather than a half-rendered page.
        await expect(page.locator('pre.mermaid[data-processed="true"]'))
            .toHaveCount(total, { timeout: 20_000 });

        for (let i = 0; i < total; i++) {
            const block = blocks.nth(i);
            await expect(block.locator("svg"), `diagram #${i + 1} has no SVG`)
                .toHaveCount(1);
            await expect(block, `diagram #${i + 1} is a Mermaid syntax error`)
                .not.toContainText("Syntax error");
        }

        expect(errors).toEqual([]);
    });

    test("the ER diagram draws at full size, scrolling inside its own box", async ({ page }) => {
        await page.goto("/architecture?nosw=1");
        const block = page.locator("#schema pre.mermaid");
        await expect(block).toHaveAttribute("data-processed", "true", { timeout: 20_000 });
        await page.locator("#schema details.engineering summary").click();

        // Fit-to-width shrank this ~4000px-wide diagram to ~19%, leaving
        // ~3px labels. At natural size the SVG is wider than its box...
        const m = await block.evaluate((pre) => {
            const svg = pre.querySelector("svg");
            return {
                drawn: svg.getBoundingClientRect().width,
                natural: svg.viewBox.baseVal.width,
                box: pre.clientWidth,
            };
        });
        expect(m.drawn).toBeGreaterThanOrEqual(m.natural * 0.95);
        expect(m.drawn).toBeGreaterThan(m.box);

        // ...so it must scroll inside the box, not widen the page.
        const overflow = await page.evaluate(
            () => document.documentElement.scrollWidth - window.innerWidth,
        );
        expect(overflow).toBeLessThanOrEqual(0);
    });
});
