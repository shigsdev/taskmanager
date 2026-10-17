/**
 * #285 (user decision 2026-10-17): a BAU goal fits work AND personal. It used
 * to count as work-only, so the /utilities cleanup card flagged every
 * personal project under the user's "Personal BAU" goal as a cross-side link
 * (the "stale BAU entries"), and a personal task's goal picker hid BAU goals.
 * Real data; the voice/scan half is pytest's (test_voice_memo.py).
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

test.describe("#285 BAU goals fit both work and personal", () => {
    test("/utilities doesn't flag a personal project on a BAU goal; a work goal still is", async ({ page, request }) => {
        const tag = `E2E285 ${Date.now()}`;
        const bau = await (await request.post("/api/goals", {
            data: { title: tag + " Personal BAU", category: "bau", priority: "should" } })).json();
        const work = await (await request.post("/api/goals", {
            data: { title: tag + " work goal", category: "work", priority: "should" } })).json();
        const onBau = await (await request.post("/api/projects", {
            data: { name: tag + " birthday", type: "personal", goal_id: bau.id } })).json();
        const onWork = await (await request.post("/api/projects", {
            data: { name: tag + " side gig", type: "personal", goal_id: work.id } })).json();
        try {
            await page.goto("/utilities?nosw=1");
            await page.waitForLoadState("networkidle");
            const audit = page.locator("[data-pg-audit]");
            // The quiet case first: a personal project on a WORK goal is still flagged.
            await expect(audit.locator(".pg-row-cross", { hasText: tag + " side gig" })).toHaveCount(1);
            await expect(audit.locator(".pg-row-cross", { hasText: tag + " birthday" })).toHaveCount(0);
        } finally {
            for (const p of [onBau, onWork]) await request.delete(`/api/projects/${p.id}`);
            for (const g of [bau, work]) await request.delete(`/api/goals/${g.id}`);
        }
    });

    test("a personal task's goal picker lists a BAU goal", async ({ page, request }) => {
        const tag = `E2E285 ${Date.now()}`;
        const bau = await (await request.post("/api/goals", {
            data: { title: tag + " Personal BAU", category: "bau", priority: "should" } })).json();
        const task = await (await request.post("/api/tasks", {
            data: { title: tag + " renew registration", type: "personal", tier: "today" } })).json();
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.locator(`.task-card[data-id="${task.id}"] .task-title`).click();
            await expect(page.locator("#detailOverlay")).toBeVisible();
            const opts = await page.locator("#detailGoal option").allTextContents();
            expect(opts.some((t) => t.includes(tag + " Personal BAU"))).toBe(true);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
            await request.delete(`/api/goals/${bau.id}`);
        }
    });
});
