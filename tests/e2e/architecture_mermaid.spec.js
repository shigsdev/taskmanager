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
const { test, expect } = require("./lane"); // #402: per-worker lane server

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

    test("#404: ARCHITECTURE.md's own diagrams draw, readably", async ({ page }) => {
        // render_architecture_md re-wraps ```mermaid fences as
        // <pre class="mermaid">; before #404 they were <code> source text.
        // The /scan diagram was also flowchart LR: 3416px wide, fitted to
        // 762px = ~3.6px labels, so "it has an svg" is not enough here.
        await page.goto("/architecture?nosw=1");
        await waitForFinishedDiagrams(page);
        const md = page.locator(".architecture-md");
        await expect(md.locator("code.language-mermaid"), "a diagram is still shown as source")
            .toHaveCount(0);
        const blocks = md.locator("pre.mermaid");
        expect(await blocks.count()).toBeGreaterThanOrEqual(2);
        await md.evaluate((el) => { el.closest("details").open = true; });
        const drawn = await blocks.evaluateAll((pres) => pres.map((pre) => {
            const svg = pre.querySelector(":scope > svg");
            const label = svg.querySelector(".nodeLabel");
            const scale = svg.getBoundingClientRect().width / svg.viewBox.baseVal.width;
            return {
                error: /Syntax error/.test(pre.textContent),
                fontPx: parseFloat(getComputedStyle(label).fontSize) * scale,
            };
        }));
        const desktop = page.viewportSize().width >= 1000;
        drawn.forEach((d, i) => {
            expect(d.error, `ARCHITECTURE.md diagram #${i + 1} is a syntax error`).toBe(false);
            // Mobile fits every diagram to ~330px; pinch-zoom covers it there.
            if (desktop) {
                expect(d.fontPx, `ARCHITECTURE.md diagram #${i + 1} labels ~${d.fontPx.toFixed(1)}px`)
                    .toBeGreaterThanOrEqual(10);
            }
        });
    });

    // #405: open every <details> so each diagram has a real box to measure.
    async function openAllDetails(page) {
        await page.evaluate(() => document.querySelectorAll("details").forEach((d) => { d.open = true; }));
    }

    test("#405 phone: every diagram draws full size and swipes inside its own box", async ({ page }) => {
        test.skip(page.viewportSize().width > 700, "phone layout only");
        await page.goto("/architecture?nosw=1");
        await waitForFinishedDiagrams(page);
        await openAllDetails(page);
        const boxes = await page.locator("pre.mermaid").evaluateAll((pres) => pres.map((pre) => {
            const svg = pre.querySelector(":scope > svg");
            const label = svg.querySelector(".nodeLabel, .er.entityLabel, text");
            pre.scrollLeft = 0;
            const preBox = pre.getBoundingClientRect();
            const svgBox = svg.getBoundingClientRect();
            return {
                fontPx: parseFloat(getComputedStyle(label).fontSize) * svgBox.width / svg.viewBox.baseVal.width,
                wider: svgBox.width > pre.clientWidth,
                scrolls: pre.scrollWidth > pre.clientWidth,
                leftClippedPx: preBox.left - svgBox.left,
            };
        }));
        boxes.forEach((b, i) => {
            expect(b.fontPx, `diagram #${i + 1} labels ~${b.fontPx.toFixed(1)}px`).toBeGreaterThanOrEqual(10);
            if (b.wider) expect(b.scrolls, `diagram #${i + 1} is wider than its box but can't scroll`).toBe(true);
            expect(b.leftClippedPx, `diagram #${i + 1} left edge is cut off`).toBeLessThanOrEqual(0);
        });
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(overflow, "the page itself scrolls sideways").toBeLessThanOrEqual(0);
    });

    test("#405 phone: no diagram opens on an empty first screen", async ({ page }) => {
        test.skip(page.viewportSize().width > 700, "phone layout only");
        await page.goto("/architecture?nosw=1");
        await waitForFinishedDiagrams(page);
        await openAllDetails(page);
        // Phase 6 found two that did: "What's running" (#2) starts 947px down
        // its left column; #11 centres its top nodes ~400px to the right.
        // Counts drawn nodes inside each box's first screen as scrolled.
        await expect.poll(() => page.locator("pre.mermaid").evaluateAll((pres) => pres.map((box) => {
            const origin = box.getBoundingClientRect();
            const viewH = Math.min(box.clientHeight, window.innerHeight);
            return [...box.querySelectorAll("g.node, g[id^='entity-']")].filter((g) => {
                const r = g.getBoundingClientRect();
                const x = r.left - origin.left;
                return x < box.clientWidth && x + r.width > 0 && r.top - origin.top < viewH;
            }).length;
        })), { timeout: 5000 }).not.toContain(0);

        // The full-screen view starts somewhere with content too.
        await page.locator(".diagram-zoom-btn").nth(1).click();
        const inDialog = await page.locator("#diagramZoomBody").evaluate((box) => {
            const origin = box.getBoundingClientRect();
            const viewH = Math.min(box.clientHeight, window.innerHeight);
            return [...box.querySelectorAll("g.node")].filter((g) => {
                const r = g.getBoundingClientRect();
                const x = r.left - origin.left;
                return x < box.clientWidth && x + r.width > 0 && r.top - origin.top < viewH;
            }).length;
        });
        expect(inDialog, "full-screen view opened on an empty screen").toBeGreaterThan(0);
        await page.keyboard.press("Escape");
    });

    test("#405 phone: Full screen opens a diagram, Escape and ✕ put it back", async ({ page }) => {
        test.skip(page.viewportSize().width > 700, "phone layout only");
        await page.goto("/architecture?nosw=1");
        const total = await waitForFinishedDiagrams(page);
        const buttons = page.locator(".diagram-zoom-btn");
        await expect(buttons).toHaveCount(total);
        await expect(buttons.first()).toBeVisible();
        const box = await buttons.first().boundingBox();
        expect(box.height, "Full screen button under the 44px tap floor").toBeGreaterThanOrEqual(44);

        const dialog = page.locator("#diagramZoom");
        const firstPre = page.locator("pre.mermaid").first();
        const naturalW = await firstPre.locator(":scope > svg")
            .evaluate((svg) => svg.viewBox.baseVal.width);

        for (const how of ["Escape", "close button"]) {
            await buttons.first().click();
            await expect(dialog, `${how}: dialog did not open`).toHaveAttribute("open", "");
            await expect(firstPre.locator(":scope > svg")).toHaveCount(0);
            const shown = await dialog.locator("#diagramZoomBody > svg")
                .evaluate((svg) => svg.getBoundingClientRect().width);
            expect(Math.abs(shown - naturalW), "not shown at natural size").toBeLessThan(2);
            await expect(page.locator("#diagramZoomClose")).toBeFocused();
            await expect(page.locator("html")).toHaveClass(/diagram-zoom-open/);

            if (how === "Escape") await page.keyboard.press("Escape");
            else await page.locator("#diagramZoomClose").click();

            await expect(dialog, `${how}: dialog did not close`).not.toHaveAttribute("open", "");
            await expect(firstPre.locator(":scope > svg"), `${how}: svg not back in its box`).toHaveCount(1);
            await expect(buttons.first()).toBeFocused();
            await expect(page.locator("html")).not.toHaveClass(/diagram-zoom-open/);
        }
    });

    test("#405 desktop: no Full-screen buttons, and diagrams still fit their box", async ({ page }) => {
        test.skip(page.viewportSize().width <= 700, "desktop layout only");
        await page.goto("/architecture?nosw=1");
        await waitForFinishedDiagrams(page);
        await openAllDetails(page);
        for (const btn of await page.locator(".diagram-zoom-btn").all()) {
            await expect(btn).toBeHidden();
        }
        // What fit-to-width did, and what useMaxWidth: false + CSS must keep
        // doing on desktop: a flowchart is drawn at min(natural, box) width.
        const widths = await page.locator("pre.mermaid").evaluateAll((pres) => pres
            .filter((pre) => !pre.closest("#schema")) // the ER scrolls at natural size (#391)
            .map((pre) => {
                const svg = pre.querySelector(":scope > svg");
                const cs = getComputedStyle(pre);
                const inner = pre.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
                return {
                    drawn: svg.getBoundingClientRect().width,
                    expected: Math.min(svg.viewBox.baseVal.width, inner),
                };
            }));
        widths.forEach((w, i) => {
            expect(Math.abs(w.drawn - w.expected), `flowchart #${i + 1} drawn ${w.drawn}px, expected ${w.expected}px`)
                .toBeLessThan(2);
        });
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
