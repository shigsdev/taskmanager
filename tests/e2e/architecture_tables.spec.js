/**
 * #492: /architecture's quality-gate tables were cut off on a phone — the
 * first column holds long unbroken test names in <code> (nowrap), which
 * forced it to ~350px and pushed the description / "prevents" columns past
 * the right edge (cells measured at 615, 656, 693px on a 375 screen). The
 * page itself didn't scroll sideways, so #405's check and the prod smoke
 * missed it. At 375 every cell must now sit inside the screen.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

test.describe("#492 /architecture gate tables fit a phone", () => {
    test("every quality-gates cell is inside the screen", async ({ page }, testInfo) => {
        test.skip(testInfo.project.name !== "chromium-mobile", "the phone layout; desktop has room");
        await page.goto("/architecture?nosw=1");
        await page.waitForLoadState("networkidle");
        const res = await page.evaluate(() => {
            const vw = document.documentElement.clientWidth;
            const tables = [...document.querySelectorAll("table.quality-gates")];
            const out = [];
            tables.forEach((t, i) => {
                for (const cell of t.querySelectorAll("th, td")) {
                    const r = cell.getBoundingClientRect();
                    if (r.right > vw + 1) {
                        out.push(`table ${i + 1}: "${cell.textContent.trim().slice(0, 30)}" → ${Math.round(r.right)}`);
                        break;  // one per table is enough to say it
                    }
                }
            });
            return { tables: tables.length, out, fits: document.documentElement.scrollWidth <= window.innerWidth };
        });
        expect(res.tables).toBeGreaterThanOrEqual(4);
        expect(res.out).toEqual([]);
        expect(res.fits).toBe(true);
    });

    test("desktop keeps the table layout (the quiet case)", async ({ page }, testInfo) => {
        test.skip(testInfo.project.name !== "chromium", "desktop only");
        await page.goto("/architecture?nosw=1");
        await page.waitForLoadState("networkidle");
        const display = await page.locator("table.quality-gates tr").first()
            .evaluate((el) => getComputedStyle(el).display);
        expect(display).toBe("table-row");
    });
});
