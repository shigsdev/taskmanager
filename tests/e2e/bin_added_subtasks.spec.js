/**
 * #494: since #465 an import Undo takes the open subtasks you added to its
 * tasks (Restore brings them back, Purge removes them), but the words
 * counted only the batch's own rows. The Settings Undo confirm, the Recycle
 * Bin row and its Restore / Purge dialogs now name them.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

async function importWithSubtask(request, source) {
    const r = await request.post("/api/import/tasks/confirm", {
        data: { source, candidates: [{ title: source + " imported", type: "work" }] },
    });
    expect(r.status()).toBe(201);
    const parentId = (await r.json()).tasks[0].id;
    const sub = await request.post("/api/tasks", {
        data: { title: source + " added", type: "work", parent_id: parentId } });
    expect(sub.status()).toBe(201);
    const logs = await (await request.get("/api/settings/imports")).json();
    const list = Array.isArray(logs) ? logs : (logs.imports || logs.logs || []);
    return list.find((l) => l.source === source).batch_id;
}

test.describe("#494 Undo and the bin count the subtasks you added", () => {
    test("Settings Undo confirm names them", async ({ page, request }) => {
        const source = `E2E494-undo-${Date.now()}`;
        await importWithSubtask(request, source);
        await page.goto("/settings?nosw=1");
        await page.waitForLoadState("networkidle");
        let said = "";
        page.once("dialog", async (d) => { said = d.message(); await d.dismiss(); });
        await page.locator(`button[data-source="${source}"]`).click();
        await expect.poll(() => said).toContain("1 subtask you added goes with it.");
        // Dismissed: nothing moved.
        await expect(page.locator(`button[data-source="${source}"]`)).toHaveText("Undo");
    });

    test("the bin row, Restore and Purge name them", async ({ page, request }) => {
        const source = `E2E494-bin-${Date.now()}`;
        const batchId = await importWithSubtask(request, source);
        expect((await request.post(`/api/recycle-bin/undo/${batchId}`)).status()).toBe(200);
        await page.goto("/recycle-bin?nosw=1");
        await page.waitForLoadState("networkidle");
        const item = page.locator(".recycle-item", { hasText: source });
        await expect(item.locator(".recycle-item-counts")).toHaveText("1 task +1 subtask you added");
        await item.getByRole("button", { name: "Restore" }).click();
        await expect(page.locator("#recycleModalBody"))
            .toHaveText("Restore 1 task from this batch? 1 subtask you added comes back with it.");
        await page.click("#recycleModalCancel");
        await item.getByRole("button", { name: "Purge" }).click();
        await expect(page.locator("#recycleModalBody")).toHaveText(
            "Permanently delete 1 task from this batch? 1 subtask you added is deleted with it. This cannot be undone.");
        await page.click("#recycleModalCancel");
    });

    test("a batch with no added subtasks reads as before (the quiet case)", async ({ page, request }) => {
        const source = `E2E494-plain-${Date.now()}`;
        const r = await request.post("/api/import/tasks/confirm", {
            data: { source, candidates: [{ title: source + " imported", type: "work" }] } });
        expect(r.status()).toBe(201);
        const logs = await (await request.get("/api/settings/imports")).json();
        const list = Array.isArray(logs) ? logs : (logs.imports || logs.logs || []);
        const batchId = list.find((l) => l.source === source).batch_id;
        expect((await request.post(`/api/recycle-bin/undo/${batchId}`)).status()).toBe(200);
        await page.goto("/recycle-bin?nosw=1");
        await page.waitForLoadState("networkidle");
        const item = page.locator(".recycle-item", { hasText: source });
        await expect(item.locator(".recycle-item-counts")).toHaveText("1 task");
        await item.getByRole("button", { name: "Restore" }).click();
        await expect(page.locator("#recycleModalBody")).toHaveText("Restore 1 task from this batch?");
        await page.click("#recycleModalCancel");
    });
});
