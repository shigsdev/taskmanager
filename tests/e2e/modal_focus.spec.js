/**
 * #419: the pop-up dialogs move focus in when they open and back to what
 * opened them when they close — the side panels' #377 / #454 behaviour.
 * Opened from the keyboard (Enter on the control), closed by Escape and by
 * the mouse. One per way a dialog shows itself: display (recycle confirm,
 * 💡 Auto-categorize), the hidden attribute (Strength Forge how-to), and a
 * node built and removed (voice memo Make recurring). panel_keys_test-level
 * cases for all eight: tests/js/unit/modal_focus.test.js.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const activeIn = (page, sel) => page.evaluate((s) =>
    !!(document.activeElement && document.activeElement.closest(s)), sel);

test.describe("#419 pop-ups take focus in and hand it back", () => {
    test("Strength Forge how-to: Enter → ✕ has focus; Escape → back on ℹ️", async ({ page }) => {
        await page.goto("/strength-forge?nosw=1");
        await page.waitForLoadState("networkidle");
        const info = page.locator(".sf-exrow-info").first();
        await info.focus();
        await page.keyboard.press("Enter");
        const overlay = page.locator(".sf-modal-overlay");
        await expect(overlay).toBeVisible();
        await expect.poll(() => page.evaluate(() =>
            document.activeElement.matches(".sf-modal-overlay [data-panel-close]"))).toBe(true);
        await page.keyboard.press("Escape");
        await expect(overlay).toBeHidden();
        await expect(info).toBeFocused();
    });

    test("Strength Forge how-to by mouse: ✕ hands focus back, with no ring (the quiet case)", async ({ page }) => {
        await page.goto("/strength-forge?nosw=1");
        await page.waitForLoadState("networkidle");
        const info = page.locator(".sf-exrow-info").first();
        await info.click();
        const overlay = page.locator(".sf-modal-overlay");
        await expect(overlay).toBeVisible();
        await overlay.locator("[data-panel-close]").click();
        await expect(overlay).toBeHidden();
        await expect(info).toBeFocused();
        expect(await info.evaluate((el) => el.matches(":focus-visible"))).toBe(false);
    });

    test("recycle bin confirm: its own type-DELETE box keeps focus; Escape → back on Empty Bin", async ({ page }) => {
        await page.route("**/api/recycle-bin/summary", (r) => r.fulfill({
            json: { task_count: 1, goal_count: 0, batch_count: 1 } }));
        await page.route("**/api/recycle-bin", (r) => r.fulfill({ json: { batches: [] } }));
        await page.route("**/api/recycle-bin/empty", (r) =>
            r.fulfill({ status: 500, json: { error: "must not run" } }));
        await page.goto("/recycle-bin?nosw=1");
        await page.waitForLoadState("networkidle");
        const btn = page.locator("#recycleEmptyBtn");
        await btn.focus();
        await page.keyboard.press("Enter");
        const modal = page.locator("#recycleModalOverlay");
        await expect(modal).toBeVisible();
        await expect.poll(() => activeIn(page, "#recycleModalOverlay")).toBe(true);
        await page.keyboard.press("Escape");
        await expect(modal).toBeHidden();
        await expect(btn).toBeFocused();
    });

    test("💡 Auto-categorize: focus goes in; Escape → back on the button", async ({ page, request }) => {
        const task = await (await request.post("/api/tasks", {
            data: { title: `E2E419 inbox ${Date.now()}`, type: "work", tier: "inbox" } })).json();
        try {
            await page.route("**/api/inbox/categorize", (r) => r.fulfill({ json: {
                count: 1, capped: false,
                suggestions: [{
                    task_id: task.id, title: task.title, suggested_tier: "this_week",
                    suggested_project_id: null, suggested_goal_id: null,
                    suggested_due_date: null, suggested_type: "work", reason: "fixture",
                }],
            } }));
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            const btn = page.locator("#autoCategorizeBtn");
            await btn.focus();
            await page.keyboard.press("Enter");
            const modal = page.locator("#autoCategorizeModal");
            await expect(modal.locator(`tr[data-task-id="${task.id}"]`)).toBeVisible({ timeout: 5000 });
            await expect.poll(() => activeIn(page, "#autoCategorizeModal")).toBe(true);
            await page.keyboard.press("Escape");
            await expect(modal).toBeHidden();
            await expect(btn).toBeFocused();
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("voice memo Make recurring (built, then removed): Escape → back on its button", async ({ page }) => {
        await page.route("**/api/voice-memo", (r) => r.fulfill({ json: {
            transcript: "stubbed",
            candidates: [{ title: "E2E419 weekly", type: "work", tier: "this_week",
                           due_date: null, route: "task", is_task: true }],
        } }));
        await page.goto("/voice-memo?nosw=1");
        await page.click("#voiceRecordBtn");
        await expect(page.locator("#voiceStopBtn")).toBeVisible({ timeout: 5000 });
        await page.waitForTimeout(600);
        await page.click("#voiceStopBtn");
        const recur = page.locator("#voiceCandidates .voice-candidate").first()
            .locator(".voice-candidate-recur-btn");
        await expect(recur).toBeVisible({ timeout: 10000 });
        await recur.focus();
        await page.keyboard.press("Enter");
        await expect(page.locator(".voice-recur-overlay")).toHaveCount(1);
        await expect.poll(() => activeIn(page, ".voice-recur-overlay")).toBe(true);
        await page.keyboard.press("Escape");
        await expect(page.locator(".voice-recur-overlay")).toHaveCount(0);
        await expect(recur).toBeFocused();
    });
});
