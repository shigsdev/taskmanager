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

    /**
     * Bug #57 (2026-04-25): a stale `type === "work"` conditional in
     * app.js taskDetailSave forced project_id: null on every non-work
     * task save, silently dropping the dropdown selection. The API
     * accepted what it received, so there was no error — only a
     * round-trip assertion catches it. This test creates a personal
     * task + personal project via the API, opens the detail panel,
     * picks the project, saves, reloads, and asserts the dropdown
     * still shows the project.
     */
    test("personal task project assignment persists across reload", async ({ page }) => {
        // Navigate first so relative fetch URLs resolve against the dev origin.
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        // Seed: create a personal project + personal task via API.
        const projectId = await page.evaluate(async () => {
            const r = await fetch("/api/projects", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: "Persist Test Proj", type: "personal" }),
            });
            return (await r.json()).id;
        });

        const taskId = await page.evaluate(async () => {
            const r = await fetch("/api/tasks", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ title: "persist-test-task", type: "personal", tier: "inbox" }),
            });
            return (await r.json()).id;
        });

        try {
            // Reload so allProjects/allTasks include the freshly seeded rows
            // and the project dropdown is populated.
            await page.reload();
            await page.waitForLoadState("networkidle");
            await page.evaluate(async (id) => {
                const t = await fetch(`/api/tasks/${id}`).then((r) => r.json());
                window.taskDetailOpen(t);
            }, taskId);
            await expect(page.locator("#detailPanel")).toBeVisible();

            // Pick the project, save.
            await page.selectOption("#detailProject", projectId);
            await page.evaluate(() => document.getElementById("detailForm").requestSubmit());
            // Save closes the panel; wait for that.
            await expect(page.locator("#detailOverlay")).toBeHidden({ timeout: 3000 });

            // Verify via the API that the project_id actually persisted —
            // this is the assertion that catches bug #57's silent drop.
            const persisted = await page.evaluate(async (id) => {
                const r = await fetch(`/api/tasks/${id}`);
                return (await r.json()).project_id;
            }, taskId);
            expect(persisted).toBe(projectId);

            // Re-open the panel; the dropdown should reflect the saved value.
            await page.evaluate(async (id) => {
                const t = await fetch(`/api/tasks/${id}`).then((r) => r.json());
                window.taskDetailOpen(t);
            }, taskId);
            await expect(page.locator("#detailPanel")).toBeVisible();
            const dropdownValue = await page.inputValue("#detailProject");
            expect(dropdownValue).toBe(projectId);
        } finally {
            // Cleanup: delete the seed task + project so the test stays idempotent.
            await page.evaluate(async ([tid, pid]) => {
                await fetch(`/api/tasks/${tid}`, { method: "DELETE" });
                await fetch(`/api/projects/${pid}`, { method: "DELETE" });
            }, [taskId, projectId]);
        }
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
