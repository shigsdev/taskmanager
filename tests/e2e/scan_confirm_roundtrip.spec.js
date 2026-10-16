/**
 * #490: a /scan review's fields reach the saved goal / project. Only the
 * upload (Vision + Claude) is stubbed; Add All goes to the real
 * /api/scan/confirm, and the created row is read back from the API — so a
 * renamed payload key fails here, not silently in use.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

async function scanAndAddAll(page, kind, candidates) {
    await page.route("**/api/scan/upload", (route) => route.fulfill({
        json: { ocr_text: "x", kind, candidates },
    }));
    await page.goto("/scan?nosw=1");
    await page.locator(`input[name=parseAs][value=${kind}]`).check();
    await page.setInputFiles("#scanFile", { name: "note.png", mimeType: "image/png", buffer: Buffer.from(PNG, "base64") });
    await page.locator("#scanSubmitBtn").click();
    await expect(page.locator("#scanReview")).toBeVisible({ timeout: 10000 });
    const confirmed = page.waitForResponse((r) => r.url().includes("/api/scan/confirm"));
    await page.locator("#scanConfirmAll").click();
    expect((await confirmed).status()).toBe(201);
}

test.describe("#490 /scan confirm round trip", () => {
    test("a scanned goal keeps its category, priority, quarter and actions", async ({ page, request }) => {
        const title = `E2E490 goal ${Date.now()}`;
        await scanAndAddAll(page, "goals", [{
            title, category: "health", priority: "must",
            target_quarter: "2026-Q4", actions: "Train three times a week", included: true,
        }]);
        const goals = await (await request.get("/api/goals?is_active=all")).json();
        const g = (Array.isArray(goals) ? goals : goals.goals).find((x) => x.title === title);
        expect(g).toMatchObject({
            category: "health", priority: "must",
            target_quarter: "2026-Q4", actions: "Train three times a week",
        });
    });

    test("a scanned project keeps its name, type and quarter", async ({ page, request }) => {
        const name = `E2E490 project ${Date.now()}`;
        await scanAndAddAll(page, "projects", [
            { title: name, type: "personal", target_quarter: "2027-Q1", included: true },
        ]);
        const projects = await (await request.get("/api/projects?is_active=all")).json();
        const p = (Array.isArray(projects) ? projects : projects.projects).find((x) => x.name === name);
        expect(p).toMatchObject({ type: "personal", target_quarter: "2027-Q1" });
    });

    test("a scanned task keeps its type (the quiet case)", async ({ page, request }) => {
        const title = `E2E490 task ${Date.now()}`;
        await scanAndAddAll(page, "tasks", [{ title, type: "personal", included: true }]);
        const tasks = await (await request.get("/api/tasks")).json();
        const t = (Array.isArray(tasks) ? tasks : tasks.tasks).find((x) => x.title === title);
        expect(t).toMatchObject({ type: "personal", tier: "inbox" });
    });
});
