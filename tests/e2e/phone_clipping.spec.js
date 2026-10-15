/**
 * #452: things clipped or broken on the phone (and a few above it).
 *  - A Completed card's "Re-open" menu was cut to the card (overflow:hidden
 *    at <=600px, and inline from swipe.js on touch devices): 0 of 7 options
 *    could be tapped.
 *  - Swipe-to-reveal slid the whole card left with its buttons still past
 *    its right edge, so overflow:hidden showed blank space; above 600px on a
 *    touch device the buttons showed unstyled inside the card.
 *  - `hidden` lost to an author `display:` rule (Utilities status boxes,
 *    Strength Forge detail rows).
 *  - The board's bulk toolbar was capped at half the viewport (fixed +
 *    left:50%) and wrapped to three rows at 1280px.
 *  - The Settings import-history table was cut off at 375px with no scroll.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const hittable = (page, sel) => page.evaluate((s) => [...document.querySelectorAll(s)].map((b) => {
    const r = b.getBoundingClientRect();
    if (!r.width || !r.height) return false;
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return hit === b || b.contains(hit);
}), sel);

async function swipeLeft(page, sel, dx) {
    await page.evaluate(([s, d]) => {
        const card = document.querySelector(s);
        const r = card.getBoundingClientRect();
        const y = r.top + r.height / 2;
        const x0 = r.right - 20;
        const touch = (x) => new Touch({ identifier: 1, target: card, clientX: x, clientY: y });
        const fire = (type, x) => card.dispatchEvent(new TouchEvent(type, {
            bubbles: true, cancelable: true,
            touches: type === "touchend" ? [] : [touch(x)],
            targetTouches: type === "touchend" ? [] : [touch(x)],
            changedTouches: [touch(x)],
        }));
        fire("touchstart", x0);
        for (let i = 1; i <= 5; i++) fire("touchmove", x0 - (d * i) / 5);
        fire("touchend", x0 - d);
    }, [sel, dx]);
}

test.describe("#452 phone clipping", () => {
    test("a Completed card's Re-open menu can be tapped in full", async ({ page, request }) => {
        // Two completed cards: the menu opens on the upper one, over the
        // other (each completed card is its own stacking context).
        const tag = `E2E452 ${Date.now()}`;
        const below = await (await request.post("/api/tasks", { data: { title: tag + " below", type: "work" } })).json();
        await request.post(`/api/tasks/${below.id}/complete`);
        const t = await (await request.post("/api/tasks", { data: { title: tag, type: "work" } })).json();
        await request.post(`/api/tasks/${t.id}/complete`);
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.click("#tierCompleted .collapse-toggle");
            const card = page.locator(`#completedList .task-card[data-id="${t.id}"]`);
            await expect(card).toBeVisible();
            await card.scrollIntoViewIfNeeded();
            await card.locator(".reopen-btn").click();
            await expect(card.locator(".reopen-dropdown button")).toHaveCount(7);
            const hits = await hittable(page, `#completedList .task-card[data-id="${t.id}"] .reopen-dropdown button`);
            expect(hits).toEqual([true, true, true, true, true, true, true]);
        } finally {
            await request.delete(`/api/tasks/${t.id}`);
            await request.delete(`/api/tasks/${below.id}`);
        }
    });

});

// swipe.js only wires cards up on a touch device, and the mobile project
// doesn't emulate touch — this group does.
test.describe("#452 swipe on a touch screen", () => {
    test.use({ hasTouch: true, viewport: { width: 375, height: 812 } });

    test("swipe reveals Move and Delete inside the card", async ({ page, request }, testInfo) => {
        test.skip(testInfo.project.name !== "chromium-mobile", "one touch run is enough");
        const tag = `E2E452 swipe ${Date.now()}`;
        const t = await (await request.post("/api/tasks", { data: { title: tag, type: "work", tier: "today" } })).json();
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            const sel = `.task-card[data-id="${t.id}"]`;
            await page.locator(sel).scrollIntoViewIfNeeded();
            await expect(page.locator(`${sel} .swipe-actions`)).toHaveCount(1);
            // Before a swipe the buttons aren't showing.
            expect(await hittable(page, `${sel} .swipe-actions button`)).toEqual([false, false]);
            await swipeLeft(page, sel, 110);
            await expect(page.locator(sel)).toHaveClass(/swiped/);
            await expect.poll(() => hittable(page, `${sel} .swipe-actions button`)).toEqual([true, true]);
            // Wider touch screen (tablet): still hidden until swiped, and styled.
            await page.setViewportSize({ width: 820, height: 1000 });
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.locator(sel).scrollIntoViewIfNeeded();
            expect(await hittable(page, `${sel} .swipe-actions button`)).toEqual([false, false]);
            await swipeLeft(page, sel, 110);
            await expect.poll(() => hittable(page, `${sel} .swipe-actions button`)).toEqual([true, true]);
            const bg = await page.locator(`${sel} .swipe-action-delete`).evaluate((b) => getComputedStyle(b).backgroundColor);
            expect(bg).not.toBe("rgba(0, 0, 0, 0)");
        } finally {
            await request.delete(`/api/tasks/${t.id}`);
        }
    });


    test("on a touch screen the Re-open menu is reachable and the page doesn't widen", async ({ page, request }, testInfo) => {
        test.skip(testInfo.project.name !== "chromium-mobile", "one touch run is enough");
        const tag = `E2E452 touch ${Date.now()}`;
        const below = await (await request.post("/api/tasks", { data: { title: tag + " below", type: "work" } })).json();
        await request.post(`/api/tasks/${below.id}/complete`);
        const t = await (await request.post("/api/tasks", { data: { title: tag, type: "work" } })).json();
        await request.post(`/api/tasks/${t.id}/complete`);
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.click("#tierCompleted .collapse-toggle");
            const card = page.locator(`#completedList .task-card[data-id="${t.id}"]`);
            await expect(card.locator(".swipe-actions")).toHaveCount(1); // swipe.js wired it
            await card.scrollIntoViewIfNeeded();
            await card.locator(".reopen-btn").click();
            const hits = await hittable(page, `#completedList .task-card[data-id="${t.id}"] .reopen-dropdown button`);
            expect(hits).toEqual([true, true, true, true, true, true, true]);
            const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: innerWidth }));
            expect(m.sw).toBeLessThanOrEqual(m.iw);
            expect(m.iw).toBe(375);
        } finally {
            await request.delete(`/api/tasks/${t.id}`);
            await request.delete(`/api/tasks/${below.id}`);
        }
    });
});

test.describe("#452 phone clipping (2)", () => {
    test("hidden means hidden: Utilities status boxes, Strength Forge detail rows", async ({ page }) => {
        for (const path of ["/utilities", "/strength-forge"]) {
            await page.goto(`${path}?nosw=1`);
            await page.waitForLoadState("networkidle");
            const shown = await page.evaluate(() => [...document.querySelectorAll("[hidden]")]
                .filter((e) => getComputedStyle(e).display !== "none")
                .map((e) => e.className || e.id));
            expect(shown, path).toEqual([]);
        }
    });

    test("the board's bulk toolbar is one row at desktop width", async ({ page, viewport }) => {
        test.skip(viewport.width < 1000, "desktop width");
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator(".task-card .bulk-select-check").first().click();
        const tb = page.locator("#bulkToolbar");
        await expect(tb).toBeVisible();
        const m = await tb.evaluate((el) => {
            const tops = [...el.children].filter((c) => c.getBoundingClientRect().width > 0)
                .map((c) => Math.round(c.getBoundingClientRect().top + c.getBoundingClientRect().height / 2));
            const r = el.getBoundingClientRect();
            return { rows: new Set(tops).size, left: r.left, right: r.right, vw: innerWidth };
        });
        expect(m.rows).toBe(1);
        expect(m.left).toBeGreaterThanOrEqual(0);
        expect(m.right).toBeLessThanOrEqual(m.vw);
    });

    test("Settings tables scroll sideways instead of being cut off", async ({ page, viewport }) => {
        test.skip(viewport.width >= 700, "phone width");
        await page.goto("/settings?nosw=1");
        await page.waitForLoadState("networkidle");
        const t = await page.evaluate(() => [...document.querySelectorAll(".settings-section table")].map((tbl) => {
            // The box that clips it is the table itself (display:block) or its parent.
            const box = getComputedStyle(tbl).overflowX === "auto" ? tbl : tbl.parentElement;
            return {
                id: tbl.id,
                fits: tbl.scrollWidth <= box.clientWidth + 1,
                scrolls: ["auto", "scroll"].includes(getComputedStyle(box).overflowX),
            };
        }));
        expect(t.length).toBeGreaterThan(0);
        for (const row of t) expect(row.fits || row.scrolls, row.id).toBe(true);
        const sw = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
        expect(sw).toBe(true);
    });
});
