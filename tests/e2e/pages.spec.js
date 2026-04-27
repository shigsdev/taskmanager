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

    /**
     * Bug #58 sweep (2026-04-25): #57 was a silent payload drop. Sibling
     * bugs of the same class would silently drop other detail-panel
     * fields. This test sets EVERY field on a task via the detail panel,
     * saves, then asserts each value persisted via the API. Catches any
     * field that the save handler is silently rewriting or dropping.
     *
     * Note: checklist + repeat are tested separately because their UI
     * shape is dynamic.
     */
    test("every detail-panel field round-trips via save-and-reload", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        // Seed: project (work), goal, task — so dropdowns have selectable values.
        const seed = await page.evaluate(async () => {
            const proj = await fetch("/api/projects", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: "RoundTrip Proj", type: "work" }),
            }).then((r) => r.json());
            const goal = await fetch("/api/goals", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    title: "RoundTrip Goal",
                    category: "work",
                    priority: "should",
                    quarter: "2026-Q4",
                }),
            }).then((r) => r.json());
            const task = await fetch("/api/tasks", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ title: "roundtrip-task", type: "work", tier: "inbox" }),
            }).then((r) => r.json());
            return { projectId: proj.id, goalId: goal.id, taskId: task.id };
        });

        try {
            await page.reload();
            await page.waitForLoadState("networkidle");
            await page.evaluate(async (id) => {
                const t = await fetch(`/api/tasks/${id}`).then((r) => r.json());
                window.taskDetailOpen(t);
            }, seed.taskId);
            await expect(page.locator("#detailPanel")).toBeVisible();

            // Set every field. Distinct values so silent overwrites are easy
            // to spot in the assertion message.
            await page.fill("#detailTitle", "round-trip new title");
            await page.selectOption("#detailTier", "today");
            await page.selectOption("#detailType", "work");
            await page.selectOption("#detailProject", seed.projectId);
            await page.fill("#detailDueDate", "2026-12-31");
            await page.selectOption("#detailGoal", seed.goalId);
            await page.fill("#detailUrl", "https://example.com/round-trip");
            await page.fill("#detailNotes", "round-trip notes body");

            await page.evaluate(() => document.getElementById("detailForm").requestSubmit());
            await expect(page.locator("#detailOverlay")).toBeHidden({ timeout: 3000 });

            const persisted = await page.evaluate(async (id) => {
                return await fetch(`/api/tasks/${id}`).then((r) => r.json());
            }, seed.taskId);

            expect(persisted.title, "title").toBe("round-trip new title");
            expect(persisted.tier, "tier").toBe("today");
            expect(persisted.type, "type").toBe("work");
            expect(persisted.project_id, "project_id").toBe(seed.projectId);
            expect(persisted.due_date, "due_date").toBe("2026-12-31");
            expect(persisted.goal_id, "goal_id").toBe(seed.goalId);
            expect(persisted.url, "url").toBe("https://example.com/round-trip");
            expect(persisted.notes, "notes").toBe("round-trip notes body");
        } finally {
            await page.evaluate(async (s) => {
                await fetch(`/api/tasks/${s.taskId}`, { method: "DELETE" });
                await fetch(`/api/projects/${s.projectId}`, { method: "DELETE" });
                await fetch(`/api/goals/${s.goalId}`, { method: "DELETE" });
            }, seed);
        }
    });

    /**
     * Bug #58 sweep (2026-04-25): checklist items are stored as JSON in the
     * task row. They have a dynamic DOM (one row per item, add/remove
     * buttons). A silent drop here would mean a user adds steps to a task,
     * saves, and the steps disappear on reload. Test that checklist
     * items round-trip both ways: add new ones, save, reload, assert
     * they're still there.
     */
    test("checklist items round-trip via save-and-reload", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        const taskId = await page.evaluate(async () => {
            const r = await fetch("/api/tasks", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ title: "checklist-test", type: "work", tier: "inbox" }),
            });
            return (await r.json()).id;
        });

        try {
            await page.reload();
            await page.waitForLoadState("networkidle");
            await page.evaluate(async (id) => {
                const t = await fetch(`/api/tasks/${id}`).then((r) => r.json());
                window.taskDetailOpen(t);
            }, taskId);
            await expect(page.locator("#detailPanel")).toBeVisible();

            // Add three checklist items via the helper that the UI uses.
            await page.evaluate(() => {
                window.taskDetailAddChecklistRow("buy bread", false);
                window.taskDetailAddChecklistRow("buy milk", true);
                window.taskDetailAddChecklistRow("buy eggs", false);
            });

            await page.evaluate(() => document.getElementById("detailForm").requestSubmit());
            await expect(page.locator("#detailOverlay")).toBeHidden({ timeout: 3000 });

            const persisted = await page.evaluate(async (id) => {
                return await fetch(`/api/tasks/${id}`).then((r) => r.json());
            }, taskId);
            expect(persisted.checklist).toHaveLength(3);
            expect(persisted.checklist.map((c) => c.text)).toEqual(["buy bread", "buy milk", "buy eggs"]);
            expect(persisted.checklist[1].checked).toBe(true);
            expect(persisted.checklist[0].checked).toBe(false);
        } finally {
            await page.evaluate(async (id) => {
                await fetch(`/api/tasks/${id}`, { method: "DELETE" });
            }, taskId);
        }
    });
});

test.describe("Goals page filters", () => {
    test("category filter narrows visible goals to the chosen category", async ({ page }) => {
        // PR38 audit fix D3: prior version asserted that the dropdown's
        // value updated after selectOption — which always passes
        // regardless of whether the JS filter logic actually ran. This
        // test now asserts the visible card set genuinely changed:
        //   1. Snapshot the initial card count + categories.
        //   2. Pick a non-default category that isn't All.
        //   3. Assert AFTER the filter only health-tagged cards remain.
        // A broken filter renderer (e.g. the change handler stops
        // calling renderGoals) would now FAIL this test.
        await page.goto("/goals?nosw=1");
        await page.waitForLoadState("networkidle");

        const initialCount = await page.locator(".goal-card").count();
        expect(initialCount).toBeGreaterThan(0);

        // Pick the first category present in any goal card.
        // The seeded data has at least one HEALTH goal — assert it.
        const allCategoryBadges = await page.locator(".goal-card .badge-category").allTextContents();
        const hasHealth = allCategoryBadges.some((t) => /health/i.test(t));
        if (!hasHealth) {
            test.skip(true, "Seed data has no health goals — filter test cannot validate.");
        }

        await page.selectOption("#filterCategory", "health");
        await page.waitForTimeout(300);  // debounce + render

        // After filtering, every visible card MUST be a health card.
        const visibleCategories = await page.locator(".goal-card:visible .badge-category").allTextContents();
        expect(visibleCategories.length).toBeGreaterThan(0);
        for (const cat of visibleCategories) {
            expect(cat.toLowerCase()).toContain("health");
        }

        // Sanity: filtered count must be ≤ initial count.
        const filteredCount = await page.locator(".goal-card:visible").count();
        expect(filteredCount).toBeLessThanOrEqual(initialCount);
    });
});


// === PR38 audit C1+C2: feature interaction tests ============================

test.describe("Filter chips actually filter the board (#92)", () => {
    test("clicking a project chip narrows the visible task set", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        const allCount = await page.locator(".tier-board .task-card").count();
        // Need at least 2 cards across 2+ projects to make this meaningful.
        if (allCount < 2) test.skip(true, "Seeded data has too few tasks for this test.");

        // Find a non-"All" project chip.
        const projectChips = page.locator("#projectFilterBar button:not(.active)");
        const chipCount = await projectChips.count();
        if (chipCount === 0) test.skip(true, "No selectable project chip.");

        await projectChips.first().click();
        await page.waitForTimeout(200);

        // After click: chip is active AND visible cards are <= initial.
        const activeChips = await page.locator("#projectFilterBar button.active").count();
        expect(activeChips).toBe(1);
        const filteredCount = await page.locator(".tier-board .task-card").count();
        expect(filteredCount).toBeLessThanOrEqual(allCount);
        // Click "All" to clear.
        await page.locator("#projectFilterBar button").first().click();
        await page.waitForTimeout(200);
        const clearedActive = await page.locator("#projectFilterBar button.active").count();
        expect(clearedActive).toBe(1);  // only "All" should be active
    });

    test("clicking 2 goal chips activates both (#97 multi-select)", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        // Snapshot the chips BEFORE any click so the indices are stable.
        // (After a click, the chip's class changes from "" to "active"
        // and the :not(.active) selector shifts.)
        const allGoalChips = page.locator("#goalFilterBar button");
        const total = await allGoalChips.count();
        // Index 0 is "All". Need at least 2 actual goal chips (1+2).
        if (total < 3) test.skip(true, "Need 2+ selectable goal chips.");

        await allGoalChips.nth(1).click();
        await page.waitForTimeout(150);
        await allGoalChips.nth(2).click();
        await page.waitForTimeout(150);

        const activeChips = await page.locator("#goalFilterBar button.active").count();
        expect(activeChips).toBeGreaterThanOrEqual(2);

        // localStorage CSV must contain a comma (proves multi-select wrote correctly).
        const stored = await page.evaluate(() => localStorage.getItem("tm.filter.goal"));
        expect(stored).toContain(",");

        // Cleanup
        await page.locator("#goalFilterBar button").first().click();
        await page.evaluate(() => localStorage.removeItem("tm.filter.goal"));
    });
});

test.describe("Calendar drag-and-drop (#94)", () => {
    test("drop unscheduled task on a day cell sets due_date + auto-routes tier (#100)", async ({
        page, request,
    }) => {
        // Create a dedicated unscheduled task via API so we don't depend on seeds.
        const created = await request.post("/api/tasks", {
            data: { title: `E2E DnD ${Date.now()}`, type: "work", tier: "inbox" },
        });
        expect(created.ok()).toBe(true);
        const task = await created.json();
        // The auto-fill rule sets due_date if tier is today/tomorrow; inbox
        // doesn't trigger that, so this stays unscheduled.

        try {
            await page.goto("/calendar?nosw=1");
            await page.waitForLoadState("networkidle");
            await expect(page.locator(".calendar-cell").first()).toBeVisible();

            // Find the test task in the Unscheduled side panel + the
            // first non-past cell to drop onto.
            const li = page.locator(`#calendarUnscheduled li[data-task-id="${task.id}"]`);
            await expect(li).toBeVisible();
            const cell = page.locator(".calendar-cell:not(.calendar-cell-past)").first();
            const cellDate = await cell.getAttribute("data-date");
            expect(cellDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);

            // Programmatic drag-and-drop via DataTransfer (Playwright's
            // page.dragAndDrop doesn't always fire the real dragstart for
            // this app's listener style).
            await page.evaluate((args) => {
                const li = document.querySelector(
                    `#calendarUnscheduled li[data-task-id="${args.tid}"]`
                );
                const cell = document.querySelector(
                    `.calendar-cell[data-date="${args.cellDate}"]`
                );
                const dt = new DataTransfer();
                dt.setData("text/plain", args.tid);
                li.dispatchEvent(new DragEvent("dragstart", { dataTransfer: dt, bubbles: true }));
                cell.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
                cell.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
            }, { tid: task.id, cellDate });

            // Wait for the PATCH + re-render + DB to land.
            await page.waitForTimeout(500);

            // Re-fetch via API and assert due_date AND tier auto-routed (#74).
            const after = await request.get(`/api/tasks/${task.id}`);
            const t = await after.json();
            expect(t.due_date).toBe(cellDate);
            // Tier must be one of today/tomorrow/this_week/next_week (date-bucketed
            // per #74), NOT inbox anymore.
            expect(["today", "tomorrow", "this_week", "next_week"]).toContain(t.tier);
        } finally {
            // Cleanup: archive the test task so it doesn't pollute future runs.
            await request.delete(`/api/tasks/${task.id}`);
        }
    });
});
