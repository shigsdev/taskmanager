/**
 * #463: a deleted task opened in the task panel (a completed subtask's link
 * to its deleted parent) offered ✓ Complete, Copy, Cancel and Delete — all
 * either refused (#474) or wrong for a binned task — and no way back. It now
 * shows "This task is in the Recycle Bin." and a Restore button instead.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const uniq = () => Math.random().toString(36).slice(2, 8);
const FOUR = ["#detailComplete", "#detailDuplicate", "#detailCancel", "#detailDelete"];

// A deleted parent whose completed subtask still sits on /completed.
async function deletedParent(request) {
    const tag = uniq();
    const parent = await (await request.post("/api/tasks", {
        data: { title: `E2E463 parent ${tag}`, type: "work", tier: "backlog" },
    })).json();
    const child = await (await request.post("/api/tasks", {
        data: { title: `E2E463 child ${tag}`, type: "work", parent_id: parent.id },
    })).json();
    await request.post(`/api/tasks/${child.id}/complete`);
    await request.delete(`/api/tasks/${parent.id}`);
    return { parent, child };
}

async function openParentFromChild(page, child) {
    await page.goto("/completed?nosw=1");
    await page.waitForLoadState("networkidle");
    await page.locator(`.task-card[data-id="${child.id}"]`).click({ position: { x: 4, y: 4 } });
    await expect(page.locator("#detailOverlay")).toBeVisible();
    const link = page.locator("#parentLinkBody .parent-link");
    await expect(page.locator("#parentLinkBody .parent-link-status")).toHaveText("deleted");
    await link.click();
}

async function cleanup(request, ids) {
    for (const id of ids) await request.delete(`/api/tasks/${id}`);
}

test.describe("#463 a deleted task in the panel", () => {
    test("shows Restore instead of Complete / Copy / Cancel / Delete, and Restore brings it back", async ({ page, request }) => {
        const { parent, child } = await deletedParent(request);
        try {
            await openParentFromChild(page, child);
            await expect(page.locator("#detailTitle")).toHaveValue(parent.title);
            await expect(page.locator("#detailDeletedNote")).toBeVisible();
            await expect(page.locator("#detailDeletedNote")).toHaveText("This task is in the Recycle Bin.");
            for (const sel of FOUR) await expect(page.locator(sel), sel).toBeHidden();
            const restore = page.locator("#detailRestore");
            await expect(restore).toBeVisible();
            await expect(page.locator("#detailForm button[type=submit]")).toBeVisible();

            await restore.click();
            await expect(page.locator("#detailOverlay")).toBeHidden();
            await expect.poll(async () =>
                (await (await request.get(`/api/tasks/${parent.id}`)).json()).status).toBe("active");
        } finally {
            await cleanup(request, [child.id, parent.id]);
        }
    });

    test("a refused Restore says so and leaves it in the bin", async ({ page, request }) => {
        const { parent, child } = await deletedParent(request);
        const dialogs = [];
        page.on("dialog", (d) => { dialogs.push(d.message()); d.dismiss(); });
        try {
            await openParentFromChild(page, child);
            await page.route(`**/api/tasks/${parent.id}`, async (route) => {
                if (route.request().method() === "PATCH") {
                    await route.fulfill({ status: 500, json: { error: "stub refusal" } });
                } else {
                    await route.fallback();
                }
            });
            await page.locator("#detailRestore").click();
            await expect.poll(() => dialogs.length).toBe(1);
            expect(dialogs[0]).toBe("Restoring the task didn't save: stub refusal. The page now shows what's saved.");
            await expect(page.locator("#detailOverlay")).toBeVisible();
            await expect(page.locator("#detailRestore")).toBeVisible();
            const saved = await (await request.get(`/api/tasks/${parent.id}`)).json();
            expect(saved.status).toBe("deleted");
        } finally {
            await page.unroute(`**/api/tasks/${parent.id}`);
            await cleanup(request, [child.id, parent.id]);
        }
    });

    test("an active task's panel is unchanged (the quiet case)", async ({ page, request }) => {
        const task = await (await request.post("/api/tasks", {
            data: { title: `E2E463 active ${uniq()}`, type: "work", tier: "backlog" },
        })).json();
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.locator(`.task-card[data-id="${task.id}"] .task-title`).click({ position: { x: 4, y: 4 } });
            await expect(page.locator("#detailOverlay")).toBeVisible();
            for (const sel of FOUR) await expect(page.locator(sel), sel).toBeVisible();
            await expect(page.locator("#detailRestore")).toBeHidden();
            await expect(page.locator("#detailDeletedNote")).toBeHidden();
        } finally {
            await cleanup(request, [task.id]);
        }
    });

    test("after a deleted task, the next one opened has its buttons back", async ({ page, request }) => {
        const { parent, child } = await deletedParent(request);
        try {
            await openParentFromChild(page, child);
            await expect(page.locator("#detailRestore")).toBeVisible();
            await page.keyboard.press("Escape");
            await expect(page.locator("#detailOverlay")).toBeHidden();
            await page.locator(`.task-card[data-id="${child.id}"]`).click({ position: { x: 4, y: 4 } });
            await expect(page.locator("#detailOverlay")).toBeVisible();
            await expect(page.locator("#detailRestore")).toBeHidden();
            await expect(page.locator("#detailDeletedNote")).toBeHidden();
            await expect(page.locator("#detailDelete")).toBeVisible();
        } finally {
            await cleanup(request, [child.id, parent.id]);
        }
    });
});
