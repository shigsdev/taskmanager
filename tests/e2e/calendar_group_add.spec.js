/**
 * #293: /calendar's day cells got a "+" in #454, but the Unscheduled side
 * panel's sections (Inbox, This Week · no day, Next Week · no day, Backlog &
 * Freezer) had no way to add a task straight into them. Each group header
 * now has a "+" that opens a new task already in that section, with no date.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

test.describe("#293 add a task straight into an Unscheduled section", () => {
    test("Next Week · no day: + opens a new task in Next Week, Save files it there undated", async ({ page, request }) => {
        const tag = `E2E293 ${Date.now()}`;
        await page.goto("/calendar?nosw=1");
        await page.waitForLoadState("networkidle");
        const zone = page.locator('.calendar-unscheduled-zone[data-drop-tier="next_week"]');
        const add = zone.locator(".calendar-group-add");
        await expect(add).toHaveAttribute("aria-label", "Add a task to Next Week");
        await add.click();
        await expect(page.locator("#detailOverlay")).toBeVisible();
        await expect(page.locator("#detailTier")).toHaveValue("next_week");
        await expect(page.locator("#detailDueDate")).toHaveValue("");
        await page.fill("#detailTitle", tag);
        await page.locator('#detailOverlay button[type="submit"]').click();
        await expect(page.locator("#detailOverlay")).toBeHidden();
        const mine = async () => (await (await request.get("/api/tasks")).json())
            .filter((t) => t.title === tag);
        await expect.poll(async () => (await mine()).length).toBe(1);
        const made = await mine();
        try {
            expect(made[0].tier).toBe("next_week");
            expect(made[0].due_date).toBeNull();
            // It shows up in that group on the calendar.
            await expect(zone).toContainText(tag);
        } finally {
            for (const t of made) await request.delete(`/api/tasks/${t.id}`);
        }
    });

    test("every group has one, and Backlog & Freezer files to Backlog", async ({ page }) => {
        await page.goto("/calendar?nosw=1");
        await page.waitForLoadState("networkidle");
        const want = { inbox: "inbox", this_week: "this_week", next_week: "next_week", backlog: "backlog" };
        for (const [dropTier, tier] of Object.entries(want)) {
            await page.locator(`.calendar-unscheduled-zone[data-drop-tier="${dropTier}"] .calendar-group-add`).click();
            await expect(page.locator("#detailTier")).toHaveValue(tier);
            await page.keyboard.press("Escape");
            await expect(page.locator("#detailOverlay")).toBeHidden();
        }
    });

    test("a day's + still dates the task (the quiet case)", async ({ page }) => {
        await page.goto("/calendar?nosw=1");
        await page.waitForLoadState("networkidle");
        const cell = page.locator(".calendar-cell:not(.calendar-cell-past)").nth(2);
        const iso = await cell.getAttribute("data-date");
        await cell.locator(".calendar-cell-add").click();
        await expect(page.locator("#detailDueDate")).toHaveValue(iso);
    });
});
