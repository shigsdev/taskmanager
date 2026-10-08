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
 * #395 (2026-10-08): wait for the FINISHED diagrams, never for
 * `data-processed`. mermaid (11.17.2, runThrowsErrors) sets
 * data-processed="true" when it STARTS a diagram, then builds it inside the
 * <pre> as `div#dmermaid-N > svg` (no viewBox, width="100%") and swaps the
 * finished svg in as the <pre>'s direct child only at the end. Measuring
 * in that window read a 754px-wide, viewBox-less temporary svg once.
 *
 * Mermaid loads from cdn.jsdelivr.net, so this test needs network — the
 * same dependency the prod smoke check already has.
 */
const { test, expect } = require("@playwright/test");

// Every block holds its finished svg as a DIRECT child (mermaid's final
// `element.innerHTML = svg`). Returns the block count.
async function waitForFinishedDiagrams(page) {
    const total = await page.locator("pre.mermaid").count();
    expect(total).toBeGreaterThanOrEqual(10);
    await expect(page.locator("pre.mermaid > svg"))
        .toHaveCount(total, { timeout: 20_000 });
    return total;
}

// Fit-to-width shrank the ~4000px-wide ER diagram to ~19% (~3px labels).
// At natural size the svg is wider than its box and scrolls inside it.
async function expectErDrawnAtFullSize(page) {
    await page.locator("#schema details.engineering summary").click();
    const m = await page.locator("#schema pre.mermaid").evaluate((pre) => {
        const svg = pre.querySelector(":scope > svg");
        return {
            drawn: svg.getBoundingClientRect().width,
            natural: svg.viewBox.baseVal.width,
            box: pre.clientWidth,
        };
    });
    expect(m.natural).toBeGreaterThan(m.box);
    expect(m.drawn).toBeGreaterThanOrEqual(m.natural * 0.95);

    // ...so it must scroll inside the box, not widen the page.
    const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
}

test.describe("#391 /architecture Mermaid diagrams", () => {
    test("every diagram renders and none is a syntax error", async ({ page }) => {
        const errors = [];
        page.on("pageerror", (err) => errors.push(err.message));

        await page.goto("/architecture?nosw=1");
        const total = await waitForFinishedDiagrams(page);

        const blocks = page.locator("pre.mermaid");
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
        await waitForFinishedDiagrams(page);
        await expectErDrawnAtFullSize(page);
    });

    test("#395: the checks wait for the finished diagram, not data-processed", async ({ page }) => {
        // Hold the ER chunk: mermaid loads it AFTER creating the temporary
        // svg, which freezes the page in exactly the state #394's probe
        // caught once by chance.
        await page.route(/\/erDiagram-[^/]*\.mjs$/, async (route) => {
            await new Promise((r) => setTimeout(r, 4000));
            await route.continue();
        });
        await page.goto("/architecture?nosw=1");

        // The trap, pinned: "processed" while only the temporary svg exists.
        const er = page.locator("#schema pre.mermaid");
        await expect(er).toHaveAttribute("data-processed", "true", { timeout: 20_000 });
        await expect(er.locator(":scope > div[id^='dmermaid'] > svg")).toHaveCount(1);
        await expect(er.locator(":scope > svg")).toHaveCount(0);

        // The real checks still pass, because they wait for the finished svg.
        await waitForFinishedDiagrams(page);
        await expectErDrawnAtFullSize(page);
    });
});
