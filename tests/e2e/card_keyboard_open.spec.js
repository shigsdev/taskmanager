/**
 * #295: a board task card opened only on a click — no keyboard way to open
 * a task from the board, /tier/<name> or /completed. The card's title is
 * now a button for the keyboard (#454's makeOpener): Tab to it, Enter or
 * Space opens the task panel with focus on ✕, and #377 hands focus back to
 * the title on close. The ✓ and quick buttons stay their own Tab stops.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

async function newTask(request, tag, tier) {
    return (await request.post("/api/tasks", { data: { title: tag, type: "work", tier } })).json();
}

test.describe("#295 board cards open from the keyboard", () => {
    test("board: Enter on the title opens the panel; Escape → back on the title", async ({ page, request }) => {
        const tag = `E2E295 ${Date.now()}`;
        const task = await newTask(request, tag, "today");
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            const title = page.locator(`.task-card[data-id="${task.id}"] .task-title`);
            await expect(title).toHaveAttribute("role", "button");
            await expect(title).toHaveAttribute("aria-label", `Open task: ${tag}`);
            await title.focus();
            await page.keyboard.press("Enter");
            await expect(page.locator("#detailOverlay")).toBeVisible();
            await expect(page.locator("#detailTitle")).toHaveValue(tag);
            await expect.poll(() => page.evaluate(() =>
                document.activeElement.matches("#detailOverlay [data-panel-close]"))).toBe(true);
            await page.keyboard.press("Escape");
            await expect(page.locator("#detailOverlay")).toBeHidden();
            await expect(title).toBeFocused();
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("Space opens it too, and Tab from the title reaches the card's ✓", async ({ page, request }) => {
        const tag = `E2E295 ${Date.now()}`;
        const task = await newTask(request, tag, "today");
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            const card = page.locator(`.task-card[data-id="${task.id}"]`);
            await card.locator(".task-title").focus();
            await page.keyboard.press(" ");
            await expect(page.locator("#detailOverlay")).toBeVisible();
            await page.keyboard.press("Escape");
            await expect(card.locator(".task-title")).toBeFocused();
            // The card's own buttons are still reachable after the title.
            let reached = false;
            for (let i = 0; i < 4 && !reached; i++) {
                await page.keyboard.press("Tab");
                reached = await card.locator(".task-complete-btn")
                    .evaluate((el) => el === document.activeElement);
            }
            expect(reached).toBe(true);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("/completed: Enter on a done task's title opens it", async ({ page, request }) => {
        const tag = `E2E295 ${Date.now()}`;
        const task = await newTask(request, tag, "today");
        await request.post(`/api/tasks/${task.id}/complete`);
        try {
            await page.goto("/completed?nosw=1");
            await page.waitForLoadState("networkidle");
            const title = page.locator(`.task-card[data-id="${task.id}"] .task-title`);
            await title.focus();
            await page.keyboard.press("Enter");
            await expect(page.locator("#detailOverlay")).toBeVisible();
            await expect(page.locator("#detailTitle")).toHaveValue(tag);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("a click still opens the card (the quiet case)", async ({ page, request }) => {
        const tag = `E2E295 ${Date.now()}`;
        const task = await newTask(request, tag, "today");
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.locator(`.task-card[data-id="${task.id}"] .task-title`).click();
            await expect(page.locator("#detailOverlay")).toBeVisible();
            await expect(page.locator("#detailTitle")).toHaveValue(tag);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });
});
