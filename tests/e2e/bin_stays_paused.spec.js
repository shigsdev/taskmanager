/**
 * #373: Purge and Empty Bin name the repeating tasks that stay paused.
 *
 * Purging a batch clears the "resume when unarchived" marker for its
 * projects and goals, so a repeating task the undo paused never comes back
 * on its own. The server lists them (`stays_paused`); the two dialogs now
 * say so. Nothing here is written — the bin's answers are stubbed and
 * Escape closes each dialog.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const BATCH = {
    batch_id: "00000000-0000-0000-0000-000000000373", source: "projects_import",
    imported_at: "2026-10-10T12:00:00Z", undone_at: "2026-10-11T12:00:00Z",
    task_count: 0, goal_count: 0, restore_goal_count: 0,
    project_count: 1, restore_project_count: 1, subtask_count: 0,
    stays_paused: [{ id: "r1", title: "Water plants" }],
};
const SUMMARY = {
    batch_count: 1, task_count: 0, goal_count: 0, project_count: 1, deleted_task_count: 0,
    stays_paused: [{ id: "r1", title: "Water plants" }, { id: "r2", title: "Stretch" }],
};

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

test.describe("#373 Purge and Empty Bin name the repeating tasks left paused", () => {
    test("Purge and Empty name them; Restore doesn't", async ({ page }) => {
        await stubBin(page, SUMMARY, [BATCH]);
        await page.goto("/recycle-bin?nosw=1");
        await page.waitForLoadState("networkidle");

        const row = page.locator("#recycleList .recycle-item");
        expect(await dialogBody(page, () => row.getByRole("button", { name: "Purge" }).click()))
            .toBe("Permanently delete 1 project from this batch? " +
                  "1 repeating task on it stays paused: \"Water plants\". " +
                  "Resume it on Recurring if you still want it. This cannot be undone.");
        expect(await dialogBody(page, () => page.locator("#recycleEmptyBtn").click()))
            .toContain("2 repeating tasks on them stay paused: \"Water plants\", \"Stretch\". " +
                       "Resume them on Recurring if you still want them. This cannot be undone.");
        expect(await dialogBody(page, () => row.getByRole("button", { name: "Restore" }).click()))
            .toBe("Restore 1 project from this batch?");
    });

    test("a batch with none reads exactly as before (the quiet case)", async ({ page }) => {
        await stubBin(page, { ...SUMMARY, stays_paused: [] }, [{ ...BATCH, stays_paused: [] }]);
        await page.goto("/recycle-bin?nosw=1");
        await page.waitForLoadState("networkidle");

        const row = page.locator("#recycleList .recycle-item");
        expect(await dialogBody(page, () => row.getByRole("button", { name: "Purge" }).click()))
            .toBe("Permanently delete 1 project from this batch? This cannot be undone.");
        const empty = await dialogBody(page, () => page.locator("#recycleEmptyBtn").click());
        expect(empty).not.toContain("repeating");
        expect(empty).toMatch(/1 batch\. This cannot be undone\.$/);
    });
});
