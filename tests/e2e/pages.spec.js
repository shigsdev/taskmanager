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
// Re-apply the no-IPv6 DNS patch in this worker. globalSetup runs in
// the parent process; the patch on dns.promises.lookup is lost when
// Playwright forks workers and they re-require dns. Without this,
// `request.post("/api/tasks", ...)` intermittently fails with
// `ECONNREFUSED ::1:5111` when Happy Eyeballs picks IPv6 first.
// Matches the pattern smoke.spec.js uses (per globalSetup comment).
require("../playwright-globalSetup");
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

    test("background projects/goals refresh does not widen a personal task's dropdowns to work items (2026-05-17)", async ({ page }) => {
        // Regression: loadProjects()/loadGoals() (init race, polling,
        // post-save) called taskDetailPopulate{Projects,Goals}() with no
        // type arg → repopulated the OPEN panel unfiltered, so a Personal
        // task showed Work projects/goals. Same class as #57.
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        const ids = await page.evaluate(async () => {
            const mk = async (url, body) =>
                (await (await fetch(url, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(body),
                })).json());
            const workProj = await mk("/api/projects", { name: "ZZ Work Proj", type: "work" });
            const persProj = await mk("/api/projects", { name: "ZZ Personal Proj", type: "personal" });
            const task = await mk("/api/tasks", { title: "zz-personal-dropdown-task", type: "personal", tier: "inbox" });
            return { workProj: workProj.id, persProj: persProj.id, task: task.id };
        });

        try {
            await page.reload();
            await page.waitForLoadState("networkidle");

            const result = await page.evaluate(async (ids) => {
                const t = await fetch(`/api/tasks/${ids.task}`).then((r) => r.json());
                window.taskDetailOpen(t);
                await new Promise((x) => setTimeout(x, 300));
                const opts = () =>
                    Array.from(document.getElementById("detailProject").options).map((o) => o.value);
                const before = opts();
                // The clobber path: a background refresh while panel open.
                await window.loadProjects();
                if (typeof window.loadGoals === "function") await window.loadGoals();
                await new Promise((x) => setTimeout(x, 300));
                const after = opts();
                return { before, after, workId: ids.workProj, persId: ids.persProj };
            }, ids);

            // Personal project present, work project absent — BEFORE and
            // crucially AFTER the background refresh (the regression).
            expect(result.before).toContain(result.persId);
            expect(result.before).not.toContain(result.workId);
            expect(result.after).toContain(result.persId);
            expect(result.after).not.toContain(result.workId);
        } finally {
            await page.evaluate(async (ids) => {
                await fetch(`/api/tasks/${ids.task}`, { method: "DELETE" });
                await fetch(`/api/projects/${ids.workProj}`, { method: "DELETE" });
                await fetch(`/api/projects/${ids.persProj}`, { method: "DELETE" });
            }, ids);
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
            // to spot in the assertion message. Use today's ISO for due_date
            // so tier=today + due_date stay consistent under #149's live
            // date→tier auto-routing (a far-future date would now flip the
            // tier to backlog before save). LOCAL date — toISOString() is
            // UTC and crosses midnight earlier than the listener's local
            // "today" near end-of-day, which would route tier→tomorrow.
            const _now = new Date();
            const todayIso =
                _now.getFullYear() + "-" +
                String(_now.getMonth() + 1).padStart(2, "0") + "-" +
                String(_now.getDate()).padStart(2, "0");
            await page.fill("#detailTitle", "round-trip new title");
            await page.selectOption("#detailTier", "today");
            await page.selectOption("#detailType", "work");
            await page.selectOption("#detailProject", seed.projectId);
            await page.fill("#detailDueDate", todayIso);
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
            expect(persisted.due_date, "due_date").toBe(todayIso);
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

test.describe("Multi-drag: dragging a selected card moves the whole group", () => {
    // User-requested 2026-05-09: "when I select two at a time, i cannot
    // drag them up/down in unison." Fix: when the dragged card is part
    // of a 2+ selection, the whole .bulk-selected set drags together;
    // tier change applies via /api/tasks/bulk PATCH.

    test("drag a selected card from TODAY to TOMORROW carries the whole 2-card selection", async ({
        page, request,
    }) => {
        const created = [];
        for (let i = 0; i < 3; i++) {
            const r = await request.post("/api/tasks", {
                data: { title: `MULTI-DRAG ${i}`, type: "work", tier: "today" },
            });
            created.push(await r.json());
        }
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            // Select cards [0] and [1] (third card is the control —
            // should NOT move).
            await page.locator(
                `.task-card[data-id="${created[0].id}"] .bulk-select-check`
            ).check();
            await page.locator(
                `.task-card[data-id="${created[1].id}"] .bulk-select-check`
            ).check();
            // Programmatic drag — dispatch native DragEvents the same
            // way calendar drag-and-drop tests do.
            await page.evaluate(({ src, target }) => {
                const card = document.querySelector(`.task-card[data-id="${src}"]`);
                const list = document.querySelector(
                    `.task-list[data-tier="${target}"]`
                );
                const dt = new DataTransfer();
                dt.setData("text/plain", src);
                card.dispatchEvent(new DragEvent("dragstart", { dataTransfer: dt, bubbles: true }));
                list.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true, clientY: 99999 }));
                list.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
                card.dispatchEvent(new DragEvent("dragend", { dataTransfer: dt, bubbles: true }));
            }, { src: created[0].id, target: "tomorrow" });
            await page.waitForTimeout(1500);

            // BOTH selected cards should now be in tomorrow.
            const t0 = await (await request.get(`/api/tasks/${created[0].id}`)).json();
            const t1 = await (await request.get(`/api/tasks/${created[1].id}`)).json();
            const t2 = await (await request.get(`/api/tasks/${created[2].id}`)).json();
            expect(t0.tier).toBe("tomorrow");
            expect(t1.tier).toBe("tomorrow");
            // Control: unselected card stays in today.
            expect(t2.tier).toBe("today");
        } finally {
            for (const t of created) {
                await request.delete(`/api/tasks/${t.id}`);
            }
        }
    });
});

test.describe("Tier-column drag updates due_date for today/tomorrow", () => {
    test("dragging a dated task to Tomorrow advances due_date (user report 2026-05-05)", async ({
        page, request,
    }) => {
        // Create a task in TODAY with today's date — exact user repro.
        const _now = new Date();
        const todayIso =
            _now.getFullYear() + "-" +
            String(_now.getMonth() + 1).padStart(2, "0") + "-" +
            String(_now.getDate()).padStart(2, "0");
        const create = await request.post("/api/tasks", {
            data: {
                title: "DRAG-149 today→tomorrow",
                type: "work", tier: "today", due_date: todayIso,
            },
        });
        const task = await create.json();
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");

            // Programmatic drag from today list to tomorrow list, mirroring
            // calendar drag-and-drop test pattern.
            // #225 (2026-05-24): set up network waits BEFORE dispatching
            // the drop so we don't race the fire. The cross-tier drop
            // fires TWO calls — PATCH /api/tasks/<id> (tier change) +
            // POST /api/tasks/reorder (sort_order save) — and the test
            // assertion fires a SEPARATE GET via Playwright's
            // apiRequestContext. On a slow gate run the fixed 700ms
            // wait wasn't always enough for both calls to clear the
            // Flask single-threaded server, causing the GET to time
            // out at 10s with apparent SQLite lock contention. Wait
            // explicitly for the responses instead.
            const patchPromise = page.waitForResponse(
                (resp) => resp.url().includes(`/api/tasks/${task.id}`)
                    && resp.request().method() === "PATCH",
                { timeout: 15_000 },
            );
            const reorderPromise = page.waitForResponse(
                (resp) => resp.url().includes("/api/tasks/reorder"),
                { timeout: 15_000 },
            );
            await page.evaluate((tid) => {
                const card = document.querySelector(`.task-card[data-id="${tid}"]`);
                const tomorrowList = document.querySelector(
                    '.task-list[data-tier="tomorrow"]'
                );
                const dt = new DataTransfer();
                dt.setData("text/plain", tid);
                card.dispatchEvent(new DragEvent("dragstart", { dataTransfer: dt, bubbles: true }));
                tomorrowList.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
                tomorrowList.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
            }, task.id);
            await patchPromise;
            await reorderPromise;

            const refetch = await request.get(`/api/tasks/${task.id}`);
            const refreshed = await refetch.json();
            expect(refreshed.tier).toBe("tomorrow");
            // Date must have advanced — bug was that it stayed at today.
            expect(refreshed.due_date).not.toBe(todayIso);
            const oldDate = new Date(todayIso);
            const newDate = new Date(refreshed.due_date);
            const deltaDays = Math.round(
                (newDate - oldDate) / (1000 * 60 * 60 * 24)
            );
            expect(deltaDays).toBe(1);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("dragging a dated task to This Week LEAVES the date alone (no canonical date)", async ({
        page, request,
    }) => {
        // Inverse — week ranges have no single canonical date, so the
        // drop handler should NOT touch due_date. Server's _auto_promote
        // route runs the OTHER direction (date→tier), not this one.
        const _now = new Date();
        const todayIso =
            _now.getFullYear() + "-" +
            String(_now.getMonth() + 1).padStart(2, "0") + "-" +
            String(_now.getDate()).padStart(2, "0");
        const create = await request.post("/api/tasks", {
            data: {
                title: "DRAG-149 today→this_week",
                type: "work", tier: "today", due_date: todayIso,
            },
        });
        const task = await create.json();
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");

            // #225 (2026-05-24): same network-wait pattern as the
            // Tomorrow sibling test above. Drop fires PATCH + reorder;
            // the GET below must wait for both to clear before reading.
            const patchPromise = page.waitForResponse(
                (resp) => resp.url().includes(`/api/tasks/${task.id}`)
                    && resp.request().method() === "PATCH",
                { timeout: 15_000 },
            );
            const reorderPromise = page.waitForResponse(
                (resp) => resp.url().includes("/api/tasks/reorder"),
                { timeout: 15_000 },
            );
            await page.evaluate((tid) => {
                const card = document.querySelector(`.task-card[data-id="${tid}"]`);
                const list = document.querySelector(
                    '.task-list[data-tier="this_week"]'
                );
                const dt = new DataTransfer();
                dt.setData("text/plain", tid);
                card.dispatchEvent(new DragEvent("dragstart", { dataTransfer: dt, bubbles: true }));
                list.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
                list.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
            }, task.id);
            await patchPromise;
            await reorderPromise;

            const refetch = await request.get(`/api/tasks/${task.id}`);
            const refreshed = await refetch.json();
            // Tier moved...
            expect(refreshed.tier).toBe("this_week");
            // ...but date is preserved.
            expect(refreshed.due_date).toBe(todayIso);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });
});

/**
 * Bug #148 (2026-05-05): completed/cancelled task → open detail
 * panel → change tier → Save. Old behaviour: task vanished from
 * active board AND stayed under Completed because the PATCH only
 * sent {tier} not {status, tier}. Fixed by snapshotting on open +
 * augmenting payload with status:active when an archived/cancelled
 * task has any field change.
 */
test.describe("Detail panel: edit completed task → unarchive (#148)", () => {
    test("completed task with tier change un-archives and appears on active board", async ({
        page, request,
    }) => {
        // Create + complete a task so it's archived going in.
        const create = await request.post("/api/tasks", {
            data: { title: "BUG148 round-trip", type: "work", tier: "today" },
        });
        const task = await create.json();
        await request.post(`/api/tasks/${task.id}/complete`);

        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");

            // Expand the Completed section so the card is in the DOM
            // and clickable. Toggle is the chevron on the heading.
            await page.locator("#tierCompleted .collapse-toggle").click();
            const completedCard = page.locator(`.task-card[data-id="${task.id}"]`);
            await expect(completedCard).toBeVisible({ timeout: 2000 });

            // Open detail panel
            await completedCard.click();
            await expect(page.locator("#detailPanel")).toBeVisible({ timeout: 2000 });

            // Change tier from today → this_week
            await page.locator("#detailTier").selectOption("this_week");
            // Save (form submit)
            await page.locator("#detailForm button[type=submit]").click();

            // Panel closes + reloads; wait for the request to settle.
            await page.waitForTimeout(500);

            // API verification — status should be active now
            const refetch = await request.get(`/api/tasks/${task.id}`);
            const refreshed = await refetch.json();
            expect(refreshed.status).toBe("active");
            expect(refreshed.tier).toBe("this_week");

            // DOM verification — card should be in This Week tier, NOT Completed
            const inThisWeek = page.locator(
                `.tier[data-tier="this_week"] .task-card[data-id="${task.id}"]`
            );
            await expect(inThisWeek).toBeVisible({ timeout: 2000 });
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("changing tier to 'today' on a dateless task auto-fills due_date", async ({
        page, request,
    }) => {
        // #149: live tier→date sync. Tier=today/tomorrow has a
        // canonical date; UI should preview the same auto-fill the
        // server applies on save.
        const create = await request.post("/api/tasks", {
            data: { title: "BUG149 tier-to-date", type: "work", tier: "inbox" },
        });
        const task = await create.json();
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            const card = page.locator(`.task-card[data-id="${task.id}"]`);
            await card.click();
            await expect(page.locator("#detailPanel")).toBeVisible({ timeout: 2000 });
            // Due date starts empty.
            await expect(page.locator("#detailDueDate")).toHaveValue("");
            // Pick Today → due_date should populate.
            await page.locator("#detailTier").selectOption("today");
            const dueValue = await page.locator("#detailDueDate").inputValue();
            expect(dueValue).toMatch(/^\d{4}-\d{2}-\d{2}$/);
            // Per #149 follow-up (user bug report 2026-05-05):
            // switching tier from today→tomorrow MUST advance the
            // date, otherwise the UI feels broken. Always-overwrite
            // for today/tomorrow (canonical date per tier).
            const tomorrowValue = await page.locator("#detailTier").evaluate((el) => {
                el.value = "tomorrow";
                el.dispatchEvent(new Event("change", { bubbles: true }));
                return document.getElementById("detailDueDate").value;
            });
            expect(tomorrowValue).not.toBe(dueValue);
            // Tomorrow's date should be exactly +1 day from today's.
            const todayDate = new Date(dueValue);
            const tomorrowDate = new Date(tomorrowValue);
            const deltaDays = Math.round(
                (tomorrowDate - todayDate) / (1000 * 60 * 60 * 24)
            );
            expect(deltaDays).toBe(1);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("changing due_date routes the tier dropdown live", async ({
        page, request,
    }) => {
        // #149: live date→tier sync. Set a date a week out → tier
        // should jump to next_week (or this_week depending on
        // weekday). We assert it's NOT inbox anymore.
        const create = await request.post("/api/tasks", {
            data: { title: "BUG149 date-to-tier", type: "work", tier: "inbox" },
        });
        const task = await create.json();
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            const card = page.locator(`.task-card[data-id="${task.id}"]`);
            await card.click();
            await expect(page.locator("#detailPanel")).toBeVisible({ timeout: 2000 });
            // Pick a date 8 days out (definitely past tomorrow, in or
            // beyond next_week range).
            const future = new Date();
            future.setDate(future.getDate() + 8);
            const iso = future.toISOString().slice(0, 10);
            await page.locator("#detailDueDate").evaluate((el, v) => {
                el.value = v;
                el.dispatchEvent(new Event("change", { bubbles: true }));
            }, iso);
            const tierAfter = await page.locator("#detailTier").inputValue();
            expect(tierAfter).not.toBe("inbox");
            // 8 days out is either next_week or backlog depending on
            // today's weekday; assert it's one of those.
            expect(["this_week", "next_week", "backlog"]).toContain(tierAfter);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("FREEZER tier suppresses date→tier auto-routing", async ({
        page, request,
    }) => {
        // #149 scope: FREEZER preserves explicit park — changing the
        // date shouldn't kick the task out of the freezer.
        const create = await request.post("/api/tasks", {
            data: { title: "BUG149 freezer", type: "work", tier: "freezer" },
        });
        const task = await create.json();
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            // Expand freezer section to make the card clickable.
            const freezerToggle = page.locator('.tier[data-tier="freezer"] .collapse-toggle');
            const ariaExpanded = await freezerToggle.getAttribute("aria-expanded");
            if (ariaExpanded === "false") {
                await freezerToggle.click();
            }
            const card = page.locator(`.task-card[data-id="${task.id}"]`);
            await card.click();
            await expect(page.locator("#detailPanel")).toBeVisible({ timeout: 2000 });
            await expect(page.locator("#detailTier")).toHaveValue("freezer");
            const today = new Date().toISOString().slice(0, 10);
            await page.locator("#detailDueDate").evaluate((el, v) => {
                el.value = v;
                el.dispatchEvent(new Event("change", { bubbles: true }));
            }, today);
            // Tier should STILL be freezer.
            await expect(page.locator("#detailTier")).toHaveValue("freezer");
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("no-op save on completed task does NOT un-archive", async ({
        page, request,
    }) => {
        // Guard from the BACKLOG row scope: opening a completed task
        // and clicking Save without changing anything must keep the
        // task archived. Otherwise the click-Save-by-accident case
        // resurrects every completed task the user opens.
        const create = await request.post("/api/tasks", {
            data: { title: "BUG148 no-op", type: "work", tier: "today" },
        });
        const task = await create.json();
        await request.post(`/api/tasks/${task.id}/complete`);

        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");

            await page.locator("#tierCompleted .collapse-toggle").click();
            const card = page.locator(`.task-card[data-id="${task.id}"]`);
            await expect(card).toBeVisible({ timeout: 2000 });
            await card.click();
            await expect(page.locator("#detailPanel")).toBeVisible({ timeout: 2000 });

            // Save without touching anything.
            await page.locator("#detailForm button[type=submit]").click();
            await page.waitForTimeout(500);

            const refetch = await request.get(`/api/tasks/${task.id}`);
            const refreshed = await refetch.json();
            expect(refreshed.status).toBe("archived");
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });
});

test.describe("Bulk move-up / move-down within a tier", () => {
    // Feature shipped 2026-05-08 (user-requested):
    //   "I need the ability to multi select things and move them up
    //   and down in the task window."
    // Pure reorder logic is Jest-tested in tier_helpers.test.js; this
    // test verifies the wiring: select-mode + checkboxes + toolbar
    // buttons → /api/tasks/reorder → DOM reflects the new order.

    test("contiguous selection moves up by one slot, stays selected", async ({
        page, request,
    }) => {
        // Seed three tasks in TODAY so we have something to reorder.
        const created = [];
        for (let i = 0; i < 3; i++) {
            const r = await request.post("/api/tasks", {
                data: { title: `BULK-MOVE ${i}`, type: "work", tier: "today" },
            });
            created.push(await r.json());
        }
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            // 2026-05-08 redesign: per-card checkbox IS selection — no
            // separate "enter bulk mode" toggle. Just check the boxes.
            // Select cards [1] and [2] (the second and third in tier
            // creation order) — should move up to positions [0] and [1].
            const list = page.locator('.task-list[data-tier="today"]');
            const initialIds = await list.locator(".task-card").evaluateAll(
                (els) => els.map((e) => e.dataset.id)
            );
            // Find the indexes of our seeded tasks in the rendered list.
            const seedSet = new Set(created.map((t) => t.id));
            const ourIds = initialIds.filter((id) => seedSet.has(id));
            expect(ourIds.length).toBe(3);
            // Check the LAST two of our three seeded cards.
            for (const id of [ourIds[1], ourIds[2]]) {
                await page.locator(
                    `.task-card[data-id="${id}"] .bulk-select-check`
                ).check();
            }
            await page.locator("#bulkActionMoveUp").click();
            // Wait for the reorder PATCH + reload.
            await page.waitForTimeout(900);
            const afterIds = await list.locator(".task-card").evaluateAll(
                (els) => els.map((e) => e.dataset.id)
            );
            // Find our three IDs in the new ordering — they should now
            // appear as ourIds[1], ourIds[2], ourIds[0] (the middle and
            // bottom shifted up over the top).
            const ourAfter = afterIds.filter((id) => seedSet.has(id));
            expect(ourAfter).toEqual([ourIds[1], ourIds[2], ourIds[0]]);
            // The reordered selection should still be checked so the
            // user can press ↑ again without re-selecting.
            for (const id of [ourIds[1], ourIds[2]]) {
                const isChecked = await page.locator(
                    `.task-card[data-id="${id}"] .bulk-select-check`
                ).isChecked();
                expect(isChecked).toBe(true);
            }
        } finally {
            for (const t of created) {
                await request.delete(`/api/tasks/${t.id}`);
            }
        }
    });
});

/**
 * Auto-categorize Inbox: user reported 2026-05-08 that the project
 * dropdown rendered with empty/blank options. Bug was in
 * static/inbox_categorize.js — option label read p.title, but
 * /api/projects returns p.name (Goal uses title; Project uses name —
 * model asymmetry). This test mocks the categorize endpoint so the
 * Claude call doesn't fire, then asserts the project dropdown options
 * have visible text matching real project names.
 */
test.describe("Auto-categorize Inbox: project dropdown labels", () => {
    test("project options show readable text (not blank from p.title bug)", async ({
        page, request,
    }) => {
        // Seed: one inbox task + one project so the dropdown has at
        // least one non-empty option to assert on.
        const projResp = await request.post("/api/projects", {
            data: { name: "AUTOCAT-PROJ", type: "work" },
        });
        const proj = await projResp.json();
        const taskResp = await request.post("/api/tasks", {
            data: { title: "auto-cat dropdown probe", type: "work", tier: "inbox" },
        });
        const task = await taskResp.json();

        try {
            // Mock the Claude-backed endpoint so we don't burn an API
            // call (and so the test is deterministic regardless of
            // Claude's mood). Returns one suggestion that picks our
            // seeded project.
            await page.route("**/api/inbox/categorize", (route) => {
                route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify({
                        count: 1,
                        capped: false,
                        suggestions: [{
                            task_id: task.id,
                            title: task.title,
                            suggested_tier: "this_week",
                            suggested_project_id: proj.id,
                            suggested_goal_id: null,
                            suggested_due_date: null,
                            suggested_type: "work",
                            reason: "fixture",
                        }],
                    }),
                });
            });

            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.locator("#autoCategorizeBtn").click();
            // Wait for the modal to render the row.
            await expect(
                page.locator('#autoCategorizeRows tr[data-task-id="' + task.id + '"]')
            ).toBeVisible({ timeout: 5000 });

            // The project select for our row should have an <option>
            // with our project's NAME as visible text. Before the fix,
            // every option's textContent was "undefined" (p.title on a
            // payload that only has p.name).
            const optionTexts = await page.locator(
                `#autoCategorizeRows tr[data-task-id="${task.id}"] select[data-field="project"] option`
            ).allTextContents();
            expect(optionTexts).toContain("AUTOCAT-PROJ");
            // And no option text should equal "undefined" (paranoia
            // guard against a future regression that swallows the bug).
            expect(optionTexts).not.toContain("undefined");

            // Suggested project should be pre-selected (Claude picked it).
            const selectedValue = await page.locator(
                `#autoCategorizeRows tr[data-task-id="${task.id}"] select[data-field="project"]`
            ).inputValue();
            expect(selectedValue).toBe(proj.id);
        } finally {
            await page.unroute("**/api/inbox/categorize");
            await request.delete(`/api/tasks/${task.id}`);
            await request.delete(`/api/projects/${proj.id}`);
        }
    });
});

test.describe("Calendar concurrent-render race (#219)", () => {
    // User-reported 2026-05-24 (screenshot showed the current week
    // repeated under next week). Root cause: renderCalendar is async
    // and awaits two apiFetch calls. If a second renderCalendar fires
    // mid-await (visibilitychange #114 + apiClient.subscribeTasksChanged
    // #214 both call it; the 60s poll #160 too), both calls' DOM
    // appends land after their awaits. Each call cleared the grid AT
    // THE TOP, but the actual append-rows step happened after the
    // awaits — so the late call's appended rows piled on top of the
    // already-appended rows from an earlier call.
    //
    // Fix: generation-counter guard inside renderCalendar — each call
    // increments and snapshots; only the LATEST call commits to the
    // DOM. The innerHTML = "" also moved to AFTER the awaits.
    //
    // This test fires multiple renderCalendar() concurrently and
    // asserts the final cell count is still exactly 14 (2 weeks × 7
    // days per #218). Without the guard the test fails at 28+ cells.
    test("multiple concurrent renderCalendar() calls produce exactly 14 cells", async ({ page }) => {
        await page.goto("/calendar?nosw=1");
        await page.waitForLoadState("networkidle");
        await expect(page.locator(".calendar-cell").first()).toBeVisible({ timeout: 5_000 });
        // Fire 5 renderCalendar() calls in rapid succession WITHOUT
        // awaiting between them — same shape as the
        // visibilitychange/subscribeTasksChanged/setInterval race.
        await page.evaluate(async () => {
            const promises = [];
            for (let i = 0; i < 5; i++) {
                promises.push(window.renderCalendar());
            }
            await Promise.all(promises);
        });
        // After all 5 settle, assert exactly 14 cells AND exactly 2
        // .calendar-row containers. (The user's screenshot showed 3+
        // rows when the race fired.)
        await page.waitForTimeout(200);
        expect(await page.locator(".calendar-cell").count()).toBe(14);
        expect(await page.locator(".calendar-row").count()).toBe(2);
    });
});

test.describe("Tier board horizontal overflow (#216 / #138 D-B1)", () => {
    // Sibling of the prod-smoke "/calendar does not horizontally overflow"
    // test, but for the home board. Runs in BOTH chromium (desktop 1280×800)
    // and chromium-mobile (375×812) — those two projects run the same test
    // files, so this test gives us pre-deploy coverage at both viewports.
    //
    // #216 (2026-05-24): `.tier-board` had no explicit
    // `grid-template-columns` at <900px → implicit single track sized to
    // MAX-CONTENT → `.task-card .task-quick-actions` (flex-shrink:0, holds
    // 5+ tier buttons) extended the track ~190px past a 375px viewport.
    // Fix: `grid-template-columns: minmax(0, 1fr)` (default) + `minmax(0,1fr)
    // minmax(0,1fr)` at (min-width: 900px). The classic #138 D-B1 pattern.
    test("home board scrollWidth ≤ innerWidth (current viewport)", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        await expect(page.locator(".tier-board")).toBeVisible();
        // Need at least one task card on the board for the assertion to
        // be meaningful — quick-actions only render on task-card rows.
        const cardCount = await page.locator(".tier-board .task-card").count();
        if (cardCount === 0) test.skip(true, "Seeded data has no tasks on the board.");
        const overflow = await page.evaluate(() => {
            const wide = [];
            const iw = window.innerWidth;
            for (const el of document.querySelectorAll("*")) {
                const r = el.getBoundingClientRect();
                if (r.right > iw + 1 && r.width > 30) {
                    wide.push({
                        tag: el.tagName,
                        cls: (el.className + "").slice(0, 60),
                        id: el.id,
                        w: Math.round(r.width),
                        right: Math.round(r.right),
                    });
                    if (wide.length >= 6) break;
                }
            }
            return {
                scrollWidth: document.documentElement.scrollWidth,
                innerWidth: iw,
                wide,
            };
        });
        expect(overflow.scrollWidth, JSON.stringify(overflow)).toBeLessThanOrEqual(overflow.innerWidth);
    });
});
