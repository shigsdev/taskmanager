/**
 * #465: Settings → Import History → Undo used to delete only the batch's own
 * tasks, so a subtask added to an imported task afterwards stayed on the
 * board under a deleted parent. It now goes with its parent, and the Recycle
 * Bin's Restore brings it back.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const stamp = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
const statusOf = async (request, id) =>
    (await (await request.get(`/api/tasks/${id}`)).json()).status;

async function importWithSubtask(request) {
    const s = stamp();
    const source = `E2E465 import ${s}`;
    const title = `E2E465 imported ${s}`;
    const r = await request.post("/api/import/tasks/confirm", {
        data: { candidates: [{ title, type: "work", included: true }], source },
    });
    expect(r.ok()).toBe(true);
    const logs = await (await request.get("/api/settings/imports")).json();
    const batchId = logs.find((l) => l.source === source).batch_id;
    const parent = (await (await request.get("/api/tasks")).json()).find((t) => t.title === title);
    const sub = await (await request.post("/api/tasks", {
        data: { title: `E2E465 added later ${s}`, type: "work", parent_id: parent.id },
    })).json();
    return { source, batchId, parent, sub };
}

async function cleanup(request, { batchId, sub }) {
    await request.post(`/api/recycle-bin/undo/${batchId}`);
    await request.post(`/api/recycle-bin/purge/${batchId}`, { data: { confirmation: "DELETE" } });
    await request.delete(`/api/tasks/${sub.id}`);   // in case the purge didn't take it
}

test.describe("#465 import undo takes added subtasks", () => {
    test("Undo sends the subtask to the bin with its parent; Restore brings both back", async ({ page, request }) => {
        const fx = await importWithSubtask(request);
        try {
            await page.goto("/settings?nosw=1");
            await page.waitForLoadState("networkidle");
            page.once("dialog", (d) => d.accept());
            await page.locator(`button[data-batch-id="${fx.batchId}"]`).click();
            await expect.poll(() => statusOf(request, fx.parent.id)).toBe("deleted");
            expect(await statusOf(request, fx.sub.id)).toBe("deleted");

            // Not on the board, and not listed on its own in the bin.
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            await expect(page.locator(`.task-card[data-id="${fx.sub.id}"]`)).toHaveCount(0);
            await page.goto("/recycle-bin?nosw=1");
            await page.waitForLoadState("networkidle");
            await expect(page.locator("#recycleDeletedList")).not.toContainText(fx.sub.title);

            // Restore the batch from the bin.
            const row = page.locator("#recycleList li.recycle-item").filter({
                has: page.locator(".recycle-item-title", { hasText: fx.source }),
            });
            await row.locator("button", { hasText: "Restore" }).click();
            await page.locator("#recycleModalConfirm").click();
            await expect.poll(() => statusOf(request, fx.parent.id)).toBe("active");
            expect(await statusOf(request, fx.sub.id)).toBe("active");
        } finally {
            await cleanup(request, fx);
        }
    });
});
