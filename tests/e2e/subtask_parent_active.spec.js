/**
 * #493: only an open task takes a new subtask (user decision 2026-10-16).
 * The server refuses a completed / cancelled / deleted parent; the task
 * panel stops offering "+ Add" on a task that isn't active.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

test.describe("#493 subtasks go under open tasks only", () => {
    test("a completed task's panel offers no + Add", async ({ page, request }) => {
        const tag = `E2E493 ${Date.now()}`;
        const parent = await (await request.post("/api/tasks", { data: { title: tag + " parent", type: "work" } })).json();
        await request.post("/api/tasks", { data: { title: tag + " child", type: "work", parent_id: parent.id } });
        expect((await request.post(`/api/tasks/${parent.id}/complete`, { data: { complete_subtasks: true } })).status()).toBe(200);
        try {
            await page.goto("/completed?nosw=1");
            await page.waitForLoadState("networkidle");
            // The title: a card's middle is its quick buttons at 375 (Re-open on /completed).
            await page.locator(".task-card", { hasText: tag + " parent" }).first().locator(".task-title").click();
            await expect(page.locator("#subtaskSection")).toBeVisible();
            // The input and button, not the row: a missing row is "hidden" too.
            await expect(page.locator("#subtaskInput")).toBeHidden();
            await expect(page.locator("#addSubtaskBtn")).toBeHidden();
            await expect(page.locator("#subtaskClosedNote")).toHaveText("Re-open this task to add a subtask.");
            // A completed card offers no + Subtask either.
            await expect(page.locator(".task-card", { hasText: tag + " parent" }).locator(".quick-subtask-btn"))
                .toHaveCount(0);
        } finally {
            await request.delete(`/api/tasks/${parent.id}`);
        }
    });

    test("an open task still takes a subtask from the panel (the quiet case)", async ({ page, request }) => {
        const tag = `E2E493 ${Date.now()}`;
        const parent = await (await request.post("/api/tasks", { data: { title: tag + " open", type: "work", tier: "today" } })).json();
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.locator(`.task-card[data-id="${parent.id}"] .task-title`).click();
            await expect(page.locator("#subtaskAddRow")).toBeVisible();
            await expect(page.locator("#subtaskClosedNote")).toBeHidden();
            await page.fill("#subtaskInput", tag + " step");
            await page.click("#addSubtaskBtn");
            await expect(page.locator("#subtaskItems")).toContainText(tag + " step");
        } finally {
            await request.delete(`/api/tasks/${parent.id}`);
        }
    });

    test("a stale tab adding under a parent completed elsewhere is told why", async ({ page, request }) => {
        const tag = `E2E493 ${Date.now()}`;
        const parent = await (await request.post("/api/tasks", { data: { title: tag + " stale", type: "work", tier: "today" } })).json();
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.locator(`.task-card[data-id="${parent.id}"] .task-title`).click();
            await expect(page.locator("#subtaskAddRow")).toBeVisible();
            // Completed in another tab while this panel was open.
            await request.post(`/api/tasks/${parent.id}/complete`);
            let said = "";
            page.once("dialog", async (d) => { said = d.message(); await d.dismiss(); });
            await page.fill("#subtaskInput", tag + " late");
            await page.click("#addSubtaskBtn");
            await expect.poll(() => said).toContain("That task is completed — re-open it first.");
            await expect(page.locator("#subtaskInput")).toHaveValue(tag + " late");
        } finally {
            await request.delete(`/api/tasks/${parent.id}`);
        }
    });
});
