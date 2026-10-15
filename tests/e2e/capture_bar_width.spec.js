/**
 * #449: the capture box was 67 px wide on the phone board (117 px on a
 * section page) — the type select and four icon buttons took the row. At
 * phone width the text box now has the first row to itself and the select
 * and buttons wrap onto the next; at desktop width nothing moves.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const PAGES = ["/", "/tier/today", "/goals"];

test.describe("#449 capture box width", () => {
    for (const path of PAGES) {
        test(`${path}: the capture box fits its text`, async ({ page, viewport }) => {
            await page.goto(`${path}?nosw=1`);
            const input = page.locator("#captureInput");
            await expect(input).toBeVisible();
            const m = await page.evaluate(() => {
                const bar = document.getElementById("captureBar");
                const input = document.getElementById("captureInput");
                const others = [...bar.children].filter(
                    (el) => el !== input && el.getBoundingClientRect().width > 0,
                );
                const ir = input.getBoundingClientRect();
                return {
                    inputW: ir.width,
                    inputTop: ir.top,
                    inputBottom: ir.bottom,
                    barW: bar.getBoundingClientRect().width,
                    others: others.map((el) => {
                        const r = el.getBoundingClientRect();
                        return { top: r.top, right: r.right };
                    }),
                    sw: document.documentElement.scrollWidth,
                    iw: window.innerWidth,
                };
            });
            expect(m.others.length).toBeGreaterThan(0);
            expect(m.sw).toBeLessThanOrEqual(m.iw);
            for (const o of m.others) expect(o.right).toBeLessThanOrEqual(m.iw);
            if (viewport.width <= 600) {
                // Its own row, nearly the bar's full width; the rest below it.
                expect(m.inputW).toBeGreaterThanOrEqual(m.barW - 2);
                expect(m.inputW).toBeGreaterThanOrEqual(300);
                for (const o of m.others) expect(o.top).toBeGreaterThanOrEqual(m.inputBottom);
            } else {
                // Desktop: one row, as before (the quiet case).
                for (const o of m.others) expect(o.top).toBeLessThan(m.inputBottom);
            }
        });
    }
});
