/**
 * #466 (user decision 2026-10-16): moving a task into This Week or Backlog
 * without touching its date keeps the date only if it belongs there. A
 * due-today task moved to Backlog used to stay on today's calendar square
 * and come back overnight; a far-dated task promoted to This Week went back
 * to Backlog the next morning.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const uniq = () => Math.random().toString(36).slice(2, 8);
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const daysFromNow = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return iso(d); };
const cardIn = (page, tier, id) =>
    page.locator(`.task-list[data-tier="${tier}"] .task-card[data-id="${id}"]`);
const saved = async (request, id) => (await request.get(`/api/tasks/${id}`)).json();

// The board's own move: Move ▾ above 600px, the row under the title on a phone.
async function moveCard(page, card, label) {
    if (page.viewportSize().width > 600) {
        await card.locator(".task-move-btn").click();
        await page.locator(".task-move-menu button", { hasText: label }).click();
    } else {
        await card.locator(".task-quick-actions button", { hasText: label }).click();
    }
}

test.describe("#466 a section move keeps only a date that fits", () => {
    test("a due-today task moved to Backlog loses today's date", async ({ page, request }) => {
        const task = await (await request.post("/api/tasks", {
            data: { title: `E2E466 today ${uniq()}`, type: "work", tier: "today", due_date: daysFromNow(0) },
        })).json();
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            await moveCard(page, cardIn(page, "today", task.id), "Backlog");
            await expect(cardIn(page, "backlog", task.id)).toHaveCount(1);
            await expect(cardIn(page, "today", task.id)).toHaveCount(0);
            await expect.poll(async () => (await saved(request, task.id)).due_date).toBeNull();
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("a far-dated Backlog task promoted to This Week loses the far date", async ({ page, request }) => {
        const task = await (await request.post("/api/tasks", {
            data: { title: `E2E466 far ${uniq()}`, type: "work", tier: "backlog", due_date: daysFromNow(40) },
        })).json();
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            await moveCard(page, cardIn(page, "backlog", task.id), "This Week");
            await expect(cardIn(page, "this_week", task.id)).toHaveCount(1);
            await expect.poll(async () => (await saved(request, task.id)).due_date).toBeNull();
            expect((await saved(request, task.id)).tier).toBe("this_week");
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("a far-dated task moved to Backlog keeps its date (the quiet case)", async ({ page, request }) => {
        const far = daysFromNow(40);
        const task = await (await request.post("/api/tasks", {
            data: { title: `E2E466 keep ${uniq()}`, type: "work", tier: "freezer", due_date: far },
        })).json();
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            await moveCard(page, cardIn(page, "freezer", task.id), "Backlog");
            await expect(cardIn(page, "backlog", task.id)).toHaveCount(1);
            expect((await saved(request, task.id)).due_date).toBe(far);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });
});
