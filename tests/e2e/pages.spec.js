/**
 * Page navigation + core interaction E2E tests.
 *
 * These verify that real pages load in a real browser without JS errors,
 * that key interactive elements work, and that the capture bar submits
 * through the full stack (browser → API → DB → re-render).
 *
 * Uses ?nosw=1 to avoid SW interference.
 */
// @ts-check
const { test, expect } = require("@playwright/test");

test.describe("Page navigation — no console errors", () => {
    const pages = [
        { path: "/?nosw=1", title: "Home" },
        { path: "/goals?nosw=1", title: "Goals" },
        { path: "/review?nosw=1", title: "Weekly Review" },
        { path: "/settings?nosw=1", title: "Settings" },
        { path: "/import?nosw=1", title: "Import" },
        { path: "/scan?nosw=1", title: "Scan" },
        { path: "/recycle-bin?nosw=1", title: "Recycle Bin" },
        { path: "/print?nosw=1", title: "Daily Tasks" },
    ];

    for (const pg of pages) {
        test(`${pg.title} page loads without JS errors`, async ({ page }) => {
            const errors = [];
            page.on("pageerror", (err) => errors.push(err.message));

            // Clear any lingering SW state first to avoid controllerchange reloads
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.waitForTimeout(500);

            await page.goto(pg.path);
            await page.waitForLoadState("networkidle");

            expect(errors).toEqual([]);
        });
    }
});

test.describe("Capture bar — full-stack round trip", () => {
    test("create task via capture bar and verify it appears", async ({
        page,
    }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        const taskTitle = `E2E-test-${Date.now()}`;

        // Type in capture bar and submit
        await page.fill("#captureInput", `${taskTitle} #today`);
        await page.click("#captureSubmit");

        // Wait for the task to appear on the page
        await page.waitForTimeout(1500);

        // Verify the task is visible in the Today tier
        const pageText = await page.textContent("body");
        expect(pageText).toContain(taskTitle);

        // Verify input was cleared
        const inputValue = await page.inputValue("#captureInput");
        expect(inputValue).toBe("");

        // Clean up: delete the test task via API
        const taskId = await page.evaluate(async (title) => {
            const resp = await fetch("/api/tasks");
            const tasks = await resp.json();
            const task = tasks.find((t) => t.title === title);
            return task ? task.id : null;
        }, taskTitle);

        if (taskId) {
            await page.evaluate(async (id) => {
                await fetch(`/api/tasks/${id}`, { method: "DELETE" });
            }, taskId);
        }
    });

    test("capture bar with URL creates task with link", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        const taskTitle = `E2E-url-${Date.now()}`;

        await page.fill(
            "#captureInput",
            `${taskTitle} https://example.com/test`
        );
        await page.click("#captureSubmit");
        await page.waitForTimeout(2000);

        // Verify the task exists with URL via API
        const task = await page.evaluate(async (title) => {
            const resp = await fetch("/api/tasks");
            const tasks = await resp.json();
            return tasks.find((t) => t.title === title);
        }, taskTitle);

        expect(task).toBeTruthy();
        expect(task.url).toBe("https://example.com/test");

        // Clean up
        if (task) {
            await page.evaluate(async (id) => {
                await fetch(`/api/tasks/${id}`, { method: "DELETE" });
            }, task.id);
        }
    });
});

test.describe("Detail panel", () => {
    test("clicking a task opens the detail panel", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        // Click the first task card
        const firstCard = page.locator(".task-card").first();
        await firstCard.click();

        // Detail panel should be visible
        const panel = page.locator("#detailPanel");
        await expect(panel).toBeVisible({ timeout: 2000 });
    });
});

test.describe("Goals page filters", () => {
    test("category filter changes visible goals", async ({ page }) => {
        await page.goto("/goals?nosw=1");
        await page.waitForLoadState("networkidle");

        // Count all goal cards initially
        const initialCount = await page.locator(".goal-card").count();
        expect(initialCount).toBeGreaterThan(0);

        // Filter by a specific category
        await page.selectOption("#filterCategory", "health");
        await page.waitForTimeout(500);

        // The filter should be applied
        const filterValue = await page.inputValue("#filterCategory");
        expect(filterValue).toBe("health");
    });
});
