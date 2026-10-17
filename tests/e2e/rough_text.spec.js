/**
 * #491: real titles are rougher than the seed's — a ~300-character line, or
 * a bare URL with nothing to wrap on (the #138 shape). The pages that list
 * tasks must keep them inside the screen at every width. Found by #491's
 * Phase 6 on the rougher seed: /print at 375 scrolled sideways (a flex
 * title can't shrink below an unbroken string).
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const URL_TITLE = "E2E491 https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz"
    + "0123456789AbCdEfGhIj/edit?usp=sharing&ouid=104857600123456789012";
const LONG_TITLE = "E2E491 " + "Draft the long-form write-up of the spring vendor review ".repeat(5).trim();

test.describe("#491 rough titles stay on screen", () => {
    const made = [];
    test.beforeAll(async ({ request }) => {
        for (const [title, tier] of [[URL_TITLE, "this_week"], [LONG_TITLE, "today"]]) {
            const r = await request.post("/api/tasks", { data: { title, type: "personal", tier } });
            expect(r.status()).toBe(201);
            made.push((await r.json()).id);
        }
    });
    test.afterAll(async ({ request }) => {
        for (const id of made) await request.delete(`/api/tasks/${id}`);
    });

    for (const path of ["/print", "/", "/tier/this_week", "/calendar"]) {
        test(`${path}: no sideways scroll, every rough title inside the screen`, async ({ page }) => {
            await page.goto(path + "?nosw=1");
            await page.waitForLoadState("networkidle");
            const res = await page.evaluate(() => {
                const out = [];
                for (const el of document.querySelectorAll("body *")) {
                    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.includes("E2E491"));
                    if (!own) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width && r.right > window.innerWidth + 1) out.push(`${el.className} → ${Math.round(r.right)}`);
                }
                return { fits: document.documentElement.scrollWidth <= window.innerWidth, out };
            });
            expect(res.out).toEqual([]);
            expect(res.fits).toBe(true);
        });
    }
});
