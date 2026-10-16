/**
 * #478: the Recycle Bin counts projects.
 *
 * The server always counted them (project_count), but the page added only
 * tasks + goals: a bin holding just an undone project import read "No undone
 * imports." with Empty Bin disabled, its row read "0 items", the dialogs
 * never named the projects, and Settings → "Recycle Bin (N)" left them out.
 * Nothing here is written — the bin's answers are stubbed and Escape closes
 * each dialog.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const BATCH = {
    batch_id: "00000000-0000-0000-0000-000000000478", source: "projects_import",
    imported_at: "2026-10-10T12:00:00Z", undone_at: "2026-10-11T12:00:00Z",
    task_count: 0, goal_count: 0, restore_goal_count: 0,
    project_count: 2, restore_project_count: 1,
};
const SUMMARY = { batch_count: 1, task_count: 0, goal_count: 0, project_count: 2, deleted_task_count: 0 };

async function stubBin(page, summary, batches) {
    await page.route("**/api/recycle-bin/summary", (r) => r.fulfill({ json: summary }));
    await page.route("**/api/recycle-bin", (r) => r.fulfill({ json: { batches } }));
    for (const p of ["**/api/recycle-bin/empty", "**/api/recycle-bin/purge/*", "**/api/recycle-bin/restore/*"]) {
        await page.route(p, (r) => r.fulfill({ status: 500, json: { error: "must not run" } }));
    }
}

async function dialogBody(page, open) {
    await open();
    const modal = page.locator("#recycleModalOverlay");
    await expect(modal).toBeVisible();
    const text = await page.locator("#recycleModalBody").textContent();
    await page.keyboard.press("Escape");
    await expect(modal).toBeHidden();
    return text;
}

test.describe("#478 the Recycle Bin counts projects", () => {
    test("a projects-only bin can be emptied, and every count names the projects", async ({ page }) => {
        await stubBin(page, SUMMARY, [BATCH]);
        await page.goto("/recycle-bin?nosw=1");
        await page.waitForLoadState("networkidle");

        await expect(page.locator("#recycleSummaryText")).toHaveText("2 projects across 1 batch.");
        await expect(page.locator("#recycleEmptyBtn")).toBeEnabled();
        await expect(page.locator("#recycleList .recycle-item-counts")).toHaveText("2 projects");

        const row = page.locator("#recycleList .recycle-item");
        expect(await dialogBody(page, () => row.getByRole("button", { name: "Restore" }).click()))
            .toBe("Restore 1 project from this batch?");
        expect(await dialogBody(page, () => row.getByRole("button", { name: "Purge" }).click()))
            .toBe("Permanently delete 2 projects from this batch? This cannot be undone.");
        expect(await dialogBody(page, () => page.locator("#recycleEmptyBtn").click()))
            .toContain("2 projects across 1 batch.");
    });

    test("an empty bin still says so, with Empty Bin off (the quiet case)", async ({ page }) => {
        await stubBin(page, { batch_count: 0, task_count: 0, goal_count: 0, project_count: 0,
                              deleted_task_count: 0 }, []);
        await page.goto("/recycle-bin?nosw=1");
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#recycleSummaryText")).toHaveText("No undone imports.");
        await expect(page.locator("#recycleEmptyBtn")).toBeDisabled();
    });

    test("a tasks-and-goals batch reads as it did", async ({ page }) => {
        await stubBin(page, { batch_count: 1, task_count: 3, goal_count: 1, project_count: 0,
                              deleted_task_count: 0 },
                      [{ ...BATCH, task_count: 3, goal_count: 1, restore_goal_count: 1,
                         project_count: 0, restore_project_count: 0 }]);
        await page.goto("/recycle-bin?nosw=1");
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#recycleSummaryText")).toHaveText("3 tasks and 1 goal across 1 batch.");
        await expect(page.locator("#recycleList .recycle-item-counts")).toHaveText("3 tasks and 1 goal");
    });

    test("Settings counts the projects in the bin", async ({ page }) => {
        await page.route("**/api/recycle-bin/summary", (r) => r.fulfill({ json:
            { ...SUMMARY, task_count: 1, deleted_task_count: 2 } }));
        await page.goto("/settings?nosw=1");
        await expect(page.locator("#settingsBinCount")).toHaveText("5");
    });
});
