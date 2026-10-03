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

// #274: pure page-load console-error checks — ui_audit.spec.js audits the
// SAME routes for console errors (plus overflow + touch targets) at 375px,
// so re-running these at mobile is redundant. @noviewport skips them on
// chromium-mobile.
test.describe("Page navigation — no console errors @noviewport", () => {
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

        // Click the first task card. Target the title's TOP-LEFT (not the
        // card center): since #281 the mobile card wraps the tier-jump buttons
        // onto their own row below, so a center-of-card click can land on a
        // button (which stopPropagation's to move the tier, not open detail).
        // The x/y offset also dodges the DESKTOP hover-overlay quick-actions —
        // it's position:absolute right-anchored and (being opacity:0, not
        // pointer-events:none) still intercepts hit-tests over the title's
        // right/center. The title's left edge is always clear of both, and a
        // click there bubbles to the card's open-detail handler.
        const firstCard = page.locator(".task-card").first();
        await firstCard.locator(".task-title").click({ position: { x: 4, y: 4 } });

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

// #274: these drag tests dispatch DataTransfer events programmatically and
// assert the resulting DB state (due_date / tier / sort_order) — not pixel
// layout — so they're viewport-independent. @noviewport skips them at
// mobile. (Real-pointer reachability at 375px is covered by the
// interaction tests that stay, plus ui_audit's touch-target floor.)
test.describe("Calendar drag-and-drop (#94) @noviewport", () => {
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

    test("drag a task to the top of its own day cell reorders it within the day (#267)", async ({
        page, request,
    }) => {
        // Three today-tier tasks (no due_date → today's cell via the tier
        // fallback). New tasks default sort_order=0, so they list newest-first
        // (created_at desc): created[2], created[1], created[0]. created[0] is
        // therefore at the BOTTOM — dragging it to the very top is a real move.
        const created = [];
        for (let i = 0; i < 3; i++) {
            const r = await request.post("/api/tasks", {
                data: { title: `CAL-REORDER ${Date.now()}-${i}`, type: "work", tier: "today" },
            });
            created.push(await r.json());
        }
        try {
            await page.goto("/calendar?nosw=1");
            await page.waitForLoadState("networkidle");
            const todayIso = await page.evaluate(() => {
                const d = new Date(); d.setHours(0, 0, 0, 0);
                const y = d.getFullYear();
                const m = String(d.getMonth() + 1).padStart(2, "0");
                const day = String(d.getDate()).padStart(2, "0");
                return `${y}-${m}-${day}`;
            });
            const cell = page.locator(`.calendar-cell[data-date="${todayIso}"]`);
            await expect(cell).toBeVisible();
            await expect(
                cell.locator(`li[data-task-id="${created[0].id}"]`)
            ).toBeVisible();

            // Dispatch a real within-cell drag of created[0] to the very top.
            // clientY just above the first row makes the pure helper insert it
            // at index 0. dragstart on the li sets _dragSourceDate=todayIso;
            // the cell drop handler sees source===target → reorder path.
            await page.evaluate((args) => {
                const sel = `.calendar-cell[data-date="${args.iso}"]`;
                const li = document.querySelector(`${sel} li[data-task-id="${args.id}"]`);
                const cellEl = document.querySelector(sel);
                const list = cellEl.querySelector(".calendar-cell-tasks");
                const firstLi = list.querySelector("li[data-task-id]");
                const topY = firstLi.getBoundingClientRect().top - 3;
                const dt = new DataTransfer();
                dt.setData("text/plain", args.id);
                li.dispatchEvent(new DragEvent("dragstart", { dataTransfer: dt, bubbles: true }));
                cellEl.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true, clientY: topY }));
                cellEl.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true, clientY: topY }));
            }, { id: created[0].id, iso: todayIso });

            // Wait for the reorder PATCH + re-render + DB to land.
            await page.waitForTimeout(600);

            // created[0] was dropped at the absolute top of the cell → it must
            // now have the smallest sort_order of the three (index 0 in the
            // cell's new order).
            const after = await Promise.all(created.map(async (c) => {
                const res = await request.get(`/api/tasks/${c.id}`);
                return res.json();
            }));
            const so = Object.fromEntries(after.map((t) => [t.id, t.sort_order]));
            expect(so[created[0].id]).toBeLessThan(so[created[1].id]);
            expect(so[created[0].id]).toBeLessThan(so[created[2].id]);
        } finally {
            for (const c of created) {
                await request.delete(`/api/tasks/${c.id}`);
            }
        }
    });

    test("within-cell reorder to the bottom keeps tasks distinct + moves the dragged one down (#279)", async ({
        page, request,
    }) => {
        // #279: the within-cell reorder now renumbers the dragged task's whole
        // tier (collision-free). Behavioral check on the live path: drag the
        // top task to the bottom and confirm it moves down AND the three tasks
        // keep distinct sort_orders (the cross-cell substitution math is
        // unit-tested in calendar_bucket_helpers.test.js `reorderTierWithCell`).
        const created = [];
        for (let i = 0; i < 3; i++) {
            const r = await request.post("/api/tasks", {
                data: { title: `CAL-SLOT ${Date.now()}-${i}`, type: "work", tier: "today" },
            });
            created.push(await r.json());
        }
        try {
            await page.goto("/calendar?nosw=1");
            await page.waitForLoadState("networkidle");
            const todayIso = await page.evaluate(() => {
                const d = new Date(); d.setHours(0, 0, 0, 0);
                const y = d.getFullYear();
                const m = String(d.getMonth() + 1).padStart(2, "0");
                const day = String(d.getDate()).padStart(2, "0");
                return `${y}-${m}-${day}`;
            });
            const cell = page.locator(`.calendar-cell[data-date="${todayIso}"]`);
            // Newest-first display: created[2] is at the TOP — drag it to bottom.
            await expect(
                cell.locator(`li[data-task-id="${created[2].id}"]`)
            ).toBeVisible();
            await page.evaluate((args) => {
                const sel = `.calendar-cell[data-date="${args.iso}"]`;
                const li = document.querySelector(`${sel} li[data-task-id="${args.id}"]`);
                const cellEl = document.querySelector(sel);
                const list = cellEl.querySelector(".calendar-cell-tasks");
                const lis = list.querySelectorAll("li[data-task-id]");
                const lastLi = lis[lis.length - 1];
                const bottomY = lastLi.getBoundingClientRect().bottom + 3;
                const dt = new DataTransfer();
                dt.setData("text/plain", args.id);
                li.dispatchEvent(new DragEvent("dragstart", { dataTransfer: dt, bubbles: true }));
                cellEl.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true, clientY: bottomY }));
                cellEl.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true, clientY: bottomY }));
            }, { id: created[2].id, iso: todayIso });

            await page.waitForTimeout(700);

            const after = await Promise.all(created.map(async (c) => {
                const res = await request.get(`/api/tasks/${c.id}`);
                return res.json();
            }));
            const so = Object.fromEntries(after.map((t) => [t.id, t.sort_order]));
            // created[2] dragged to the bottom → now after created[0] & created[1].
            expect(so[created[2].id]).toBeGreaterThan(so[created[0].id]);
            expect(so[created[2].id]).toBeGreaterThan(so[created[1].id]);
            // No collision among the three.
            const vals = [so[created[0].id], so[created[1].id], so[created[2].id]];
            expect(new Set(vals).size).toBe(3);
        } finally {
            for (const c of created) {
                await request.delete(`/api/tasks/${c.id}`);
            }
        }
    });
});

test.describe("Multi-drag: dragging a selected card moves the whole group @noviewport", () => {
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

test.describe("Tier-column drag updates due_date for today/tomorrow @noviewport", () => {
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
            await card.locator(".task-title").click({ position: { x: 4, y: 4 } });  // #281: title top-left, not card center (see above)
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
            await card.locator(".task-title").click({ position: { x: 4, y: 4 } });  // #281: title top-left, not card center (see above)
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
            await card.locator(".task-title").click({ position: { x: 4, y: 4 } });  // #281: title top-left, not card center (see above)
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

test.describe("Calendar concurrent-render race (#219) @noviewport", () => {
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

/**
 * #323 — create a recurring template from /recurring.
 *
 * Until this shipped, the page could only list and edit; a template had
 * to be born from a capture-bar hint, a task's repeat rule, or a voice
 * memo. The round-trip (button → blank panel → POST → row in the list
 * after a reload) is the actual user path, so it gets a real browser
 * assertion rather than trusting the Jest helper tests alone.
 */
test.describe("Recurring — create a template from the page (#323)", () => {
    test("+ New template round-trips a new row into the list", async ({ page }) => {
        await page.goto("/recurring?nosw=1");
        await page.waitForLoadState("networkidle");

        const title = `E2E weekly template ${Date.now()}`;

        await page.locator("#recurringNew").click();
        const panel = page.locator("#recurEditOverlay");
        await expect(panel).toBeVisible({ timeout: 2000 });

        // Create mode: heading + submit label switch, and the actions that
        // need an existing row are hidden rather than left to fail.
        await expect(page.locator("#recurEditHeading")).toHaveText("New recurring template");
        await expect(page.locator("#recurEditSave")).toHaveText("Create");
        await expect(page.locator("#recurEditPause")).toBeHidden();
        await expect(page.locator("#recurEditDelete")).toBeHidden();

        await page.locator("#recurEditTitle").fill(title);
        await page.locator("#recurEditFrequency").selectOption("weekly");
        // Weekly reveals the day picker, pre-set to today's weekday.
        await expect(page.locator("#recurEditWeeklyField")).toBeVisible();
        await page.locator("#recurEditSave").click();

        // Panel closes and the list re-renders with the new template.
        await expect(panel).toBeHidden({ timeout: 3000 });
        await expect(page.locator(".recurring-row", { hasText: title })).toHaveCount(1);

        // It really persisted — not just an optimistic client-side row.
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(page.locator(".recurring-row", { hasText: title })).toHaveCount(1);
    });

    test("opening an existing row after a create shows edit mode again", async ({ page }) => {
        // The panel is shared, so create mode must not leak into the next
        // edit (hidden Pause/Delete would strand the user).
        await page.goto("/recurring?nosw=1");
        await page.waitForLoadState("networkidle");

        await page.locator("#recurringNew").click();
        await expect(page.locator("#recurEditPause")).toBeHidden();
        await page.locator("#recurEditClose").click();

        await page.locator(".recurring-row .recurring-row-info").first().click();
        await expect(page.locator("#recurEditOverlay")).toBeVisible({ timeout: 2000 });
        await expect(page.locator("#recurEditHeading")).toHaveText("Edit recurring template");
        await expect(page.locator("#recurEditSave")).toHaveText("Save");
        await expect(page.locator("#recurEditPause")).toBeVisible();
        await expect(page.locator("#recurEditDelete")).toBeVisible();
    });
});

/**
 * #324 — a reflection written across several sittings must survive
 * leaving the page.
 *
 * Before this, the in-progress text lived only in the textarea: a reload,
 * a closed tab, or iOS evicting the PWA destroyed it silently. Nothing in
 * the browser persists that text across a reload, so if it comes back
 * after one, it genuinely came from the server — which is also what makes
 * it follow the user from phone to laptop.
 */
test.describe("Reflection — resumable drafts (#324)", () => {
    test.beforeEach(async ({ page }) => {
        // Start from a known state; a leftover draft would mask a failure.
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.evaluate(() => fetch("/api/reflection/draft", { method: "DELETE" }));
    });

    test.afterEach(async ({ page }) => {
        await page.evaluate(() => fetch("/api/reflection/draft", { method: "DELETE" }));
    });

    test("typed text autosaves and is restored after a reload", async ({ page }) => {
        const text = `Week of prep notes ${Date.now()}`;

        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");

        // No banner before there is anything to restore.
        await expect(page.locator("#reflDraftBanner")).toBeHidden();

        await page.locator("#reflText").fill(text);
        await expect(page.locator("#reflDraftStatus")).toHaveText(
            "Draft saved", { timeout: 5000 },
        );

        // The reload is the whole point: nothing client-side keeps this.
        await page.reload();
        await page.waitForLoadState("networkidle");

        await expect(page.locator("#reflText")).toHaveValue(text, { timeout: 5000 });
        await expect(page.locator("#reflDraftBanner")).toBeVisible();
        await expect(page.locator("#reflDraftBannerText")).toContainText("Draft restored");
    });

    test("adding to a restored draft keeps both sittings", async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator("#reflText").fill("Sitting one.");
        await expect(page.locator("#reflDraftStatus")).toHaveText(
            "Draft saved", { timeout: 5000 },
        );

        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#reflText")).toHaveValue("Sitting one.", { timeout: 5000 });

        await page.locator("#reflText").fill("Sitting one. Sitting two.");
        await expect(page.locator("#reflDraftStatus")).toHaveText(
            "Draft saved", { timeout: 5000 },
        );

        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#reflText")).toHaveValue(
            "Sitting one. Sitting two.", { timeout: 5000 },
        );
    });

    test("discarding a draft clears it for good", async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator("#reflText").fill("Text to throw away.");
        await expect(page.locator("#reflDraftStatus")).toHaveText(
            "Draft saved", { timeout: 5000 },
        );

        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#reflDraftBanner")).toBeVisible({ timeout: 5000 });

        page.once("dialog", (d) => d.accept());
        await page.locator("#reflDraftDiscard").click();
        await expect(page.locator("#reflText")).toHaveValue("");
        await expect(page.locator("#reflDraftBanner")).toBeHidden();

        // And it stays gone.
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#reflText")).toHaveValue("");
        await expect(page.locator("#reflDraftBanner")).toBeHidden();
    });

    test("an untouched empty box does not create a phantom draft", async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator("#reflText").click();
        await page.waitForTimeout(2000);  // longer than the autosave debounce

        const draft = await page.evaluate(() =>
            fetch("/api/reflection/draft").then((r) => r.json()));
        expect(draft.draft).toBeNull();
    });
});

/**
 * #325 — the reflection milestone header.
 *
 * The countdown is what makes a multi-week plan legible, so the
 * round-trip (set → header renders → survives a reload) gets a real
 * browser assertion rather than trusting the helper tests alone.
 */
test.describe("Reflection — milestone runway (#325)", () => {
    test.beforeEach(async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.evaluate(() =>
            fetch("/api/reflection/milestone", { method: "DELETE" }));
    });

    test.afterEach(async ({ page }) => {
        await page.evaluate(() =>
            fetch("/api/reflection/milestone", { method: "DELETE" }));
    });

    test("unset shows an invitation, not an empty bar", async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#reflMilestoneTitle")).toHaveText(
            "No milestone set", { timeout: 5000 },
        );
        await expect(page.locator("#reflMilestoneEdit")).toHaveText("Set a milestone");
    });

    test("setting a milestone renders the countdown and survives reload",
        async ({ page }) => {
            await page.goto("/reflection?nosw=1");
            await page.waitForLoadState("networkidle");

            await page.locator("#reflMilestoneEdit").click();
            await expect(page.locator("#reflMilestoneForm")).toBeVisible();

            await page.locator("#reflMilestoneLabel").fill("New role starts");
            await page.locator("#reflMilestoneDate").fill("2099-01-01");
            await page.locator("#reflMilestoneSave").click();

            await expect(page.locator("#reflMilestoneForm")).toBeHidden({ timeout: 5000 });
            await expect(page.locator("#reflMilestoneTitle")).toContainText(
                "Working toward: New role starts",
            );
            await expect(page.locator("#reflMilestoneTitle")).toContainText("1 Jan 2099");
            await expect(page.locator("#reflMilestoneSub")).toContainText("left");

            await page.reload();
            await page.waitForLoadState("networkidle");
            await expect(page.locator("#reflMilestoneTitle")).toContainText(
                "New role starts", { timeout: 5000 },
            );
        });

    test("clearing removes it for good", async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator("#reflMilestoneEdit").click();
        await page.locator("#reflMilestoneLabel").fill("Temporary");
        await page.locator("#reflMilestoneDate").fill("2099-01-01");
        await page.locator("#reflMilestoneSave").click();
        await expect(page.locator("#reflMilestoneTitle")).toContainText("Temporary");

        await page.locator("#reflMilestoneEdit").click();
        page.once("dialog", (d) => d.accept());
        await page.locator("#reflMilestoneClear").click();
        await expect(page.locator("#reflMilestoneTitle")).toHaveText(
            "No milestone set", { timeout: 5000 },
        );

        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#reflMilestoneTitle")).toHaveText(
            "No milestone set", { timeout: 5000 },
        );
    });

    test("picking a goal takes over the name field", async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator("#reflMilestoneEdit").click();

        const opts = page.locator("#reflMilestoneGoal option");
        if (await opts.count() < 2) test.skip(true, "no goals seeded");

        await page.locator("#reflMilestoneGoal").selectOption({ index: 1 });
        // The label mirrors the goal and locks — the name comes from the goal.
        await expect(page.locator("#reflMilestoneLabel")).toBeDisabled();
        const goalTitle = await opts.nth(1).textContent();
        await expect(page.locator("#reflMilestoneLabel")).toHaveValue(goalTitle.trim());

        await page.locator("#reflMilestoneDate").fill("2099-01-01");
        await page.locator("#reflMilestoneSave").click();
        await expect(page.locator("#reflMilestoneTitle")).toContainText(
            goalTitle.trim(), { timeout: 5000 },
        );
    });
});

/**
 * #327 — the transient on-device audio buffer, against REAL IndexedDB.
 *
 * This is the regression test the ADR's promise rests on. The app's
 * guarantee changed from "audio is never written to disk" to "audio may
 * rest on THIS DEVICE temporarily, then is cleaned up" — so the thing
 * that must be mechanically enforced is the CLEANUP, not the storage.
 */
test.describe("Reflection — transient audio buffer (#327)", () => {
    const seed = async (page, segmentId, chunks, startedAt) => page.evaluate(
        async ([id, sizes, started]) => {
            await window.audioBuffer.beginSegment(id, {
                startedAt: started, mime: "audio/webm",
            });
            for (let i = 0; i < sizes.length; i++) {
                await window.audioBuffer.putChunk(
                    id, i, new Blob([new Uint8Array(sizes[i])]), "audio/webm",
                );
            }
        }, [segmentId, chunks, startedAt]);

    test.beforeEach(async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.evaluate(() => window.audioBuffer.purgeAll());
    });

    test.afterEach(async ({ page }) => {
        await page.evaluate(() => window.audioBuffer.purgeAll());
    });

    test("chunks persist and reassemble in order", async ({ page }) => {
        await seed(page, "seg-a", [100, 200, 300], Date.now());
        const out = await page.evaluate(async () => {
            const segs = await window.audioBuffer.listSegments();
            const blob = await window.audioBuffer.assembleSegment("seg-a");
            return { count: segs.length, bytes: segs[0].bytes,
                     chunkCount: segs[0].chunkCount, assembled: blob ? blob.size : null };
        });
        expect(out.count).toBe(1);
        expect(out.bytes).toBe(600);
        expect(out.chunkCount).toBe(3);
        // Reassembly must total the parts — ordering/completeness is correctness.
        expect(out.assembled).toBe(600);
    });

    test("it SURVIVES a reload — that is the whole point", async ({ page }) => {
        await seed(page, "seg-survive", [500], Date.now());
        await page.reload();
        await page.waitForLoadState("networkidle");
        const bytes = await page.evaluate(async () => {
            const segs = await window.audioBuffer.listSegments();
            return segs.length ? segs[0].bytes : 0;
        });
        expect(bytes).toBe(500);
    });

    test("dropSegment leaves NOTHING behind — the cleanup promise", async ({ page }) => {
        await seed(page, "seg-drop", [100, 100], Date.now());
        const after = await page.evaluate(async () => {
            await window.audioBuffer.dropSegment("seg-drop");
            const segs = await window.audioBuffer.listSegments();
            const blob = await window.audioBuffer.assembleSegment("seg-drop");
            return { segs: segs.length, blob: blob === null };
        });
        expect(after.segs).toBe(0);
        expect(after.blob).toBe(true);   // chunks gone, not just the index row
    });

    test("dropping one segment does not touch another", async ({ page }) => {
        await seed(page, "seg-1", [100], Date.now());
        await seed(page, "seg-2", [250], Date.now());
        const out = await page.evaluate(async () => {
            await window.audioBuffer.dropSegment("seg-1");
            const segs = await window.audioBuffer.listSegments();
            return { ids: segs.map(s => s.segmentId), bytes: segs[0] && segs[0].bytes };
        });
        expect(out.ids).toEqual(["seg-2"]);
        expect(out.bytes).toBe(250);
    });

    test("purgeExpired deletes audio past the retention window", async ({ page }) => {
        const old = Date.now() - 25 * 60 * 60 * 1000;   // 25h — expired
        const fresh = Date.now() - 60 * 60 * 1000;      // 1h  — keep
        await seed(page, "seg-old", [100], old);
        await seed(page, "seg-fresh", [100], fresh);
        const out = await page.evaluate(async () => {
            const dropped = await window.audioBuffer.purgeExpired();
            const segs = await window.audioBuffer.listSegments();
            return { dropped, remaining: segs.map(s => s.segmentId) };
        });
        expect(out.dropped).toBe(1);
        expect(out.remaining).toEqual(["seg-fresh"]);
    });

    test("purgeAll clears everything (Done / Cancel path)", async ({ page }) => {
        await seed(page, "seg-x", [100], Date.now());
        await seed(page, "seg-y", [100], Date.now());
        const left = await page.evaluate(async () => {
            await window.audioBuffer.purgeAll();
            return (await window.audioBuffer.listSegments()).length;
        });
        expect(left).toBe(0);
    });

    test("orphaned audio is OFFERED on load, not silently used or binned",
        async ({ page }) => {
            await seed(page, "seg-orphan", [32000 * 60 / 8], Date.now());
            await page.reload();
            await page.waitForLoadState("networkidle");
            const banner = page.locator("#reflRecoverBanner");
            await expect(banner).toBeVisible({ timeout: 5000 });
            await expect(page.locator("#reflRecoverText")).toContainText("about 1 minute");
            // Still present — offering must not consume it.
            const still = await page.evaluate(async () =>
                (await window.audioBuffer.listSegments()).length);
            expect(still).toBe(1);
        });

    test("an EXPIRED orphan is purged on load, never offered", async ({ page }) => {
        await seed(page, "seg-stale", [50000], Date.now() - 30 * 60 * 60 * 1000);
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#reflRecoverBanner")).toBeHidden();
        const left = await page.evaluate(async () =>
            (await window.audioBuffer.listSegments()).length);
        expect(left).toBe(0);
    });

    test("Discard removes the recovered audio for good", async ({ page }) => {
        await seed(page, "seg-discard", [40000], Date.now());
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#reflRecoverBanner")).toBeVisible({ timeout: 5000 });
        page.once("dialog", (d) => d.accept());
        await page.locator("#reflRecoverDiscard").click();
        await expect(page.locator("#reflRecoverBanner")).toBeHidden();
        const left = await page.evaluate(async () =>
            (await window.audioBuffer.listSegments()).length);
        expect(left).toBe(0);
    });

    test("nothing buffered means no banner at all", async ({ page }) => {
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#reflRecoverBanner")).toBeHidden();
    });
});

/**
 * #328 — reflection context documents, end to end through a real upload.
 *
 * The unit tests cover extraction and the prompt fence. What only a
 * browser can prove is the part the user actually touches: that a real
 * multipart upload round-trips, that the row says what was read, that an
 * attachment SURVIVES a reload (the multi-sitting promise this feature
 * exists for), and that the keystroke autosave doesn't quietly eat it.
 */
test.describe("Reflection — context files (#328)", () => {
    // Drives the real <input type=file> with an in-memory buffer, so the
    // whole multipart path runs exactly as it does for a user.
    const attach = async (page, name, mimeType, body) => {
        await page.locator("#reflContextInput").setInputFiles({
            name, mimeType, buffer: Buffer.from(body),
        });
    };

    const clearDraft = async (page) => page.evaluate(async () => {
        await fetch("/api/reflection/draft", {
            method: "DELETE", credentials: "same-origin",
        });
    });

    test.beforeEach(async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await clearDraft(page);
        await page.reload();
        await page.waitForLoadState("networkidle");
    });

    test.afterEach(async ({ page }) => {
        await clearDraft(page);
    });

    test("the block is visible and starts empty", async ({ page }) => {
        await expect(page.locator("#reflContext")).toBeVisible();
        await expect(page.locator(".reflection-context-add")).toBeVisible();
        // No empty-state noise on a fresh reflection.
        await expect(page.locator("#reflContextList")).toBeEmpty();
        await expect(page.locator("#reflContextSummary")).toHaveText("");
    });

    test("attaching a note lists it with its character count", async ({ page }) => {
        await attach(page, "plan.md", "text/markdown",
            "# 30/60/90\n\nWeek one: learn the domain.");
        const row = page.locator(".reflection-context-item").first();
        await expect(row).toBeVisible({ timeout: 10000 });
        await expect(row.locator(".reflection-context-item-name"))
            .toHaveText("plan.md");
        await expect(row.locator(".reflection-context-item-meta"))
            .toContainText("MD");
        await expect(row.locator(".reflection-context-item-meta"))
            .toContainText("characters");
        await expect(page.locator("#reflContextSummary"))
            .toContainText("1 of 5 file");
        await expect(page.locator("#reflContextStatus"))
            .toContainText("Attached plan.md");
    });

    test("an attachment survives a reload — the multi-sitting promise",
        async ({ page }) => {
            await attach(page, "jd.txt", "text/plain",
                "Director of Engineering. Starts 2 November.");
            await expect(page.locator(".reflection-context-item"))
                .toHaveCount(1, { timeout: 10000 });

            await page.reload();
            await page.waitForLoadState("networkidle");

            await expect(page.locator(".reflection-context-item"))
                .toHaveCount(1, { timeout: 10000 });
            await expect(
                page.locator(".reflection-context-item-name").first()
            ).toHaveText("jd.txt");
        });

    test("typing does not wipe an attachment", async ({ page }) => {
        // The autosave loop sends only the textarea. If the server read
        // that silence as "no attachments", a file attached minutes
        // earlier would vanish mid-sentence.
        await attach(page, "notes.txt", "text/plain", "context that matters");
        await expect(page.locator(".reflection-context-item"))
            .toHaveCount(1, { timeout: 10000 });

        await page.locator("#reflText").fill("This week I mostly read the JD.");
        await expect(page.locator("#reflDraftStatus"))
            .toContainText("Draft saved", { timeout: 10000 });

        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(page.locator(".reflection-context-item"))
            .toHaveCount(1, { timeout: 10000 });
        await expect(page.locator("#reflText"))
            .toHaveValue("This week I mostly read the JD.");
    });

    test("Remove detaches it, and it stays gone", async ({ page }) => {
        await attach(page, "gone.txt", "text/plain", "temporary context");
        await expect(page.locator(".reflection-context-item"))
            .toHaveCount(1, { timeout: 10000 });

        await page.locator(".reflection-context-remove").first().click();
        await expect(page.locator(".reflection-context-item")).toHaveCount(0);
        await expect(page.locator("#reflContextStatus"))
            .toContainText("Removed gone.txt");

        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(page.locator(".reflection-context-item")).toHaveCount(0);
    });

    test("an unsupported type is refused without uploading", async ({ page }) => {
        await attach(page, "payload.exe", "application/octet-stream", "MZ\u0000");
        await expect(page.locator("#reflContextStatus"))
            .toContainText("isn't supported");
        await expect(page.locator(".reflection-context-item")).toHaveCount(0);
    });

    test("a text-free file is refused by the server with a real reason",
        async ({ page }) => {
            await attach(page, "blank.txt", "text/plain", "   \n  \n");
            await expect(page.locator("#reflContextStatus"))
                .toHaveClass(/reflection-context-status-err/, { timeout: 10000 });
            await expect(page.locator(".reflection-context-item")).toHaveCount(0);
        });

    test("the same file can be picked again after being removed",
        async ({ page }) => {
            // The <input> must be reset or the browser suppresses the
            // second change event and the re-pick silently does nothing.
            await attach(page, "again.txt", "text/plain", "first go");
            await expect(page.locator(".reflection-context-item"))
                .toHaveCount(1, { timeout: 10000 });
            await page.locator(".reflection-context-remove").first().click();
            await expect(page.locator(".reflection-context-item")).toHaveCount(0);

            await attach(page, "again.txt", "text/plain", "first go");
            await expect(page.locator(".reflection-context-item"))
                .toHaveCount(1, { timeout: 10000 });
        });

    test("the file cap disables the picker rather than failing late",
        async ({ page }) => {
            for (let i = 0; i < 5; i++) {
                await attach(page, `f${i}.txt`, "text/plain", `context ${i}`);
                await expect(page.locator(".reflection-context-item"))
                    .toHaveCount(i + 1, { timeout: 10000 });
            }
            await expect(page.locator("#reflContextSummary"))
                .toContainText("5 of 5 files");
            await expect(page.locator("#reflContextInput")).toBeDisabled();
            await expect(page.locator(".reflection-context-add"))
                .toHaveClass(/reflection-context-add-disabled/);
        });

    test("a long document is shortened and says so", async ({ page }) => {
        const big = "The quick brown fox jumps over the lazy dog. ".repeat(600);
        await attach(page, "handbook.txt", "text/plain", big);
        await expect(page.locator(".reflection-context-item-meta").first())
            .toContainText("shortened from", { timeout: 15000 });
        await expect(page.locator("#reflContextStatus"))
            .toContainText("only the first part");
    });

    test("discarding the draft clears the attachments", async ({ page }) => {
        await attach(page, "bye.txt", "text/plain", "context");
        await page.locator("#reflText").fill("some words");
        await expect(page.locator(".reflection-context-item"))
            .toHaveCount(1, { timeout: 10000 });
        await expect(page.locator("#reflDraftStatus"))
            .toContainText("Draft saved", { timeout: 10000 });

        // Discard-draft lives in the restored-draft banner, which only
        // renders on a load that FOUND a draft (#324) — so the round trip
        // is part of the scenario, not incidental to it.
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#reflDraftBanner")).toBeVisible({ timeout: 10000 });
        await expect(page.locator(".reflection-context-item")).toHaveCount(1);

        page.once("dialog", (d) => d.accept());
        await page.locator("#reflDraftDiscard").click();
        await expect(page.locator(".reflection-context-item")).toHaveCount(0);
        await expect(page.locator("#reflText")).toHaveValue("");
    });

    test("no horizontal overflow with a very long filename", async ({ page }) => {
        // #138 D-B1 class: a long unbroken string in a flex row.
        await attach(
            page,
            "a-really-very-extremely-long-attachment-filename-that-goes-on.txt",
            "text/plain", "context",
        );
        await expect(page.locator(".reflection-context-item"))
            .toHaveCount(1, { timeout: 10000 });
        const overflows = await page.evaluate(() =>
            document.documentElement.scrollWidth > window.innerWidth);
        expect(overflows).toBe(false);
    });
});

test.describe("Reflection - leaving the review screen (#329)", () => {
    // The review state is only reachable through POST /api/reflection,
    // which costs a real Claude call. Intercepting just that verb drives
    // the genuine renderReview() path for free; the GET history listing
    // on the same URL is left alone.
    const stubAnalyze = async (page, proposed) => {
        await page.route("**/api/reflection", async (route, request) => {
            if (request.method() !== "POST") return route.continue();
            await route.fulfill({
                status: 201,
                contentType: "application/json",
                body: JSON.stringify({
                    id: "00000000-0000-0000-0000-000000000329",
                    iso_week: "2026-W39",
                    input_mode: "typed",
                    transcript: "A quiet week.",
                    audio_duration_seconds: null,
                    audio_cost_usd: null,
                    ai_cost_usd: 0.0197,
                    proposed_actions: proposed,
                    raw_segments: [],
                    is_archived: false,
                    is_active: true,
                }),
            });
        });
    };

    const analyze = async (page) => {
        await page.locator("#reflText").fill("A quiet week.");
        await page.locator("#reflAnalyzeBtn").click();
        await expect(page.locator("#reflStateReview")).toBeVisible({ timeout: 10000 });
    };

    // .btn carries `transition: background 0.15s`, so a naive colour read
    // can sample mid-flight - or, where the compositor clock is throttled,
    // at currentTime 0 forever (observed in the Phase 6 preview pane
    // 2026-09-24: playState "running", currentTime 0, never advancing).
    // Finish any in-flight transition first so these assert the SETTLED
    // colour rather than a timing race.
    const SETTLED_BG = (el) => {
        el.getAnimations().forEach((a) => a.finish());
        return getComputedStyle(el).backgroundColor;
    };

    const NOTHING = { explicit: [], suggested: [] };
    const SOMETHING = {
        explicit: [{
            op: "create", entity: "task", target: "Draft the 30/60/90",
            reason: "You said you wanted one before day one.",
        }],
        suggested: [],
    };

    test.beforeEach(async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
    });

    // Typing into #reflText trips the #324 autosave, so every test here
    // leaves a server-side draft behind. The stubbed POST never reaches
    // the real submit path that would retire it, so clean up explicitly
    // rather than leaking a draft into whatever block runs next.
    test.afterEach(async ({ page }) => {
        await page.unroute("**/api/reflection").catch(() => {});
        await page.evaluate(async () => {
            await fetch("/api/reflection/draft", {
                method: "DELETE", credentials: "same-origin",
            });
        }).catch(() => {});
    });

    test("an empty review still offers a way back to the board", async ({ page }) => {
        // The reported bug: Claude proposes nothing, Apply and Focus hide
        // themselves, and the only control left is "Start Over" - which
        // reads like "discard this" on a screen whose transcript is
        // already saved.
        await stubAnalyze(page, NOTHING);
        await analyze(page);

        await expect(page.locator("#reflEmpty")).toBeVisible();
        await expect(page.locator("#reflApplyBtn")).toBeHidden();
        await expect(page.locator("#reflFocusBtn")).toBeHidden();

        const exit = page.locator("#reflReviewExit");
        await expect(exit).toBeVisible();
        await expect(exit).toHaveText("Go to Tasks");
        await expect(exit).toHaveAttribute("href", "/");
    });

    test("the exit becomes the primary action when there is nothing to apply",
        async ({ page }) => {
            await stubAnalyze(page, NOTHING);
            await analyze(page);
            // .btn-sm dropped => the filled .btn rule applies. Assert the
            // rendered colour, not just the class, so a CSS change that
            // breaks the promotion is caught too.
            await expect(page.locator("#reflReviewExit")).not.toHaveClass(/btn-sm/);
            await page.mouse.move(0, 0);
            const filled = await page.locator("#reflReviewExit").evaluate(SETTLED_BG);
            const neutral = await page.locator("#reflStartOverBtn").evaluate(SETTLED_BG);
            expect(filled).not.toBe(neutral);
        });

    test("the exit stays neutral while Apply Selected is on screen",
        async ({ page }) => {
            await stubAnalyze(page, SOMETHING);
            await analyze(page);
            await expect(page.locator("#reflApplyBtn")).toBeVisible();
            await expect(page.locator("#reflReviewExit")).toBeVisible();
            await expect(page.locator("#reflReviewExit")).toHaveClass(/btn-sm/);
            // The class alone isn't enough: .btn and .btn-sm both set a
            // background at equal specificity, so .btn-sm only wins by
            // source order. Assert the resting colour instead.
            //
            // Compare against the --surface token, NOT against Start
            // Over: at mobile the row is full-width and stacked, so
            // after the Analyze click the pointer rests over whichever
            // control reflows under it and .btn-sm:hover paints that one
            // --surface-sunk. Parking the mouse makes this deterministic
            // either way.
            await page.mouse.move(0, 0);
            const exitBg = await page.locator("#reflReviewExit").evaluate(SETTLED_BG);
            const applyBg = await page.locator("#reflApplyBtn").evaluate(SETTLED_BG);
            const surface = await page.evaluate(() => {
                const probe = document.createElement("span");
                probe.style.backgroundColor = "var(--surface)";
                document.body.appendChild(probe);
                const c = getComputedStyle(probe).backgroundColor;
                probe.remove();
                return c;
            });
            expect(exitBg).toBe(surface);
            expect(exitBg).not.toBe(applyBg);
        });

    test("clicking it really navigates - nothing swallows the click",
        async ({ page }) => {
            await stubAnalyze(page, NOTHING);
            await analyze(page);
            // Stub the destination document so this proves the top-level
            // navigation fired without loading the real board (which would
            // register a service worker mid-suite; every other test here
            // runs with ?nosw=1 precisely to avoid that).
            await page.route(/^https?:\/\/[^/]+\/$/, async (route, request) => {
                if (request.resourceType() !== "document") return route.continue();
                await route.fulfill({
                    status: 200, contentType: "text/html",
                    body: "<title>board stub</title>ok",
                });
            });
            await page.locator("#reflReviewExit").click();
            await expect(page).toHaveTitle("board stub");
        });

    test("the exit is reachable and centred alongside its button siblings",
        async ({ page }) => {
            await stubAnalyze(page, NOTHING);
            await analyze(page);
            const exit = page.locator("#reflReviewExit");
            const box = await exit.boundingBox();
            const startOver = await page.locator("#reflStartOverBtn").boundingBox();
            const mobile = (page.viewportSize() || {}).width < 700;

            if (mobile) {
                // 44px touch-target floor, and the <a> must centre its
                // label the way its <button> siblings do. That comes from
                // the shared mobile rule at style.css:3218
                // (.btn/.btn-sm -> inline-flex + centred); an <a class="btn">
                // left as plain inline-block would top-align its text in the
                // 48px box. Asserted here because this row is the only place
                // an anchor and a button sit side by side under that rule.
                expect(box.height).toBeGreaterThanOrEqual(44);
                const offset = await exit.evaluate((el) => {
                    const t = el.getBoundingClientRect();
                    const r = document.createRange();
                    r.selectNodeContents(el);
                    const text = r.getBoundingClientRect();
                    return Math.abs(
                        (text.top - t.top) - (t.bottom - text.bottom));
                });
                // Measured 2026-09-24 at 375px: 13.2 top / 14.8 bottom
                // (1.6 apart - an <a> line box leads differently from a
                // <button>'s). Top-aligned instead would be 7 / 21, i.e.
                // 14 apart, so 6 separates them decisively without
                // flaking on sub-pixel font rendering.
                expect(offset).toBeLessThanOrEqual(6);
            }
            expect(box.height).toBeCloseTo(startOver.height, 0);
        });

    test("no horizontal overflow on the review screen", async ({ page }) => {
        await stubAnalyze(page, SOMETHING);
        await analyze(page);
        const overflows = await page.evaluate(() =>
            document.documentElement.scrollWidth > window.innerWidth);
        expect(overflows).toBe(false);
    });
});

test.describe("Reflection - Record tab says Resume, not Start (#332)", () => {
    const setDraft = async (page, text) => page.evaluate(async (t) => {
        await fetch("/api/reflection/draft", {
            method: "PUT",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: t }),
        });
    }, text);

    const clearDraft = async (page) => page.evaluate(async () => {
        await fetch("/api/reflection/draft", {
            method: "DELETE", credentials: "same-origin",
        });
    });

    test.beforeEach(async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await clearDraft(page);
    });

    test.afterEach(async ({ page }) => {
        await clearDraft(page).catch(() => {});
    });

    test("a brand-new reflection still says Start recording", async ({ page }) => {
        await page.reload();
        await page.waitForLoadState("networkidle");
        await page.locator("#reflTabVoice").click();
        await expect(page.locator("#reflRecordBtn .voice-record-label"))
            .toHaveText("Start recording");
        // No reassurance noise for someone who has nothing to lose yet.
        await expect(page.locator("#reflResumeNote")).toBeHidden();
    });

    test("a restored draft flips the button to Resume with a word count",
        async ({ page }) => {
            // The reported case: page reloads mid-reflection, user opens
            // Record, and the transcript is hidden by selectMode - so the
            // button is the only thing telling them their words survived.
            await setDraft(page, "one two three four five six seven");
            await page.reload();
            await page.waitForLoadState("networkidle");
            await expect(page.locator("#reflText"))
                .toHaveValue(/one two three/, { timeout: 10000 });

            await page.locator("#reflTabVoice").click();
            await expect(page.locator("#reflRecordBtn .voice-record-label"))
                .toHaveText("Resume recording");
            const note = page.locator("#reflResumeNote");
            await expect(note).toBeVisible();
            await expect(note).toContainText("7 words so far");
            await expect(note).toContainText("added to the end");
            await expect(note).toContainText(
                "nothing you have already said is replaced");
        });

    test("the accessible name tells a screen reader the same thing",
        async ({ page }) => {
            await setDraft(page, "alpha beta");
            await page.reload();
            await page.waitForLoadState("networkidle");
            await expect(page.locator("#reflText")).toHaveValue(/alpha/, { timeout: 10000 });
            await page.locator("#reflTabVoice").click();
            await expect(page.locator("#reflRecordBtn"))
                .toHaveAttribute("aria-label", /^Resume recording/);
            await expect(page.locator("#reflRecordBtn"))
                .toHaveAttribute("aria-label", /2 words already captured/);
        });

    test("typing into an empty reflection promotes the button to Resume",
        async ({ page }) => {
            // Proves the copy is derived from live text, not from a
            // one-shot "did we restore a draft?" flag set at load.
            await page.reload();
            await page.waitForLoadState("networkidle");
            await page.locator("#reflTabVoice").click();
            await expect(page.locator("#reflRecordBtn .voice-record-label"))
                .toHaveText("Start recording");

            await page.locator("#reflTabType").click();
            await page.locator("#reflText").fill("now there are some words here");
            await page.locator("#reflTabVoice").click();
            await expect(page.locator("#reflRecordBtn .voice-record-label"))
                .toHaveText("Resume recording");
            await expect(page.locator("#reflResumeNote"))
                .toContainText("6 words so far");
        });

    test("the Record tab does not overflow with the note shown", async ({ page }) => {
        await setDraft(page, Array(40).fill("reflection").join(" "));
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#reflText")).toHaveValue(/reflection/, { timeout: 10000 });
        await page.locator("#reflTabVoice").click();
        await expect(page.locator("#reflResumeNote")).toBeVisible();
        const overflows = await page.evaluate(() =>
            document.documentElement.scrollWidth > window.innerWidth);
        expect(overflows).toBe(false);
    });
});

test.describe("Reflection - a live recording blocks the SW auto-reload (#331)", () => {
    // Drives a REAL MediaRecorder against Chromium's fake capture device
    // (see FAKE_MEDIA_ARGS in playwright.config.js) and asserts the actual
    // guard in base.html - not a re-implementation of its rule, which
    // would pass even if the guard were deleted.
    test.beforeEach(async ({ page, context }) => {
        await context.grantPermissions(["microphone"]);
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.evaluate(async () => {
            await fetch("/api/reflection/draft", {
                method: "DELETE", credentials: "same-origin",
            });
        });
    });

    test.afterEach(async ({ page }) => {
        await page.evaluate(async () => {
            await fetch("/api/reflection/draft", {
                method: "DELETE", credentials: "same-origin",
            });
        }).catch(() => {});
    });

    test("an idle reflection page does not block updates", async ({ page }) => {
        // Fail-open baseline: without this, the guard could block forever
        // and quietly strand the user on stale code.
        expect(await page.evaluate(() => window.__userIsBusy())).toBe(false);
        expect(await page.evaluate(() => !!window.__mediaCaptureBusy)).toBe(false);
    });

    test("recording blocks, and stopping unblocks", async ({ page }) => {
        await page.locator("#reflTabVoice").click();
        await page.locator("#reflRecordBtn").click();
        await expect(page.locator("#reflVoiceRecording")).toBeVisible({ timeout: 15000 });

        // The exact condition of the 2026-09-24 incident: audio live, no
        // focused field. The old guard returned false here and the page
        // reloaded out from under the user.
        expect(await page.evaluate(() => document.activeElement.tagName.toLowerCase()))
            .not.toBe("textarea");
        expect(await page.evaluate(() => window.__userIsBusy())).toBe(true);

        // Cancel discards the audio and returns to idle -> safe to update.
        await page.locator("#reflCancelBtn").click();
        await expect(page.locator("#reflVoiceIdle")).toBeVisible({ timeout: 15000 });
        await expect.poll(
            () => page.evaluate(() => window.__userIsBusy()),
            { timeout: 10000 }
        ).toBe(false);
    });

    test("the guard still catches a focused textarea", async ({ page }) => {
        // Regression cover for the ORIGINAL behaviour, so the #331 clause
        // can't be added by accidentally replacing what was there.
        await page.locator("#reflText").click();
        expect(await page.evaluate(() => window.__userIsBusy())).toBe(true);
    });
});

test.describe("Reflection - naming a sitting (#339)", () => {
    const firstRow = (page) =>
        page.locator("#reflHistory .reflection-history-item").first();

    const rename = async (page, value) => {
        page.once("dialog", (d) => d.accept(value));
        await firstRow(page).locator(
            ".reflection-history-actions button", { hasText: /Name it|Rename/ }
        ).click();
    };

    test.beforeEach(async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await expect(firstRow(page)).toBeVisible({ timeout: 10000 });
        // Seeded reflections may carry a name from a previous run.
        await page.evaluate(async () => {
            const res = await fetch("/api/reflection", { credentials: "same-origin" });
            const { reflections } = await res.json();
            for (const r of reflections) {
                await fetch("/api/reflection/" + r.id, {
                    method: "PATCH", credentials: "same-origin",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ title: "" }),
                });
            }
        });
        await page.reload();
        await page.waitForLoadState("networkidle");
    });

    test("unnamed rows are told apart by time, not just date", async ({ page }) => {
        // The bug: same day + same mode produced byte-identical labels.
        const labels = await page.locator(
            "#reflHistory .reflection-history-item > summary"
        ).allTextContents();
        expect(labels.length).toBeGreaterThan(1);
        labels.forEach((l) => expect(l).toMatch(/\d{2}:\d{2}/));
        expect(new Set(labels).size).toBe(labels.length);
    });

    test("naming a sitting replaces its label", async ({ page }) => {
        await firstRow(page).evaluate((el) => { el.open = true; });
        await rename(page, "DTCC week 1 plan");
        await expect(firstRow(page).locator("summary"))
            .toHaveText(/DTCC week 1 plan/, { timeout: 10000 });
        // And it survives a reload - i.e. it is on the server, not in the DOM.
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(firstRow(page).locator("summary"))
            .toHaveText(/DTCC week 1 plan/, { timeout: 10000 });
    });

    test("the control reads Rename once a name exists", async ({ page }) => {
        await firstRow(page).evaluate((el) => { el.open = true; });
        await expect(firstRow(page).locator(
            ".reflection-history-actions button", { hasText: "Name it" }
        )).toBeVisible();
        await rename(page, "Named now");
        await expect(firstRow(page).locator("summary"))
            .toHaveText(/Named now/, { timeout: 10000 });
        await firstRow(page).evaluate((el) => { el.open = true; });
        await expect(firstRow(page).locator(
            ".reflection-history-actions button", { hasText: "Rename" }
        )).toBeVisible();
    });

    test("clearing the name restores the generated label", async ({ page }) => {
        await firstRow(page).evaluate((el) => { el.open = true; });
        await rename(page, "Temporary");
        await expect(firstRow(page).locator("summary"))
            .toHaveText(/Temporary/, { timeout: 10000 });
        await firstRow(page).evaluate((el) => { el.open = true; });
        await rename(page, "   ");
        await expect(firstRow(page).locator("summary"))
            .toHaveText(/\d{4}-W\d{2}/, { timeout: 10000 });
    });

    test("cancelling the prompt changes nothing", async ({ page }) => {
        await firstRow(page).evaluate((el) => { el.open = true; });
        const before = await firstRow(page).locator("summary").textContent();
        page.once("dialog", (d) => d.dismiss());
        await firstRow(page).locator(
            ".reflection-history-actions button", { hasText: /Name it|Rename/ }
        ).click();
        await page.waitForTimeout(400);
        expect(await firstRow(page).locator("summary").textContent()).toBe(before);
    });
});

test.describe("Reflection - checkpoint without ending the session (#333)", () => {
    // Intercepts only the interim POST so the real renderReview path runs
    // for free; every other reflection request goes to the server.
    const stubInterim = async (page, explicit) => {
        await page.route("**/api/reflection/draft/analyze", async (route) => {
            await route.fulfill({
                status: 200, contentType: "application/json",
                body: JSON.stringify({
                    id: "00000000-0000-0000-0000-000000000333",
                    iso_week: "2026-W39", title: null, input_mode: "typed",
                    transcript: "Half a thought.", audio_duration_seconds: null,
                    audio_cost_usd: null, ai_cost_usd: 0.0042,
                    proposed_actions: { explicit: explicit || [], suggested: [] },
                    raw_segments: [], context_files: [],
                    is_archived: false, is_active: true, interim: true,
                }),
            });
        });
    };

    const SOMETHING = [{
        op: "create", entity: "task", target: "Draft the 30/60/90",
        reason: "You said you wanted one before day one.",
    }];

    test.beforeEach(async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.evaluate(async () => {
            await fetch("/api/reflection/draft", {
                method: "DELETE", credentials: "same-origin",
            });
        });
        await page.reload();
        await page.waitForLoadState("networkidle");
    });

    test.afterEach(async ({ page }) => {
        await page.evaluate(async () => {
            await fetch("/api/reflection/draft", {
                method: "DELETE", credentials: "same-origin",
            });
        }).catch(() => {});
    });

    test("both ways out of writing are offered, and labelled apart",
        async ({ page }) => {
            await expect(page.locator("#reflAnalyzeBtn")).toHaveText(/Finish/);
            await expect(page.locator("#reflInterimBtn")).toHaveText(/Analyze so far/);
        });

    test("a checkpoint says it is a checkpoint and offers a way back",
        async ({ page }) => {
            await stubInterim(page, SOMETHING);
            await page.locator("#reflText").fill("Half a thought.");
            await page.locator("#reflInterimBtn").click();
            await expect(page.locator("#reflStateReview")).toBeVisible({ timeout: 10000 });

            await expect(page.locator("#reflInterimNote")).toBeVisible();
            await expect(page.locator("#reflBackToWriting")).toBeVisible();
            // Start Over would wipe the box the user is still filling.
            await expect(page.locator("#reflStartOverBtn")).toBeHidden();
            await expect(page.locator("#reflApplyBtn")).toBeVisible();
        });

    test("Back to writing returns the text untouched", async ({ page }) => {
        // The fear this addresses: that analysing threw the session away.
        await stubInterim(page, SOMETHING);
        await page.locator("#reflText").fill("Hours of irreplaceable thinking.");
        await page.locator("#reflInterimBtn").click();
        await expect(page.locator("#reflStateReview")).toBeVisible({ timeout: 10000 });
        await page.locator("#reflBackToWriting").click();
        await expect(page.locator("#reflStateInput")).toBeVisible();
        await expect(page.locator("#reflText"))
            .toHaveValue("Hours of irreplaceable thinking.");
    });

    test("you can checkpoint again after adding more", async ({ page }) => {
        await stubInterim(page, SOMETHING);
        await page.locator("#reflText").fill("First hour.");
        await page.locator("#reflInterimBtn").click();
        await expect(page.locator("#reflStateReview")).toBeVisible({ timeout: 10000 });
        await page.locator("#reflBackToWriting").click();
        await page.locator("#reflText").fill("First hour. Second hour.");
        await page.locator("#reflInterimBtn").click();
        await expect(page.locator("#reflInterimNote")).toBeVisible({ timeout: 10000 });
        await page.locator("#reflBackToWriting").click();
        await expect(page.locator("#reflText")).toHaveValue("First hour. Second hour.");
    });

    test("an empty checkpoint is refused client-side", async ({ page }) => {
        page.once("dialog", (d) => d.accept());
        await page.locator("#reflInterimBtn").click();
        await expect(page.locator("#reflStateInput")).toBeVisible();
    });

    test("a final review keeps Start Over and shows no checkpoint note",
        async ({ page }) => {
            // Guards the toggle in both directions: the interim controls
            // must not leak into a finished review.
            await page.route("**/api/reflection", async (route, request) => {
                if (request.method() !== "POST") return route.continue();
                await route.fulfill({
                    status: 201, contentType: "application/json",
                    body: JSON.stringify({
                        id: "00000000-0000-0000-0000-000000000334",
                        iso_week: "2026-W39", title: null, input_mode: "typed",
                        transcript: "Done.", audio_duration_seconds: null,
                        audio_cost_usd: null, ai_cost_usd: 0.01,
                        proposed_actions: { explicit: SOMETHING, suggested: [] },
                        raw_segments: [], context_files: [],
                        is_archived: false, is_active: true,
                    }),
                });
            });
            await page.locator("#reflText").fill("Done.");
            await page.locator("#reflAnalyzeBtn").click();
            await expect(page.locator("#reflStateReview")).toBeVisible({ timeout: 10000 });
            await expect(page.locator("#reflInterimNote")).toBeHidden();
            await expect(page.locator("#reflBackToWriting")).toBeHidden();
            await expect(page.locator("#reflStartOverBtn")).toBeVisible();
        });

    test("no horizontal overflow with the checkpoint note shown", async ({ page }) => {
        await stubInterim(page, SOMETHING);
        await page.locator("#reflText").fill("Checking the layout.");
        await page.locator("#reflInterimBtn").click();
        await expect(page.locator("#reflInterimNote")).toBeVisible({ timeout: 10000 });
        const overflows = await page.evaluate(() =>
            document.documentElement.scrollWidth > window.innerWidth);
        expect(overflows).toBe(false);
    });
});

test.describe("Reflection - continuing a past reflection (#334)", () => {
    // No stubbing: continuing is a pure DB copy with no Claude or Whisper
    // call, so the real endpoint runs here and these assert real state.
    const firstRow = (page) =>
        page.locator("#reflHistory .reflection-history-item").first();

    const clearDraft = (page) => page.evaluate(async () => {
        await fetch("/api/reflection/draft", {
            method: "DELETE", credentials: "same-origin",
        });
    });

    const continueFirstRow = async (page, { accept = true } = {}) => {
        await firstRow(page).evaluate((el) => { el.open = true; });
        page.once("dialog", (d) => (accept ? d.accept() : d.dismiss()));
        await firstRow(page).locator(
            ".reflection-history-actions button", { hasText: "Continue" }
        ).click();
    };

    test.beforeEach(async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await clearDraft(page);
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(firstRow(page)).toBeVisible({ timeout: 10000 });
    });

    test.afterEach(async ({ page }) => {
        await clearDraft(page).catch(() => {});
    });

    test("every active history row offers Continue", async ({ page }) => {
        await firstRow(page).evaluate((el) => { el.open = true; });
        await expect(firstRow(page).locator(
            ".reflection-history-actions button", { hasText: "Continue" }
        )).toBeVisible();
    });

    test("it fills the box with the sitting's own words", async ({ page }) => {
        const parentText = await firstRow(page).locator(
            ".reflection-history-transcript"
        ).textContent();
        await continueFirstRow(page);
        await expect(page.locator("#reflText")).not.toHaveValue("", {
            timeout: 10000,
        });
        expect((await page.locator("#reflText").inputValue()).trim())
            .toBe(parentText.trim());
    });

    test("the banner names what is being continued and what happens next",
        async ({ page }) => {
            await continueFirstRow(page);
            const banner = page.locator("#reflContinueBanner");
            await expect(banner).toBeVisible({ timeout: 10000 });
            // Both halves matter: WHICH sitting, and that finishing writes a
            // new row rather than overwriting the one that was clicked.
            await expect(page.locator("#reflContinueText"))
                .toHaveText(/Continuing /);
            await expect(page.locator("#reflContinueText"))
                .toHaveText(/NEW reflection/);
            await expect(page.locator("#reflContinueText"))
                .toHaveText(/left exactly as it is/);
        });

    test("the writing screen is brought back into view", async ({ page }) => {
        // The button is at the BOTTOM of the page. Filling a textarea the
        // user cannot see would read as a click that did nothing.
        await continueFirstRow(page);
        await expect(page.locator("#reflText")).not.toHaveValue("", {
            timeout: 10000,
        });
        await expect(page.locator("#reflStateInput")).toBeVisible();
        const inView = await page.locator("#reflText").evaluate((el) => {
            const r = el.getBoundingClientRect();
            return r.top < window.innerHeight && r.bottom > 0;
        });
        expect(inView).toBe(true);
    });

    test("the fork is server state, not just DOM", async ({ page }) => {
        await continueFirstRow(page);
        await expect(page.locator("#reflContinueBanner")).toBeVisible({
            timeout: 10000,
        });
        const draft = await page.evaluate(async () => {
            const res = await fetch("/api/reflection/draft", {
                credentials: "same-origin",
            });
            return (await res.json()).draft;
        });
        expect(draft.continued_from_id).toBeTruthy();
        expect(draft.continued_from.id).toBe(draft.continued_from_id);

        // And it survives a reload — the banner is rebuilt from the server.
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#reflContinueBanner")).toBeVisible({
            timeout: 10000,
        });
    });

    test("a restored continuation shows ONE banner with ONE way out",
        async ({ page }) => {
            // Phase 6, 2026-09-25: on reload both banners rendered — the
            // #324 "Draft restored" one and this one — stacking two
            // destructive controls a few pixels apart ("Discard draft" and
            // "Start fresh instead") that do exactly the same thing. The
            // continuation banner subsumes the other; this is the guard.
            await continueFirstRow(page);
            await expect(page.locator("#reflContinueBanner")).toBeVisible({
                timeout: 10000,
            });
            await page.reload();
            await page.waitForLoadState("networkidle");
            await expect(page.locator("#reflContinueBanner")).toBeVisible({
                timeout: 10000,
            });
            await expect(page.locator("#reflDraftBanner")).toBeHidden();
            // `visible: true` matters: the draft banner's button stays in
            // the DOM, hidden by its parent, so a bare toHaveCount would
            // see 2 and fail even when the screen is correct.
            await expect(page.locator(
                ".reflection-continue-banner .btn-link, "
                + ".reflection-draft-banner .btn-link"
            ).filter({ visible: true })).toHaveCount(1);
            await expect(page.locator("#reflContinueAbandon")).toBeVisible();
            await expect(page.locator("#reflDraftDiscard")).toBeHidden();
            // The reassurance the draft banner used to carry is folded in,
            // not dropped.
            await expect(page.locator("#reflContinueSaved"))
                .toHaveText(/Last saved/);
        });

    test("a plain draft still gets the draft banner", async ({ page }) => {
        // Guards the toggle in the other direction: suppressing the draft
        // banner must depend on the continuation, not happen always.
        await page.locator("#reflText").fill("An ordinary sitting.");
        await page.waitForTimeout(1600);
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#reflDraftBanner")).toBeVisible({
            timeout: 10000,
        });
        await expect(page.locator("#reflContinueBanner")).toBeHidden();
    });

    test("the reflection that was continued is untouched", async ({ page }) => {
        const before = await firstRow(page).locator(
            ".reflection-history-transcript"
        ).textContent();
        const rowsBefore = await page.locator(
            "#reflHistory .reflection-history-item"
        ).count();
        await continueFirstRow(page);
        await expect(page.locator("#reflContinueBanner")).toBeVisible({
            timeout: 10000,
        });
        // Type MORE, then check the original again: the fork must not be
        // writing through to the row it came from.
        await page.locator("#reflText").fill(before + " Plus new thinking.");
        await page.waitForTimeout(1600);  // outlast the 1200ms autosave debounce
        await page.reload();
        await page.waitForLoadState("networkidle");
        expect(await page.locator("#reflHistory .reflection-history-item").count())
            .toBe(rowsBefore);
        expect((await firstRow(page).locator(
            ".reflection-history-transcript"
        ).textContent()).trim()).toBe(before.trim());
    });

    test("cancelling the confirm changes nothing", async ({ page }) => {
        await continueFirstRow(page, { accept: false });
        await page.waitForTimeout(500);
        await expect(page.locator("#reflText")).toHaveValue("");
        await expect(page.locator("#reflContinueBanner")).toBeHidden();
    });

    test("an in-progress reflection is protected, not overwritten",
        async ({ page }) => {
            // Drafts are hard-deleted with no recycle bin, and these
            // sittings run for hours — a silent clobber here is the worst
            // thing this feature could do.
            await page.locator("#reflText").fill("Two hours of thinking.");
            await page.waitForTimeout(1600);
            await firstRow(page).evaluate((el) => { el.open = true; });
            let message = "";
            page.once("dialog", (d) => { message = d.message(); d.accept(); });
            await firstRow(page).locator(
                ".reflection-history-actions button", { hasText: "Continue" }
            ).click();
            await page.waitForTimeout(500);
            expect(message).toMatch(/already have a reflection in progress/);
            // The refusal must not have taken the text with it.
            await expect(page.locator("#reflText"))
                .toHaveValue("Two hours of thinking.");
            await expect(page.locator("#reflContinueBanner")).toBeHidden();
        });

    test("Start fresh instead clears the copy and hides the banner",
        async ({ page }) => {
            await continueFirstRow(page);
            await expect(page.locator("#reflContinueBanner")).toBeVisible({
                timeout: 10000,
            });
            const rows = await page.locator(
                "#reflHistory .reflection-history-item"
            ).count();
            page.once("dialog", (d) => d.accept());
            await page.locator("#reflContinueAbandon").click();
            await expect(page.locator("#reflText")).toHaveValue("", {
                timeout: 10000,
            });
            await expect(page.locator("#reflContinueBanner")).toBeHidden();
            // It deleted the COPY. The original is still in history.
            await page.reload();
            await page.waitForLoadState("networkidle");
            expect(await page.locator(
                "#reflHistory .reflection-history-item"
            ).count()).toBe(rows);
        });

    test("a forked row shows what it grew out of", async ({ page }) => {
        // The lineage line's own rendering, driven from a history payload
        // carrying `continued_from`. The server side of this is covered by
        // tests/test_reflection_continue.py; what can only break here is
        // the helper-to-DOM wiring.
        await page.route("**/api/reflection", async (route, request) => {
            if (request.method() !== "GET") return route.continue();
            await route.fulfill({
                status: 200, contentType: "application/json",
                body: JSON.stringify({
                    reflections: [{
                        id: "00000000-0000-0000-0000-000000000334",
                        iso_week: "2026-W39", title: "Week two",
                        input_mode: "typed", transcript: "Carried on.",
                        audio_duration_seconds: null, audio_cost_usd: null,
                        ai_cost_usd: null,
                        proposed_actions: { explicit: [], suggested: [] },
                        raw_segments: [], context_files: [],
                        is_archived: false, is_active: true, is_draft: false,
                        continued_from_id:
                            "00000000-0000-0000-0000-000000000333",
                        continued_from: {
                            id: "00000000-0000-0000-0000-000000000333",
                            title: "Week one", iso_week: "2026-W38",
                            input_mode: "typed",
                            created_at: "2026-09-21T14:05:00Z",
                        },
                        applied_actions: null, applied_at: null,
                        updated_at: null,
                        created_at: "2026-09-24T09:00:00Z",
                    }],
                }),
            });
        });
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(firstRow(page).locator(".reflection-history-lineage"))
            .toHaveText("↳ continues Week one", { timeout: 10000 });
    });

    test("tap targets and layout hold with the banner shown", async ({ page }) => {
        await continueFirstRow(page);
        await expect(page.locator("#reflContinueBanner")).toBeVisible({
            timeout: 10000,
        });
        const overflows = await page.evaluate(() =>
            document.documentElement.scrollWidth > window.innerWidth);
        expect(overflows).toBe(false);

        if ((page.viewportSize() || {}).width < 700) {
            // "Start fresh instead" is a destructive control tapped
            // one-handed; .btn-link is inline and renders ~26px without the
            // mobile inline-flex rule.
            const abandon = await page.locator("#reflContinueAbandon")
                .boundingBox();
            expect(abandon.height).toBeGreaterThanOrEqual(44);
            await firstRow(page).evaluate((el) => { el.open = true; });
            const cont = await firstRow(page).locator(
                ".reflection-history-actions button", { hasText: "Continue" }
            ).boundingBox();
            expect(cont.height).toBeGreaterThanOrEqual(44);
        }
    });
});

test.describe("Reflection - reading several together (#335)", () => {
    const rows = (page) => page.locator("#reflHistory .reflection-history-item");
    const boxes = (page) => page.locator(".reflection-history-select");

    // Only the POST is stubbed: selection, the bar, the confirm and the
    // review render all run for real, and no Claude call is paid for.
    const stubCombined = async (page, extra) => {
        await page.route("**/api/reflection/analyze-together", async (route) => {
            await route.fulfill({
                status: 201, contentType: "application/json",
                body: JSON.stringify(Object.assign({
                    id: "00000000-0000-0000-0000-000000000335",
                    iso_week: "2026-W39", title: null, input_mode: "typed",
                    transcript: "Combined analysis of 2 reflections:",
                    audio_duration_seconds: null, audio_cost_usd: null,
                    ai_cost_usd: 0.031,
                    proposed_actions: {
                        explicit: [{
                            op: "create", entity: "task",
                            target: "Draft the 30/60/90",
                            reason: "It has come up in three sittings running.",
                        }],
                        suggested: [],
                    },
                    raw_segments: [], context_files: [],
                    is_archived: false, is_active: true, is_draft: false,
                    continued_from_id: null, continued_from: null,
                    synthesis_of: ["a", "b"],
                    applied_actions: null, applied_at: null, updated_at: null,
                    created_at: "2026-09-25T09:00:00Z",
                    combined: true, source_count: 2, shortened: [],
                }, extra || {})),
            });
        });
    };

    const select = async (page, n) => {
        for (let i = 0; i < n; i++) await boxes(page).nth(i).click();
    };

    test.beforeEach(async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await expect(rows(page).first()).toBeVisible({ timeout: 10000 });
    });

    test("every active row offers a select box, without expanding", async ({ page }) => {
        // Picking five reflections must not mean five expand clicks, so
        // the box lives in the summary and is visible while collapsed.
        expect(await boxes(page).count()).toBeGreaterThan(1);
        await expect(boxes(page).first()).toBeVisible();
        await expect(rows(page).first()).not.toHaveAttribute("open", /.*/);
    });

    test("ticking a box does not open the row", async ({ page }) => {
        // preventDefault on the summary cancels BOTH default actions, so
        // the tick is applied by hand — this guards that it still lands
        // AND that the disclosure stays shut.
        await boxes(page).first().click();
        await expect(boxes(page).first()).toBeChecked();
        await expect(rows(page).first()).not.toHaveAttribute("open", /.*/);
    });

    test("one selected explains what is missing instead of failing later",
        async ({ page }) => {
            await select(page, 1);
            await expect(page.locator("#reflCombineBar")).toBeVisible();
            await expect(page.locator("#reflCombineSummary"))
                .toHaveText(/pick at least one more/);
            await expect(page.locator("#reflCombineBtn")).toBeDisabled();
        });

    test("two selected enables the action and names the count", async ({ page }) => {
        await select(page, 2);
        await expect(page.locator("#reflCombineBtn")).toBeEnabled();
        await expect(page.locator("#reflCombineBtn"))
            .toHaveText("Analyze 2 together");
    });

    test("the bar is hidden until something is ticked", async ({ page }) => {
        await expect(page.locator("#reflCombineBar")).toBeHidden();
        await select(page, 1);
        await expect(page.locator("#reflCombineBar")).toBeVisible();
    });

    test("Clear drops the whole selection", async ({ page }) => {
        await select(page, 2);
        await page.locator("#reflCombineClear").click();
        await expect(page.locator("#reflCombineBar")).toBeHidden();
        await expect(boxes(page).first()).not.toBeChecked();
    });

    test("the selection survives a history re-render", async ({ page }) => {
        // Renaming a row reloads the list. A selection built over a long
        // page that silently emptied itself would be worse than one that
        // never existed.
        await select(page, 2);
        await rows(page).nth(2).evaluate((el) => { el.open = true; });
        page.once("dialog", (d) => d.accept("Renamed for the test"));
        await rows(page).nth(2).locator(
            ".reflection-history-actions button", { hasText: /Name it|Rename/ }
        ).click();
        await expect(page.locator("#reflCombineBtn"))
            .toHaveText("Analyze 2 together", { timeout: 10000 });
        await expect(boxes(page).first()).toBeChecked();
    });

    test("the review screen says how far back it read", async ({ page }) => {
        await stubCombined(page);
        await select(page, 2);
        page.once("dialog", (d) => d.accept());
        await page.locator("#reflCombineBtn").click();
        await expect(page.locator("#reflStateReview")).toBeVisible({ timeout: 10000 });
        await expect(page.locator("#reflCombinedNote")).toBeVisible();
        await expect(page.locator("#reflCombinedNote"))
            .toHaveText(/Read across 2 reflections, in full/);
        await expect(page.locator("#reflCombinedNote"))
            .toHaveText(/nothing changes until you confirm/);
        await expect(page.locator("#reflApplyBtn")).toBeVisible();
    });

    test("truncation is surfaced on the review screen", async ({ page }) => {
        // The feature's promise is full transcripts. If one was cut, the
        // user must not go on believing otherwise.
        await stubCombined(page, { shortened: ["2026-09-14 · Week one"] });
        await select(page, 2);
        page.once("dialog", (d) => d.accept());
        await page.locator("#reflCombineBtn").click();
        await expect(page.locator("#reflCombinedNote"))
            .toHaveText(/2026-09-14 · Week one/, { timeout: 10000 });
        await expect(page.locator("#reflCombinedNote")).toHaveText(/shortened/);
    });

    test("a single reflection's review shows no combined note", async ({ page }) => {
        // Guards the toggle in the other direction.
        await page.route("**/api/reflection", async (route, request) => {
            if (request.method() !== "POST") return route.continue();
            await route.fulfill({
                status: 201, contentType: "application/json",
                body: JSON.stringify({
                    id: "00000000-0000-0000-0000-000000000336",
                    iso_week: "2026-W39", title: null, input_mode: "typed",
                    transcript: "Done.", audio_duration_seconds: null,
                    audio_cost_usd: null, ai_cost_usd: 0.01,
                    proposed_actions: { explicit: [], suggested: [] },
                    raw_segments: [], context_files: [],
                    is_archived: false, is_active: true, is_draft: false,
                    synthesis_of: null,
                }),
            });
        });
        await page.locator("#reflText").fill("Done.");
        await page.locator("#reflAnalyzeBtn").click();
        await expect(page.locator("#reflStateReview")).toBeVisible({ timeout: 10000 });
        await expect(page.locator("#reflCombinedNote")).toBeHidden();
    });

    test("cancelling the confirm runs nothing", async ({ page }) => {
        let called = false;
        await page.route("**/api/reflection/analyze-together", async (route) => {
            called = true;
            await route.fulfill({ status: 201, body: "{}" });
        });
        await select(page, 2);
        page.once("dialog", (d) => d.dismiss());
        await page.locator("#reflCombineBtn").click();
        await page.waitForTimeout(600);
        expect(called).toBe(false);
        await expect(page.locator("#reflStateInput")).toBeVisible();
    });

    test("a combined row is badged in history", async ({ page }) => {
        // Without the badge a synthesis reads as a reflection in which
        // someone typed out a list of dates.
        await page.route("**/api/reflection", async (route, request) => {
            if (request.method() !== "GET") return route.continue();
            await route.fulfill({
                status: 200, contentType: "application/json",
                body: JSON.stringify({
                    reflections: [{
                        id: "00000000-0000-0000-0000-000000000335",
                        iso_week: "2026-W39", title: null, input_mode: "typed",
                        transcript: "Combined analysis of 3 reflections:",
                        audio_duration_seconds: null, audio_cost_usd: null,
                        ai_cost_usd: 0.03,
                        proposed_actions: { explicit: [], suggested: [] },
                        raw_segments: [], context_files: [],
                        is_archived: false, is_active: true, is_draft: false,
                        continued_from_id: null, continued_from: null,
                        synthesis_of: ["a", "b", "c"],
                        applied_actions: null, applied_at: null,
                        updated_at: null, created_at: "2026-09-25T09:00:00Z",
                    }],
                }),
            });
        });
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(rows(page).first().locator(".reflection-history-badge"))
            .toHaveText("🔗 Combined analysis of 3 reflections", { timeout: 10000 });
    });

    test("tap targets and layout hold with the bar shown", async ({ page }) => {
        await select(page, 2);
        await expect(page.locator("#reflCombineBar")).toBeVisible();
        const overflows = await page.evaluate(() =>
            document.documentElement.scrollWidth > window.innerWidth);
        expect(overflows).toBe(false);

        if ((page.viewportSize() || {}).width < 700) {
            // The summary is the real tap target for selecting — the box
            // itself is deliberately 18px and sits inside it.
            const sum = await rows(page).first().locator("summary").boundingBox();
            expect(sum.height).toBeGreaterThanOrEqual(44);
            const clear = await page.locator("#reflCombineClear").boundingBox();
            expect(clear.height).toBeGreaterThanOrEqual(44);
            const btn = await page.locator("#reflCombineBtn").boundingBox();
            expect(btn.height).toBeGreaterThanOrEqual(44);
        }
    });
});

test.describe("Reflection - files attached to every reflection (#336)", () => {
    const sessionItems = (page) =>
        page.locator("#reflContextList .reflection-context-item");
    const globalItems = (page) =>
        page.locator("#reflGlobalList .reflection-context-item");

    const attach = async (page, name, body) => {
        await page.locator("#reflContextInput").setInputFiles({
            name: name, mimeType: "text/plain",
            buffer: Buffer.from(body || "Reference material for the plan."),
        });
        await expect(sessionItems(page).filter({ hasText: name }))
            .toHaveCount(1, { timeout: 15000 });
    };

    const keepForever = async (page, name) => {
        await sessionItems(page).filter({ hasText: name })
            .locator("button", { hasText: "Keep for every reflection" }).click();
        await expect(globalItems(page).filter({ hasText: name }))
            .toHaveCount(1, { timeout: 15000 });
    };

    const wipe = (page) => page.evaluate(async () => {
        await fetch("/api/reflection/draft", {
            method: "DELETE", credentials: "same-origin",
        });
        const res = await fetch("/api/reflection/global-context", {
            credentials: "same-origin",
        });
        for (const f of (await res.json()).files) {
            await fetch("/api/reflection/global-context/" + f.id, {
                method: "DELETE", credentials: "same-origin",
            });
        }
    });

    test.beforeEach(async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await wipe(page);
        await page.reload();
        await page.waitForLoadState("networkidle");
    });

    test.afterEach(async ({ page }) => {
        await wipe(page).catch(() => {});
    });

    test("the always-attached section stays hidden until there is one",
        async ({ page }) => {
            // An always-empty "Attached to every reflection" heading is a
            // permanent question with no answer.
            await expect(page.locator("#reflGlobalContext")).toBeHidden();
            await attach(page, "plan.txt");
            await expect(page.locator("#reflGlobalContext")).toBeHidden();
            await keepForever(page, "plan.txt");
            await expect(page.locator("#reflGlobalContext")).toBeVisible();
        });

    test("Keep for every reflection MOVES the file", async ({ page }) => {
        // Leaving it in both lists would show the same document twice.
        await attach(page, "plan.txt");
        await expect(sessionItems(page)).toHaveCount(1);
        await keepForever(page, "plan.txt");
        await expect(sessionItems(page)).toHaveCount(0);
        await expect(globalItems(page)).toHaveCount(1);
    });

    test("an always-attached file has no Keep control of its own",
        async ({ page }) => {
            await attach(page, "plan.txt");
            await keepForever(page, "plan.txt");
            await expect(globalItems(page).first().locator(
                "button", { hasText: "Keep for every reflection" }
            )).toHaveCount(0);
            await expect(globalItems(page).first().locator(
                "button", { hasText: "Remove" }
            )).toBeVisible();
        });

    test("it is server state, surviving a reload", async ({ page }) => {
        await attach(page, "plan.txt");
        await keepForever(page, "plan.txt");
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(globalItems(page)).toHaveCount(1, { timeout: 10000 });
        await expect(page.locator("#reflGlobalContext")).toBeVisible();
    });

    test("it survives discarding the draft", async ({ page }) => {
        // The global store is not part of the draft and must not go with
        // it when the draft is thrown away.
        await attach(page, "plan.txt");
        await keepForever(page, "plan.txt");
        await page.locator("#reflText").fill("Some words.");
        await page.waitForTimeout(1600);
        // The Discard control lives on the draft banner, which only
        // appears once a draft is RESTORED — typing alone doesn't raise
        // it, so reload to get into the state the user would be in.
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#reflDraftBanner")).toBeVisible({
            timeout: 10000,
        });
        page.once("dialog", (d) => d.accept());
        await page.locator("#reflDraftDiscard").click();
        await expect(page.locator("#reflText")).toHaveValue("", { timeout: 10000 });
        await expect(globalItems(page)).toHaveCount(1);
    });

    test("the budget counter reports BOTH lists", async ({ page }) => {
        // A counter reading "1 of 5" while the server refuses the next
        // upload would be the worst of both.
        await attach(page, "plan.txt", "A".repeat(200));
        await keepForever(page, "plan.txt");
        await attach(page, "notes.txt", "B".repeat(100));
        await expect(page.locator("#reflContextSummary"))
            .toHaveText(/2 of 5 files/, { timeout: 10000 });
        await expect(page.locator("#reflContextSummary")).toHaveText(/300 of/);
    });

    test("the counter shows with an always-attached file and no draft",
        async ({ page }) => {
            // Phase 6, 2026-09-25: the two lists load independently, so
            // with a global file and no draft renderAttachments never
            // ran and the panel listed a document under a BLANK counter —
            // the one place the shared budget is supposed to be legible.
            await attach(page, "plan.txt", "A".repeat(200));
            await keepForever(page, "plan.txt");
            await page.reload();
            await page.waitForLoadState("networkidle");
            await expect(globalItems(page)).toHaveCount(1, { timeout: 10000 });
            await expect(sessionItems(page)).toHaveCount(0);
            await expect(page.locator("#reflContextSummary"))
                .toHaveText(/1 of 5 file · 200 of 60,000/);
        });

    test("removing an always-attached file asks first and updates the count",
        async ({ page }) => {
            await attach(page, "plan.txt", "A".repeat(200));
            await keepForever(page, "plan.txt");
            await expect(page.locator("#reflContextSummary"))
                .toHaveText(/1 of 5 file/, { timeout: 10000 });
            page.once("dialog", (d) => d.accept());
            await globalItems(page).first().locator(
                "button", { hasText: "Remove" }).click();
            await expect(page.locator("#reflGlobalContext"))
                .toBeHidden({ timeout: 10000 });
            await expect(page.locator("#reflContextSummary")).toHaveText("");
        });

    test("cancelling the remove keeps the file", async ({ page }) => {
        await attach(page, "plan.txt");
        await keepForever(page, "plan.txt");
        page.once("dialog", (d) => d.dismiss());
        await globalItems(page).first().locator(
            "button", { hasText: "Remove" }).click();
        await page.waitForTimeout(500);
        await expect(globalItems(page)).toHaveCount(1);
    });

    test("tap targets and layout hold with both lists shown",
        async ({ page }) => {
            await attach(page, "plan.txt");
            await keepForever(page, "plan.txt");
            await attach(page, "notes.txt");
            const overflows = await page.evaluate(() =>
                document.documentElement.scrollWidth > window.innerWidth);
            expect(overflows).toBe(false);

            if ((page.viewportSize() || {}).width < 700) {
                const keep = await sessionItems(page).first().locator(
                    "button", { hasText: "Keep for every reflection" }
                ).boundingBox();
                expect(keep.height).toBeGreaterThanOrEqual(44);
                const rm = await globalItems(page).first().locator(
                    "button", { hasText: "Remove" }).boundingBox();
                expect(rm.height).toBeGreaterThanOrEqual(44);
            }
        });
});

test.describe("Reflection - the draft keeps the last voice segment (#330)", () => {
    // Drives a REAL MediaRecorder against Chromium's fake capture device
    // (FAKE_MEDIA_ARGS in playwright.config.js) and inspects the actual
    // autosave PUT bodies. The bug was a two-line ORDERING mistake -
    // rawSegments.push() ran AFTER the flush that snapshots it - so
    // nothing short of watching the real request could catch it. Whisper
    // itself is stubbed: the assertion is about what we SEND, and a real
    // transcription would cost money and return different words each run.
    const SEG_ONE = "first spoken chunk on the phone";
    const SEG_TWO = "second spoken chunk still on the phone";

    const stubWhisper = async (page, texts) => {
        let n = 0;
        await page.route("**/api/reflection/transcribe-segment", async (route) => {
            const transcript = texts[Math.min(n, texts.length - 1)];
            n += 1;
            await route.fulfill({
                status: 200, contentType: "application/json",
                body: JSON.stringify({
                    transcript,
                    duration_seconds: 11.5,
                    cost_usd: 0.0012,
                }),
            });
        });
    };

    // Every draft PUT body, in order, as parsed JSON.
    const watchDraftPuts = (page) => {
        const puts = [];
        page.on("request", (req) => {
            if (req.method() !== "PUT") return;
            if (!req.url().includes("/api/reflection/draft")) return;
            try { puts.push(JSON.parse(req.postData() || "{}")); }
            catch (e) { puts.push({ unparseable: true }); }
        });
        return puts;
    };

    const readDraft = (page) => page.evaluate(async () => {
        const res = await fetch("/api/reflection/draft",
                                { credentials: "same-origin" });
        return (await res.json()).draft;
    });

    const segmentCount = async (page) => {
        const d = await readDraft(page);
        return d && Array.isArray(d.raw_segments) ? d.raw_segments.length : 0;
    };

    // `endState` is the panel that should be showing once the segment has
    // been transcribed: paused normally, but IDLE when the very first
    // segment came back silent (there is nothing to resume from yet).
    const recordOneSegment = async (page, startId, endState) => {
        await page.locator("#" + startId).click();
        await expect(page.locator("#reflVoiceRecording"))
            .toBeVisible({ timeout: 20000 });
        // Give the recorder real audio to hand over; a zero-length blob is
        // not the shape the upload path sees in practice.
        await page.waitForTimeout(1200);
        await page.locator("#reflPauseBtn").click();
        await expect(page.locator(endState || "#reflVoicePaused"))
            .toBeVisible({ timeout: 20000 });
    };

    test.beforeEach(async ({ page, context }) => {
        await context.grantPermissions(["microphone"]);
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.evaluate(async () => {
            await fetch("/api/reflection/draft", {
                method: "DELETE", credentials: "same-origin",
            });
        });
        // RELOAD after the delete, not before. Deleting server-side while
        // the page is already up leaves the client holding the restored
        // draft's segments in memory, and the next dictated segment lands
        // on top of them - which showed up here as three segments where
        // the test expected two. (afterEach can lose its delete to the
        // context teardown, so a leftover draft is not hypothetical.)
        await page.reload();
        await page.waitForLoadState("networkidle");
    });

    test.afterEach(async ({ page }) => {
        await page.evaluate(async () => {
            await fetch("/api/reflection/draft", {
                method: "DELETE", credentials: "same-origin",
            });
        }).catch(() => {});
    });

    test("the flush carrying a segment's TEXT carries the segment", async ({ page }) => {
        await stubWhisper(page, [SEG_ONE]);
        const puts = watchDraftPuts(page);
        await page.locator("#reflTabVoice").click();
        await recordOneSegment(page, "reflRecordBtn");

        await expect.poll(
            () => puts.filter((b) => (b.text || "").includes(SEG_ONE)).length,
            { timeout: 15000 },
        ).toBeGreaterThan(0);

        // THE assertion. Pre-fix this PUT carried the new text with the
        // PREVIOUS (empty) segment list, so the draft was one behind from
        // the very first segment.
        const carrying = puts.filter((b) => (b.text || "").includes(SEG_ONE));
        const withSeg = carrying.filter(
            (b) => Array.isArray(b.raw_segments) && b.raw_segments.length >= 1);
        expect(withSeg.length).toBeGreaterThan(0);
        expect(withSeg[0].raw_segments[0].text).toBe(SEG_ONE);
        // The costed telemetry is the point of the trail, not just words.
        expect(withSeg[0].raw_segments[0].cost_usd).toBe(0.0012);
        expect(withSeg[0].raw_segments[0].duration_seconds).toBe(11.5);
    });

    test("the SERVER ends up holding both segments", async ({ page }) => {
        // What the second device actually reads. The PUT assertion above
        // could pass while the server still disagreed.
        await stubWhisper(page, [SEG_ONE, SEG_TWO]);
        await page.locator("#reflTabVoice").click();
        await recordOneSegment(page, "reflRecordBtn");
        await recordOneSegment(page, "reflResumeBtn");

        await expect.poll(() => segmentCount(page), { timeout: 20000 }).toBe(2);

        const draft = await readDraft(page);
        expect(draft.raw_segments.map((s) => s.text))
            .toEqual([SEG_ONE, SEG_TWO]);
        // And it is filed as voice-captured, so the resumed sitting reads
        // as what it was.
        expect(draft.input_mode).toBe("voice");
    });

    test("editing the dictated text does not erase the segments", async ({ page }) => {
        // The server half of #330: save_draft used to assign raw_segments
        // unconditionally, so a text-only autosave wiped the whole trail.
        await stubWhisper(page, [SEG_ONE]);
        await page.locator("#reflTabVoice").click();
        await recordOneSegment(page, "reflRecordBtn");
        await expect.poll(() => segmentCount(page), { timeout: 15000 }).toBe(1);

        // A text-only PUT, exactly what a second device sends when its
        // restore bailed because something was already in the box.
        await page.evaluate(async () => {
            await fetch("/api/reflection/draft", {
                method: "PUT", credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text: "tidied up on the laptop" }),
            });
        });
        const draft = await readDraft(page);
        expect(draft.transcript).toBe("tidied up on the laptop");
        expect(draft.raw_segments.map((s) => s.text)).toEqual([SEG_ONE]);
    });

    test("a silent segment adds nothing to the trail", async ({ page }) => {
        // Whisper heard no words. The push must not run either, or the
        // draft grows a segment with empty text and a real cost attached.
        await stubWhisper(page, [""]);
        await page.locator("#reflTabVoice").click();
        // Back to IDLE, not paused: with no words yet there is nothing to
        // resume from, so the page offers Start again.
        await recordOneSegment(page, "reflRecordBtn", "#reflVoiceIdle");
        await expect(page.locator("#reflVoiceStatus"))
            .toContainText("silent", { timeout: 15000 });
        expect(await segmentCount(page)).toBe(0);
    });
});

test.describe("Reflection - a submitted reflection never comes back as a draft (#341)", () => {
    // The 2026-09-24 evidence: a submitted 4445-char row at 20:17:27 and a
    // LIVE draft holding the same 4445 characters created at 20:19:41, two
    // minutes later. clearDraftUi() set lastSavedText = null while the text
    // was still sitting in the (hidden) textarea, so
    // shouldAutosaveDraft(null, text) returned true and the next autosave
    // trigger PUT it straight back. No typing required - a plain
    // visibilitychange is enough, which is why locking a phone did it.
    //
    // That resurrected draft is what then invited a second submit, and a
    // second submit is a second PAID Claude call.
    const TEXT = "A reflection that must not come back as a draft after it is submitted.";

    const stubAnalyze = async (page) => {
        await page.route("**/api/reflection", async (route, request) => {
            if (request.method() !== "POST") return route.continue();
            // Mimic the real route, which retires the draft right after
            // persisting and BEFORE calling Claude. Stubbing the POST
            // without this would leave the draft on the server and the
            // test would be asserting against a state the app never
            // reaches.
            await page.request.delete("/api/reflection/draft");
            await route.fulfill({
                status: 201, contentType: "application/json",
                body: JSON.stringify({
                    id: "00000000-0000-0000-0000-000000000341",
                    iso_week: "2026-W39", title: null, input_mode: "typed",
                    transcript: TEXT, audio_duration_seconds: null,
                    audio_cost_usd: null, ai_cost_usd: 0.0193,
                    proposed_actions: { explicit: [], suggested: [] },
                    raw_segments: [], context_files: [],
                    is_archived: false, is_active: true,
                    created_at: "2026-09-25T18:00:00+00:00",
                }),
            });
        });
    };

    const readDraft = (page) => page.evaluate(async () => {
        const res = await fetch("/api/reflection/draft",
                                { credentials: "same-origin" });
        return (await res.json()).draft;
    });

    const hide = (page) => page.evaluate(async () => {
        // The real trigger: the page going hidden. Patched rather than
        // faked with a direct call, so the actual listener runs.
        Object.defineProperty(document, "visibilityState",
                              { value: "hidden", configurable: true });
        document.dispatchEvent(new Event("visibilitychange"));
        await new Promise((r) => setTimeout(r, 600));
    });

    test.beforeEach(async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.evaluate(async () => {
            await fetch("/api/reflection/draft", {
                method: "DELETE", credentials: "same-origin",
            });
        });
        await page.reload();
        await page.waitForLoadState("networkidle");
    });

    test.afterEach(async ({ page }) => {
        await page.evaluate(async () => {
            await fetch("/api/reflection/draft", {
                method: "DELETE", credentials: "same-origin",
            });
        }).catch(() => {});
    });

    test("hiding the tab after a submit does not recreate the draft", async ({ page }) => {
        await stubAnalyze(page);
        await page.locator("#reflText").fill(TEXT);
        // Let the autosave create a real draft first, so this test proves
        // the draft is GONE rather than never having existed.
        await expect.poll(() => readDraft(page), { timeout: 10000 })
            .not.toBeNull();

        await page.locator("#reflAnalyzeBtn").click();
        await expect(page.locator("#reflStateReview")).toBeVisible({ timeout: 15000 });
        expect(await readDraft(page)).toBeNull();

        // THE regression. Pre-fix this PUT the submitted text straight back.
        await hide(page);
        expect(await readDraft(page)).toBeNull();
    });

    test("typing again after a submit DOES start a new draft", async ({ page }) => {
        // The other half of the rule: the block must lift for real work,
        // or discarding a draft and typing something new would never save.
        await stubAnalyze(page);
        await page.locator("#reflText").fill(TEXT);
        await page.locator("#reflAnalyzeBtn").click();
        await expect(page.locator("#reflStateReview")).toBeVisible({ timeout: 15000 });
        expect(await readDraft(page)).toBeNull();

        await page.locator("#reflStartOverBtn").click();
        await page.locator("#reflText").fill("A genuinely new thought.");
        await expect.poll(async () => {
            const d = await readDraft(page);
            return d ? d.transcript : null;
        }, { timeout: 10000 }).toBe("A genuinely new thought.");
    });

    test("discarding a draft then typing still autosaves", async ({ page }) => {
        // clearDraftUi() also runs on Discard, and that path must not be
        // left unable to save ever again.
        await page.locator("#reflText").fill(TEXT);
        await expect.poll(() => readDraft(page), { timeout: 10000 })
            .not.toBeNull();
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#reflText")).toHaveValue(TEXT, { timeout: 10000 });
        page.once("dialog", (d) => d.accept());
        await page.locator("#reflDraftDiscard").click();
        await expect.poll(() => readDraft(page), { timeout: 10000 }).toBeNull();

        await page.locator("#reflText").fill("Something else entirely.");
        await expect.poll(async () => {
            const d = await readDraft(page);
            return d ? d.transcript : null;
        }, { timeout: 10000 }).toBe("Something else entirely.");
    });

    test("the submit button is disabled while a submit is in flight", async ({ page }) => {
        // Every click is a paid Claude call. The #333 interim button already
        // guarded itself; the two submit buttons did not.
        let posts = 0;
        await page.route("**/api/reflection", async (route, request) => {
            if (request.method() !== "POST") return route.continue();
            posts += 1;
            await new Promise((r) => setTimeout(r, 1500));
            await route.fulfill({
                status: 201, contentType: "application/json",
                body: JSON.stringify({
                    id: "00000000-0000-0000-0000-000000000341",
                    iso_week: "2026-W39", title: null, input_mode: "typed",
                    transcript: TEXT, audio_duration_seconds: null,
                    audio_cost_usd: null, ai_cost_usd: 0.0193,
                    proposed_actions: { explicit: [], suggested: [] },
                    raw_segments: [], context_files: [],
                    is_archived: false, is_active: true,
                    created_at: "2026-09-25T18:00:00+00:00",
                }),
            });
        });
        await page.locator("#reflText").fill(TEXT);
        const btn = page.locator("#reflAnalyzeBtn");
        await btn.click();
        await expect(btn).toBeDisabled({ timeout: 5000 });
        // Force the button back on and click anyway. The `disabled`
        // attribute is the visible affordance; the in-flight FLAG is the
        // actual guard, and only this proves the flag is doing the work.
        await page.evaluate(() => {
            const b = document.getElementById("reflAnalyzeBtn");
            b.disabled = false;
            b.click();
            b.click();
        });
        await page.waitForTimeout(2500);
        expect(posts).toBe(1);
    });
});

test.describe("Calendar - 2 / 4 / 8-week outlook (#345)", () => {
    const cells = (page) => page.locator(".calendar-cell");
    const rangeBtn = (page, n) =>
        page.locator(`.calendar-range-btn[data-weeks="${n}"]`);

    const clearStoredRange = (page) => page.evaluate(() => {
        try { window.localStorage.removeItem("calendarWeeks"); } catch (e) { /* blocked */ }
    });

    test.beforeEach(async ({ page }) => {
        await page.goto("/calendar?nosw=1");
        await page.waitForLoadState("networkidle");
        await clearStoredRange(page);
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(cells(page).first()).toBeVisible({ timeout: 10000 });
    });

    test("defaults to 2 weeks - 14 cells, as before #345", async ({ page }) => {
        // The pre-existing behaviour. An existing user must not find
        // their calendar silently three times longer after a deploy.
        await expect(cells(page)).toHaveCount(14);
        await expect(rangeBtn(page, 2)).toHaveAttribute("aria-pressed", "true");
    });

    test("4 weeks renders 28 cells, 8 weeks renders 56", async ({ page }) => {
        await rangeBtn(page, 4).click();
        await expect(cells(page)).toHaveCount(28, { timeout: 10000 });
        await rangeBtn(page, 8).click();
        await expect(cells(page)).toHaveCount(56, { timeout: 10000 });
        await rangeBtn(page, 2).click();
        await expect(cells(page)).toHaveCount(14, { timeout: 10000 });
    });

    test("every rendered day is distinct and contiguous", async ({ page }) => {
        // Guards the loop arithmetic: an off-by-one in the offset would
        // repeat or skip a day, which on a 56-cell grid is easy to miss
        // by eye. (#219 shipped a real double-render bug of this shape.)
        await rangeBtn(page, 8).click();
        await expect(cells(page)).toHaveCount(56, { timeout: 10000 });
        const dates = await cells(page).evaluateAll(
            (els) => els.map((e) => e.dataset.date));
        expect(new Set(dates).size).toBe(56);
        for (let i = 1; i < dates.length; i++) {
            const prev = new Date(dates[i - 1] + "T00:00:00Z").getTime();
            const cur = new Date(dates[i] + "T00:00:00Z").getTime();
            expect(cur - prev).toBe(86400000);
        }
        // Mon-Sun rows: the first cell is a Monday, the last a Sunday.
        expect(new Date(dates[0] + "T00:00:00Z").getUTCDay()).toBe(1);
        expect(new Date(dates[55] + "T00:00:00Z").getUTCDay()).toBe(0);
    });

    test("the choice survives a reload", async ({ page }) => {
        // An outlook you have to re-pick every visit is not an outlook.
        await rangeBtn(page, 8).click();
        await expect(cells(page)).toHaveCount(56, { timeout: 10000 });
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(cells(page)).toHaveCount(56, { timeout: 10000 });
        await expect(rangeBtn(page, 8)).toHaveAttribute("aria-pressed", "true");
    });

    test("a junk stored value falls back instead of breaking the grid", async ({ page }) => {
        await page.evaluate(() => {
            window.localStorage.setItem("calendarWeeks", "lots");
        });
        await page.reload();
        await page.waitForLoadState("networkidle");
        await expect(cells(page)).toHaveCount(14, { timeout: 10000 });
    });

    test("the recurring-previews fetch widens with the grid", async ({ page }) => {
        // The failure this prevents: real tasks show in week 6 but the
        // recurring ones silently do not, so a busy week reads as empty.
        const windows = [];
        const statuses = [];
        await page.route("**/api/recurring/previews**", async (route, request) => {
            const u = new URL(request.url());
            windows.push({ start: u.searchParams.get("start"),
                           end: u.searchParams.get("end") });
            const res = await route.fetch();
            statuses.push(res.status());
            await route.fulfill({ response: res });
        });
        await rangeBtn(page, 8).click();
        await expect(cells(page)).toHaveCount(56, { timeout: 10000 });
        const last = windows[windows.length - 1];
        expect(last).toBeTruthy();
        const span = (new Date(last.end + "T00:00:00Z")
                      - new Date(last.start + "T00:00:00Z")) / 86400000;
        expect(span).toBe(55);   // inclusive: 56 days

        // And it must actually SUCCEED. The first version of this test
        // checked only that the URL widened, which it did -- while the
        // server 400'd the request ("range cannot exceed 31 days") and
        // the 8-week grid showed every real task with every recurring
        // preview silently missing. Asserting the shape of a request is
        // not asserting the feature works.
        expect(statuses.length).toBeGreaterThan(0);
        expect(statuses.every((c) => c === 200)).toBe(true);
    });

    test("a task dropped on a week-7 cell actually lands on that date", async ({
        page, request,
    }) => {
        // The real risk in #345: the drop handlers are attached per cell
        // inside the render loop, so a cell that only exists because the
        // grid got longer must reschedule exactly like a week-1 cell.
        // Asserting the persisted due_date is the only way to know the
        // handler ran — a click affordance proves nothing about the drop.
        const created = await request.post("/api/tasks", {
            data: { title: `E2E outlook DnD ${Date.now()}`, type: "work",
                    tier: "inbox" },
        });
        expect(created.ok()).toBe(true);
        const task = await created.json();

        try {
            await rangeBtn(page, 8).click();
            await expect(cells(page)).toHaveCount(56, { timeout: 10000 });

            // Cell 50 is in week 8 — unreachable before this feature.
            const farDate = await cells(page).nth(50).getAttribute("data-date");
            expect(farDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);

            const li = page.locator(
                `#calendarUnscheduled li[data-task-id="${task.id}"]`);
            await expect(li).toBeVisible({ timeout: 10000 });

            // Same programmatic DataTransfer dance the #267 cross-cell test
            // uses — page.dragAndDrop doesn't fire this app's dragstart.
            await page.evaluate((args) => {
                const src = document.querySelector(
                    `#calendarUnscheduled li[data-task-id="${args.tid}"]`);
                const cell = document.querySelector(
                    `.calendar-cell[data-date="${args.farDate}"]`);
                const dt = new DataTransfer();
                dt.setData("text/plain", args.tid);
                src.dispatchEvent(new DragEvent("dragstart",
                    { dataTransfer: dt, bubbles: true }));
                cell.dispatchEvent(new DragEvent("dragover",
                    { dataTransfer: dt, bubbles: true, cancelable: true }));
                cell.dispatchEvent(new DragEvent("drop",
                    { dataTransfer: dt, bubbles: true, cancelable: true }));
            }, { tid: task.id, farDate });

            await expect.poll(async () => {
                const r = await request.get(`/api/tasks/${task.id}`);
                return (await r.json()).due_date;
            }, { timeout: 10000 }).toBe(farDate);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("the switch clears the tap floor and does not overflow", async ({ page }) => {
        for (const n of [2, 4, 8]) {
            const box = await rangeBtn(page, n).boundingBox();
            expect(box.height).toBeGreaterThanOrEqual(44);
        }
        await rangeBtn(page, 8).click();
        await expect(cells(page)).toHaveCount(56, { timeout: 10000 });
        const overflows = await page.evaluate(() =>
            document.documentElement.scrollWidth > window.innerWidth);
        expect(overflows).toBe(false);
    });
});

test.describe("Projects - drag a task to another project (#344)", () => {
    // Every test here asserts the PERSISTED project_id, never just that a
    // handler fired or a class appeared. #347 was filed the day before
    // this was written precisely because a test that watched the shape of
    // a request passed while the request was failing.

    const taskLi = (page, id) =>
        page.locator(`.project-card-task[data-task-id="${id}"]`);
    const card = (page, id) =>
        page.locator(`.project-card[data-project-id="${id}"]`);

    // Drag via a real DataTransfer: page.dragAndDrop does not fire this
    // app's dragstart listener style (same note as the #267 calendar test).
    const dragTaskToCard = (page, taskId, projectId) =>
        page.evaluate(({ t, p }) => {
            const li = document.querySelector(
                `.project-card-task[data-task-id="${t}"]`);
            const dest = document.querySelector(
                `.project-card[data-project-id="${p}"]`);
            const dt = new DataTransfer();
            li.dispatchEvent(new DragEvent("dragstart",
                { dataTransfer: dt, bubbles: true }));
            dest.dispatchEvent(new DragEvent("dragover",
                { dataTransfer: dt, bubbles: true, cancelable: true }));
            const marked = {
                ok: dest.classList.contains("project-card-drop-ok"),
                no: dest.classList.contains("project-card-drop-no"),
            };
            dest.dispatchEvent(new DragEvent("drop",
                { dataTransfer: dt, bubbles: true, cancelable: true }));
            return marked;
        }, { t: taskId, p: projectId });

    async function projectsByType(request) {
        const r = await request.get("/api/projects?is_active=all");
        const all = await r.json();
        const active = all.filter((p) => p.is_active);
        return {
            work: active.filter((p) => p.type === "work"),
            personal: active.filter((p) => p.type === "personal"),
        };
    }

    test("a task dropped on another project card actually moves", async ({
        page, request,
    }) => {
        const { work } = await projectsByType(request);
        expect(work.length).toBeGreaterThanOrEqual(2);
        const [from, to] = work;

        const created = await request.post("/api/tasks", {
            data: { title: `E2E move ${Date.now()}`, type: "work",
                    tier: "inbox", project_id: from.id },
        });
        expect(created.ok()).toBe(true);
        const task = await created.json();

        try {
            await page.goto("/projects?nosw=1");
            await page.waitForLoadState("networkidle");
            await expect(taskLi(page, task.id)).toHaveCount(1, { timeout: 10000 });

            const marks = await dragTaskToCard(page, task.id, to.id);
            expect(marks.ok).toBe(true);        // the card advertised the drop
            expect(marks.no).toBe(false);

            await expect.poll(async () => {
                const r = await request.get(`/api/tasks/${task.id}`);
                return (await r.json()).project_id;
            }, { timeout: 10000 }).toBe(to.id);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("a work task is REFUSED by a personal project, and says why", async ({
        page, request,
    }) => {
        // The task detail panel only ever offers same-type projects
        // (app.js taskDetailPopulateProjects). Drag is a second door onto
        // the same field; if it did not honour the same rule it would be
        // the hole the picker closed. A silent refusal reads as "drag is
        // broken", so the message is part of the contract.
        const { work, personal } = await projectsByType(request);
        expect(work.length).toBeGreaterThanOrEqual(1);
        expect(personal.length).toBeGreaterThanOrEqual(1);

        const created = await request.post("/api/tasks", {
            data: { title: `E2E refuse ${Date.now()}`, type: "work",
                    tier: "inbox", project_id: work[0].id },
        });
        const task = await created.json();

        try {
            await page.goto("/projects?nosw=1");
            await page.waitForLoadState("networkidle");
            await expect(taskLi(page, task.id)).toHaveCount(1, { timeout: 10000 });

            const marks = await dragTaskToCard(page, task.id, personal[0].id);
            expect(marks.no).toBe(true);
            expect(marks.ok).toBe(false);

            const status = page.locator("#projectsDragStatus");
            await expect(status).toBeVisible();
            await expect(status).toContainText(/can only go on/i);
            await expect(status).toContainText(personal[0].name);

            // And nothing moved. Waiting first so a late PATCH would lose.
            await page.waitForTimeout(700);
            const after = await (await request.get(`/api/tasks/${task.id}`)).json();
            expect(after.project_id).toBe(work[0].id);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("the drop does NOT also fire the #275 project reorder", async ({
        page, request,
    }) => {
        // The card sits inside the reorder drop-list. Without
        // stopPropagation the task drop bubbles into onListDrop, which
        // POSTs /api/projects/reorder built from the unchanged DOM order —
        // a pointless write plus a re-render racing ours.
        const { work } = await projectsByType(request);
        const [from, to] = work;
        const created = await request.post("/api/tasks", {
            data: { title: `E2E norerender ${Date.now()}`, type: "work",
                    tier: "inbox", project_id: from.id },
        });
        const task = await created.json();

        try {
            await page.goto("/projects?nosw=1");
            await page.waitForLoadState("networkidle");
            await expect(taskLi(page, task.id)).toHaveCount(1, { timeout: 10000 });

            const reorders = [];
            page.on("request", (r) => {
                if (r.url().includes("/api/projects/reorder")) reorders.push(r.url());
            });

            await dragTaskToCard(page, task.id, to.id);
            await expect.poll(async () => {
                const r = await request.get(`/api/tasks/${task.id}`);
                return (await r.json()).project_id;
            }, { timeout: 10000 }).toBe(to.id);

            expect(reorders).toEqual([]);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("dragging a task does not hijack the card's own reorder drag", async ({
        page, request,
    }) => {
        // The task <li> lives inside a draggable card. Without
        // stopPropagation on the li's dragstart, onCardDragStart also runs
        // and the board believes you are reordering PROJECTS.
        const { work } = await projectsByType(request);
        const created = await request.post("/api/tasks", {
            data: { title: `E2E hijack ${Date.now()}`, type: "work",
                    tier: "inbox", project_id: work[0].id },
        });
        const task = await created.json();

        try {
            await page.goto("/projects?nosw=1");
            await page.waitForLoadState("networkidle");
            await expect(taskLi(page, task.id)).toHaveCount(1, { timeout: 10000 });

            const state = await page.evaluate((t) => {
                const li = document.querySelector(
                    `.project-card-task[data-task-id="${t}"]`);
                const parentCard = li.closest(".project-card");
                const dt = new DataTransfer();
                li.dispatchEvent(new DragEvent("dragstart",
                    { dataTransfer: dt, bubbles: true }));
                const out = {
                    liDragging: li.classList.contains("dragging"),
                    cardDragging: parentCard.classList.contains("dragging"),
                };
                li.dispatchEvent(new DragEvent("dragend",
                    { dataTransfer: dt, bubbles: true }));
                return out;
            }, task.id);

            expect(state.liDragging).toBe(true);
            expect(state.cardDragging).toBe(false);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("a card with collapsed tasks still accepts a drop", async ({
        page, request,
    }) => {
        // The user's decision: "dropping onto a COLLAPSED card still moves
        // the item, so you never have to expand just to drag." The drop
        // target is the whole card, so this holds — pinned here because it
        // would be easy to later move the handler onto the task list and
        // silently break it.
        const { work } = await projectsByType(request);
        const [from, to] = work;

        // Push the destination past the inline limit so it renders the
        // "Show all (N)" collapse.
        const filler = [];
        for (let i = 0; i < 6; i++) {
            const r = await request.post("/api/tasks", {
                data: { title: `E2E filler ${i} ${Date.now()}`, type: "work",
                        tier: "inbox", project_id: to.id },
            });
            filler.push((await r.json()).id);
        }
        const created = await request.post("/api/tasks", {
            data: { title: `E2E collapsed ${Date.now()}`, type: "work",
                    tier: "inbox", project_id: from.id },
        });
        const task = await created.json();

        try {
            await page.goto("/projects?nosw=1");
            await page.waitForLoadState("networkidle");
            await expect(taskLi(page, task.id)).toHaveCount(1, { timeout: 10000 });

            // The destination really is collapsed: some of its task lines
            // are hidden and a toggle is offered.
            const hidden = await card(page, to.id).evaluate((el) =>
                [...el.querySelectorAll(".project-card-task")]
                    .filter((li) => getComputedStyle(li).display === "none").length);
            expect(hidden).toBeGreaterThan(0);
            await expect(card(page, to.id).locator(".project-card-toggle"))
                .toBeVisible();

            // Drop WITHOUT expanding it.
            await dragTaskToCard(page, task.id, to.id);
            await expect.poll(async () => {
                const r = await request.get(`/api/tasks/${task.id}`);
                return (await r.json()).project_id;
            }, { timeout: 10000 }).toBe(to.id);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
            for (const id of filler) await request.delete(`/api/tasks/${id}`);
        }
    });

    test("the task line advertises that it can be dragged", async ({ page }) => {
        // Discoverability, not just function: before #344 these lines
        // looked like static labels, so nothing suggested dragging them.
        await page.goto("/projects?nosw=1");
        await page.waitForLoadState("networkidle");
        const li = page.locator('.project-card-task[draggable="true"]').first();
        await expect(li).toBeVisible({ timeout: 10000 });
        const look = await li.evaluate((el) => ({
            cursor: getComputedStyle(el).cursor,
            grip: getComputedStyle(el, "::before").content,
        }));
        expect(look.cursor).toBe("grab");
        expect(look.grip).toContain("⠿");   // the braille grip glyph
    });

    // --- the touch path -----------------------------------------------------
    // HTML5 drag-and-drop does not fire from a finger, so /projects has a
    // separate long-press path. Without these, the feature could be green
    // on desktop and simply absent on the phone — which is where a lot of
    // this board actually gets used.

    test("long-press then drag moves the task on touch", async ({
        page, request,
    }) => {
        const { work } = await projectsByType(request);
        const [from, to] = work;
        const created = await request.post("/api/tasks", {
            data: { title: `E2E touch ${Date.now()}`, type: "work",
                    tier: "inbox", project_id: from.id },
        });
        const task = await created.json();

        try {
            await page.goto("/projects?nosw=1");
            await page.waitForLoadState("networkidle");
            await expect(taskLi(page, task.id)).toHaveCount(1, { timeout: 10000 });

            const started = await page.evaluate(async ({ t, p }) => {
                const fire = (el, type, x, y, released) => {
                    const touch = new Touch({
                        identifier: 1, target: el, clientX: x, clientY: y,
                    });
                    el.dispatchEvent(new TouchEvent(type, {
                        bubbles: true, cancelable: true,
                        touches: released ? [] : [touch],
                        targetTouches: released ? [] : [touch],
                        changedTouches: [touch],
                    }));
                };
                const li = document.querySelector(
                    `.project-card-task[data-task-id="${t}"]`);
                const dest = document.querySelector(
                    `.project-card[data-project-id="${p}"]`);
                dest.scrollIntoView({ block: "center" });
                await new Promise((r) => setTimeout(r, 200));
                const r0 = li.getBoundingClientRect();
                fire(li, "touchstart", r0.left + 20, r0.top + 10, false);
                await new Promise((r) => setTimeout(r, 650));  // past the 500ms hold
                const dragging = li.classList.contains("dragging");
                const rd = dest.getBoundingClientRect();
                const cx = rd.left + rd.width / 2;
                const cy = rd.top + rd.height / 2;
                fire(document, "touchmove", cx, cy, false);
                const marked = dest.classList.contains("project-card-drop-ok");
                fire(document, "touchend", cx, cy, true);
                return { dragging, marked };
            }, { t: task.id, p: to.id });

            expect(started.dragging).toBe(true);
            expect(started.marked).toBe(true);

            await expect.poll(async () => {
                const r = await request.get(`/api/tasks/${task.id}`);
                return (await r.json()).project_id;
            }, { timeout: 10000 }).toBe(to.id);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("a tap and a scroll are not drags", async ({ page }) => {
        // The two ways the touch path could ruin ordinary phone use:
        // tapping a task line, and scrolling the board with a finger that
        // happens to start on one.
        await page.goto("/projects?nosw=1");
        await page.waitForLoadState("networkidle");
        await expect(page.locator('.project-card-task[draggable="true"]').first())
            .toBeVisible({ timeout: 10000 });

        const out = await page.evaluate(async () => {
            const fire = (el, type, x, y, released) => {
                const touch = new Touch({
                    identifier: 1, target: el, clientX: x, clientY: y,
                });
                el.dispatchEvent(new TouchEvent(type, {
                    bubbles: true, cancelable: true,
                    touches: released ? [] : [touch],
                    targetTouches: released ? [] : [touch],
                    changedTouches: [touch],
                }));
            };
            const li = document.querySelector(".project-card-task[data-task-id]");
            const r = li.getBoundingClientRect();
            const x = r.left + 20;
            const y = r.top + 10;

            // A quick tap, released well inside the hold window.
            fire(li, "touchstart", x, y, false);
            await new Promise((s) => setTimeout(s, 120));
            fire(document, "touchend", x, y, true);
            await new Promise((s) => setTimeout(s, 600));
            const afterTap = li.classList.contains("dragging");

            // A scroll: moved far enough, soon enough, to be a scroll.
            fire(li, "touchstart", x, y, false);
            await new Promise((s) => setTimeout(s, 100));
            fire(document, "touchmove", x, y + 40, false);
            await new Promise((s) => setTimeout(s, 600));
            const afterScroll = li.classList.contains("dragging");
            fire(document, "touchend", x, y + 40, true);

            // A few px of drift during the hold is still a hold — a
            // zero-tolerance cancel would make the gesture unusable.
            fire(li, "touchstart", x, y, false);
            await new Promise((s) => setTimeout(s, 100));
            fire(document, "touchmove", x + 3, y + 4, false);
            await new Promise((s) => setTimeout(s, 600));
            const afterJitter = li.classList.contains("dragging");
            fire(document, "touchend", x + 3, y + 4, true);
            await new Promise((s) => setTimeout(s, 200));

            return { afterTap, afterScroll, afterJitter };
        });

        expect(out.afterTap).toBe(false);
        expect(out.afterScroll).toBe(false);
        expect(out.afterJitter).toBe(true);
    });
});

test.describe("Goals - drag a project to another goal (#343)", () => {
    // Every test asserts the PERSISTED goal_id, never that a handler fired
    // or a class appeared. #347 exists because a test that watched the
    // shape of a request passed while the request was failing.
    //
    // Test projects are created and soft-deleted (DELETE /api/projects is
    // an archive, not a purge). Archived projects do not render on /goals
    // — goals.js fetches active only — so they cannot leak into a later
    // run's fixtures.

    const chip = (page, id) =>
        page.locator(`.goal-card-project[data-project-id="${id}"]`);
    const goalCard = (page, id) =>
        page.locator(`.goal-card[data-goal-id="${id}"]`);
    const zone = (page) => page.locator(".goals-unassigned-zone");

    async function activeGoals(request) {
        const r = await request.get("/api/goals");
        return (await r.json()).filter((g) => g.is_active);
    }

    async function makeProject(request, goalId) {
        const r = await request.post("/api/projects", {
            data: {
                name: `E2E drag ${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
                type: "work",
                goal_id: goalId,
            },
        });
        expect(r.ok()).toBe(true);
        return await r.json();
    }

    const goalIdOf = async (request, projectId) =>
        (await (await request.get(`/api/projects/${projectId}`)).json()).goal_id;

    // Open every collapsed project list. The lists start collapsed by
    // design, so a test that wants to GRAB a chip has to expand first —
    // dropping onto a collapsed card is a separate test below.
    async function expandAll(page) {
        await page.evaluate(() => {
            document.querySelectorAll(".goal-card-projects-toggle").forEach((t) => {
                if (t.getAttribute("aria-expanded") === "false") t.click();
            });
        });
    }

    // Drag via a real DataTransfer: page.dragAndDrop does not fire this
    // app's dragstart listener style (same note as the #344/#267 tests).
    // `destSelector` is the card OR the no-goal zone.
    const dragProjectTo = (page, projectId, destSelector) =>
        page.evaluate(({ p, sel }) => {
            const li = document.querySelector(
                `.goal-card-project[data-project-id="${p}"]`);
            const dest = document.querySelector(sel);
            const dt = new DataTransfer();
            li.dispatchEvent(new DragEvent("dragstart",
                { dataTransfer: dt, bubbles: true }));
            const over = new DragEvent("dragover",
                { dataTransfer: dt, bubbles: true, cancelable: true });
            dest.dispatchEvent(over);
            const marked = {
                ok: dest.classList.contains("goal-card-drop-ok"),
                no: dest.classList.contains("goal-card-drop-no"),
                accepted: over.defaultPrevented,
            };
            dest.dispatchEvent(new DragEvent("drop",
                { dataTransfer: dt, bubbles: true, cancelable: true }));
            return marked;
        }, { p: projectId, sel: destSelector });

    test("a project dropped on another goal card actually moves", async ({
        page, request,
    }) => {
        const goals = await activeGoals(request);
        expect(goals.length).toBeGreaterThanOrEqual(2);
        const [from, to] = goals;
        const project = await makeProject(request, from.id);

        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await expandAll(page);
            await expect(chip(page, project.id)).toHaveCount(1, { timeout: 10000 });

            const marks = await dragProjectTo(
                page, project.id, `.goal-card[data-goal-id="${to.id}"]`);
            expect(marks.ok).toBe(true);        // the card advertised the drop
            expect(marks.no).toBe(false);
            expect(marks.accepted).toBe(true);

            await expect.poll(() => goalIdOf(request, project.id),
                              { timeout: 10000 }).toBe(to.id);
        } finally {
            await request.delete(`/api/projects/${project.id}`);
        }
    });

    test("a COLLAPSED goal card still accepts a drop", async ({
        page, request,
    }) => {
        // The recorded decision: "collapsed by default showing a count,
        // click to expand; dropping onto a COLLAPSED card still moves the
        // item, so you never have to expand just to drag." The drop target
        // is the whole card, which is what makes that true — pinned here
        // because moving the handler onto the project list would silently
        // break it and look like a styling change.
        const goals = await activeGoals(request);
        const [from, to] = goals;
        const project = await makeProject(request, from.id);
        // Give the destination a project of its own so it renders a
        // collapsible list rather than the "No projects linked" branch.
        const sibling = await makeProject(request, to.id);

        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            // Expand ONLY the source card; the destination stays shut.
            await page.locator(`.goal-card[data-goal-id="${from.id}"] `
                               + `.goal-card-projects-toggle`).click();
            await expect(chip(page, project.id)).toBeVisible({ timeout: 10000 });

            // The destination really is collapsed.
            const destState = await goalCard(page, to.id).evaluate((el) => ({
                hidden: el.querySelector(".goal-card-project-list").hidden,
                visibleChips: [...el.querySelectorAll(".goal-card-project")]
                    .filter((c) => c.offsetParent !== null).length,
                expanded: el.querySelector(".goal-card-projects-toggle")
                    .getAttribute("aria-expanded"),
            }));
            expect(destState.hidden).toBe(true);
            expect(destState.visibleChips).toBe(0);
            expect(destState.expanded).toBe("false");

            // Drop WITHOUT expanding it.
            const marks = await dragProjectTo(
                page, project.id, `.goal-card[data-goal-id="${to.id}"]`);
            expect(marks.ok).toBe(true);

            await expect.poll(() => goalIdOf(request, project.id),
                              { timeout: 10000 }).toBe(to.id);
        } finally {
            await request.delete(`/api/projects/${project.id}`);
            await request.delete(`/api/projects/${sibling.id}`);
        }
    });

    test("the No-goal zone drags a project back OUT of its goal", async ({
        page, request,
    }) => {
        // Without this zone the interaction is one-way: a project could be
        // filed under a goal and never unfiled, and a goal-less project
        // would never appear on this page at all.
        const goals = await activeGoals(request);
        const project = await makeProject(request, goals[0].id);

        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await expandAll(page);
            await expect(chip(page, project.id)).toHaveCount(1, { timeout: 10000 });

            const marks = await dragProjectTo(
                page, project.id, ".goals-unassigned-zone");
            expect(marks.ok).toBe(true);

            await expect.poll(() => goalIdOf(request, project.id),
                              { timeout: 10000 }).toBeNull();

            // And it is now listed in the zone, not orphaned off-screen.
            await expect(zone(page).locator(
                `.goal-card-project[data-project-id="${project.id}"]`))
                .toHaveCount(1, { timeout: 10000 });
        } finally {
            await request.delete(`/api/projects/${project.id}`);
        }
    });

    test("a project of ANY type may be dropped on a goal of any category",
         async ({ page, request }) => {
        // The inverse of #344's type gate, and the reason this test
        // exists. populateGoalDropdown (projects.js) offers every active
        // goal for any project with no type filter, and bulk-edit agrees.
        // A gate here would make drag STRICTER than the picker — the same
        // inconsistency #344 closed, pointing the other way. The enums are
        // not parallel either, so there is no pairing to enforce.
        const goals = await activeGoals(request);
        const nonWork = goals.find((g) => g.category !== "work");
        test.skip(!nonWork, "seed has no non-work goal to cross to");

        const project = await makeProject(request, null);   // type: work

        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await expandAll(page);
            await expect(chip(page, project.id)).toHaveCount(1, { timeout: 10000 });

            const marks = await dragProjectTo(
                page, project.id, `.goal-card[data-goal-id="${nonWork.id}"]`);
            expect(marks.ok).toBe(true);
            expect(marks.no).toBe(false);

            await expect.poll(() => goalIdOf(request, project.id),
                              { timeout: 10000 }).toBe(nonWork.id);
        } finally {
            await request.delete(`/api/projects/${project.id}`);
        }
    });

    test("dropping on the goal it already has is a silent no-op", async ({
        page, request,
    }) => {
        // Not a refusal to paint red — the user has not done anything
        // wrong. No drop target, no highlight, no PATCH.
        const goals = await activeGoals(request);
        const project = await makeProject(request, goals[0].id);

        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await expandAll(page);
            await expect(chip(page, project.id)).toHaveCount(1, { timeout: 10000 });

            const patches = [];
            page.on("request", (r) => {
                if (r.method() === "PATCH" && r.url().includes("/api/projects/")) {
                    patches.push(r.url());
                }
            });

            const marks = await dragProjectTo(
                page, project.id, `.goal-card[data-goal-id="${goals[0].id}"]`);
            expect(marks.ok).toBe(false);
            expect(marks.no).toBe(false);       // no red mark either
            expect(marks.accepted).toBe(false);

            await page.waitForTimeout(700);     // a late PATCH would lose
            expect(patches).toEqual([]);
            expect(await goalIdOf(request, project.id)).toBe(goals[0].id);
        } finally {
            await request.delete(`/api/projects/${project.id}`);
        }
    });

    test("a move takes the project's tasks with it (#350)", async ({
        page, request,
    }) => {
        // #343 shipped without this and said so in the UI; that was a
        // gap, not a design. #77's recorded decision is "always
        // overwrite", update_task had honoured it all along, and the
        // repo shipped two tools to repair the drift update_project
        // caused. The bars move now because the tasks do.
        const goals = await activeGoals(request);
        const [from, to] = goals;
        const project = await makeProject(request, from.id);

        const taskRes = await request.post("/api/tasks", {
            data: {
                title: `E2E cascade ${Date.now()}`, type: "work",
                tier: "inbox", project_id: project.id, goal_id: from.id,
            },
        });
        const task = await taskRes.json();

        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await expandAll(page);
            await expect(chip(page, project.id)).toHaveCount(1, { timeout: 10000 });

            await dragProjectTo(page, project.id,
                                `.goal-card[data-goal-id="${to.id}"]`);
            await expect.poll(() => goalIdOf(request, project.id),
                              { timeout: 10000 }).toBe(to.id);

            // The task followed.
            await expect.poll(async () => {
                const r = await request.get(`/api/tasks/${task.id}`);
                return (await r.json()).goal_id;
            }, { timeout: 10000 }).toBe(to.id);

            const status = page.locator("#goalsDragStatus");
            await expect(status).toBeVisible();
            await expect(status).toContainText(/1 task moved with it/i);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
            await request.delete(`/api/projects/${project.id}`);
        }
    });

    test("clearing a goal asks first, and cancelling changes nothing", async ({
        page, request,
    }) => {
        // Unassigning is the destructive direction: it clears the goal on
        // every task of the project with no undo. Moving between goals is
        // a re-point and is cheap to reverse, so only this direction
        // confirms.
        const goals = await activeGoals(request);
        const project = await makeProject(request, goals[0].id);
        const taskRes = await request.post("/api/tasks", {
            data: {
                title: `E2E confirm ${Date.now()}`, type: "work",
                tier: "inbox", project_id: project.id, goal_id: goals[0].id,
            },
        });
        const task = await taskRes.json();

        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await expandAll(page);
            await expect(chip(page, project.id)).toHaveCount(1, { timeout: 10000 });

            const seen = [];
            page.on("dialog", async (d) => {
                seen.push(d.message());
                await d.dismiss();          // say No
            });

            await dragProjectTo(page, project.id, ".goals-unassigned-zone");
            await page.waitForTimeout(800);  // a late PATCH would lose

            expect(seen.length).toBe(1);
            expect(seen[0]).toMatch(/1 task/i);
            expect(seen[0]).toMatch(/cannot be undone/i);

            // Nothing moved, and nothing was cleared.
            expect(await goalIdOf(request, project.id)).toBe(goals[0].id);
            const after = await (await request.get(`/api/tasks/${task.id}`)).json();
            expect(after.goal_id).toBe(goals[0].id);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
            await request.delete(`/api/projects/${project.id}`);
        }
    });

    test("accepting the confirm clears the tasks' goals too", async ({
        page, request,
    }) => {
        const goals = await activeGoals(request);
        const project = await makeProject(request, goals[0].id);
        const taskRes = await request.post("/api/tasks", {
            data: {
                title: `E2E clear ${Date.now()}`, type: "work",
                tier: "inbox", project_id: project.id, goal_id: goals[0].id,
            },
        });
        const task = await taskRes.json();

        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await expandAll(page);
            await expect(chip(page, project.id)).toHaveCount(1, { timeout: 10000 });

            page.on("dialog", (d) => d.accept());

            await dragProjectTo(page, project.id, ".goals-unassigned-zone");
            await expect.poll(() => goalIdOf(request, project.id),
                              { timeout: 10000 }).toBeNull();

            await expect.poll(async () => {
                const r = await request.get(`/api/tasks/${task.id}`);
                return (await r.json()).goal_id;
            }, { timeout: 10000 }).toBeNull();

            await expect(page.locator("#goalsDragStatus"))
                .toContainText(/cleared the goal on 1 task/i);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
            await request.delete(`/api/projects/${project.id}`);
        }
    });

    test("a project with no goal-linked tasks does not nag", async ({
        page, request,
    }) => {
        // The confirm is for data loss, not ceremony. Nothing to clear,
        // nothing to ask.
        const goals = await activeGoals(request);
        const project = await makeProject(request, goals[0].id);
        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await expandAll(page);
            await expect(chip(page, project.id)).toHaveCount(1, { timeout: 10000 });

            const seen = [];
            page.on("dialog", async (d) => { seen.push(d.message()); await d.accept(); });

            await dragProjectTo(page, project.id, ".goals-unassigned-zone");
            await expect.poll(() => goalIdOf(request, project.id),
                              { timeout: 10000 }).toBeNull();

            expect(seen).toEqual([]);
        } finally {
            await request.delete(`/api/projects/${project.id}`);
        }
    });

    // --- #351: the flatten guard ------------------------------------------
    //
    // #350 confirmed on the CLEAR direction only, which left the worse
    // case silent. A project stores ONE goal_id, so when its tasks sit
    // on several goals, any drop collapses them and nothing afterwards
    // remembers the spread — dragging the project back cannot restore
    // it. Reversibility, not direction, is what the dialog is for.

    async function makeTask(request, title, projectId, goalId) {
        const r = await request.post("/api/tasks", {
            data: {
                title: `${title} ${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
                type: "work", tier: "inbox",
                project_id: projectId, goal_id: goalId,
            },
        });
        expect(r.ok()).toBe(true);
        return await r.json();
    }

    const taskGoalOf = async (request, id) =>
        (await (await request.get(`/api/tasks/${id}`)).json()).goal_id;

    test("moving a project whose tasks span two goals asks first (#351)",
        async ({ page, request }) => {
            const goals = await activeGoals(request);
            const project = await makeProject(request, goals[0].id);
            // One task on the project's own goal, one on a DIFFERENT
            // goal. Dropping on a third goal clears nothing, so #350's
            // guard would have stayed silent while both were rewritten.
            const a = await makeTask(request, "E2E flat A", project.id, goals[0].id);
            const b = await makeTask(request, "E2E flat B", project.id, goals[1].id);
            try {
                await page.goto("/goals?nosw=1");
                await page.waitForLoadState("networkidle");
                await expandAll(page);
                await expect(chip(page, project.id))
                    .toHaveCount(1, { timeout: 10000 });

                const seen = [];
                page.on("dialog", async (d) => {
                    seen.push(d.message());
                    await d.dismiss();              // say No
                });

                await dragProjectTo(page, project.id,
                                    `.goal-card[data-goal-id="${goals[2].id}"]`);
                await page.waitForTimeout(800);     // a late PATCH would lose

                expect(seen.length).toBe(1);
                expect(seen[0]).toMatch(/across 2 goals/i);
                expect(seen[0]).toMatch(/will NOT restore that split/i);
                // It names the goals being overwritten, not just a count.
                expect(seen[0]).toContain(goals[0].title);
                expect(seen[0]).toContain(goals[1].title);

                // Dismissed, so nothing moved at all.
                expect(await goalIdOf(request, project.id)).toBe(goals[0].id);
                expect(await taskGoalOf(request, a.id)).toBe(goals[0].id);
                expect(await taskGoalOf(request, b.id)).toBe(goals[1].id);
                await expect(page.locator("#goalsDragStatus"))
                    .toContainText(/where it was/i);
            } finally {
                await request.delete(`/api/tasks/${a.id}`);
                await request.delete(`/api/tasks/${b.id}`);
                await request.delete(`/api/projects/${project.id}`);
            }
        });

    test("accepting the flatten confirm collapses them onto one goal (#351)",
        async ({ page, request }) => {
            const goals = await activeGoals(request);
            const project = await makeProject(request, goals[0].id);
            const a = await makeTask(request, "E2E flat ok A", project.id, goals[0].id);
            const b = await makeTask(request, "E2E flat ok B", project.id, goals[1].id);
            try {
                await page.goto("/goals?nosw=1");
                await page.waitForLoadState("networkidle");
                await expandAll(page);
                await expect(chip(page, project.id))
                    .toHaveCount(1, { timeout: 10000 });

                page.on("dialog", (d) => d.accept());

                await dragProjectTo(page, project.id,
                                    `.goal-card[data-goal-id="${goals[2].id}"]`);
                await expect.poll(() => goalIdOf(request, project.id),
                                  { timeout: 10000 }).toBe(goals[2].id);
                await expect.poll(() => taskGoalOf(request, a.id),
                                  { timeout: 10000 }).toBe(goals[2].id);
                await expect.poll(() => taskGoalOf(request, b.id),
                                  { timeout: 10000 }).toBe(goals[2].id);
            } finally {
                await request.delete(`/api/tasks/${a.id}`);
                await request.delete(`/api/tasks/${b.id}`);
                await request.delete(`/api/projects/${project.id}`);
            }
        });

    test("a single-goal move still does not ask (#351)",
        async ({ page, request }) => {
            // The guard must not become a nag on the ordinary case. Every
            // task shares one goal, so dragging the project back would
            // restore all of them exactly — nothing to warn about.
            const goals = await activeGoals(request);
            const project = await makeProject(request, goals[0].id);
            const a = await makeTask(request, "E2E one A", project.id, goals[0].id);
            const b = await makeTask(request, "E2E one B", project.id, goals[0].id);
            try {
                await page.goto("/goals?nosw=1");
                await page.waitForLoadState("networkidle");
                await expandAll(page);
                await expect(chip(page, project.id))
                    .toHaveCount(1, { timeout: 10000 });

                const seen = [];
                page.on("dialog", async (d) => {
                    seen.push(d.message());
                    await d.accept();
                });

                await dragProjectTo(page, project.id,
                                    `.goal-card[data-goal-id="${goals[1].id}"]`);
                await expect.poll(() => taskGoalOf(request, a.id),
                                  { timeout: 10000 }).toBe(goals[1].id);
                await expect.poll(() => taskGoalOf(request, b.id),
                                  { timeout: 10000 }).toBe(goals[1].id);

                expect(seen).toEqual([]);
            } finally {
                await request.delete(`/api/tasks/${a.id}`);
                await request.delete(`/api/tasks/${b.id}`);
                await request.delete(`/api/projects/${project.id}`);
            }
        });

    // --- #352: recurring templates are part of the cascade ----------------
    //
    // RecurringTask carries its own goal_id and the spawner copies it
    // onto every task it creates, so a template left behind re-stamps
    // the OLD goal on each future fire. The invariant would hold at the
    // moment of the drag and then decay on a timer.

    async function makeRecurring(request, projectId, goalId) {
        const r = await request.post("/api/recurring", {
            data: {
                title: `E2E repeat ${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
                frequency: "daily", type: "work",
                project_id: projectId, goal_id: goalId,
            },
        });
        expect(r.ok()).toBe(true);
        return await r.json();
    }

    const recurringGoalOf = async (request, id) =>
        (await (await request.get(`/api/recurring/${id}`)).json()).goal_id;

    test("a repeating task moves with the project (#352)",
        async ({ page, request }) => {
            const goals = await activeGoals(request);
            const project = await makeProject(request, goals[0].id);
            const rt = await makeRecurring(request, project.id, goals[0].id);
            try {
                await page.goto("/goals?nosw=1");
                await page.waitForLoadState("networkidle");
                await expandAll(page);
                await expect(chip(page, project.id))
                    .toHaveCount(1, { timeout: 10000 });

                // One source goal, so this is NOT a flatten — it must
                // move silently, and the template must still follow.
                const seen = [];
                page.on("dialog", async (d) => { seen.push(d.message()); await d.accept(); });

                await dragProjectTo(page, project.id,
                                    `.goal-card[data-goal-id="${goals[1].id}"]`);
                await expect.poll(() => recurringGoalOf(request, rt.id),
                                  { timeout: 10000 }).toBe(goals[1].id);
                expect(seen).toEqual([]);
                await expect(page.locator("#goalsDragStatus"))
                    .toContainText(/1 repeating task moved with it/i);
            } finally {
                await request.delete(`/api/recurring/${rt.id}`);
                await request.delete(`/api/projects/${project.id}`);
            }
        });

    test("a repeating task on its own goal triggers the flatten confirm (#352)",
        async ({ page, request }) => {
            // The live "Evening prep" shape: the template sits on a goal
            // nothing else on the project uses. Losing it is losing more
            // than a task, because it keeps paying out.
            const goals = await activeGoals(request);
            const project = await makeProject(request, goals[0].id);
            const task = await makeTask(request, "E2E rt task", project.id, goals[0].id);
            const rt = await makeRecurring(request, project.id, goals[1].id);
            try {
                await page.goto("/goals?nosw=1");
                await page.waitForLoadState("networkidle");
                await expandAll(page);
                await expect(chip(page, project.id))
                    .toHaveCount(1, { timeout: 10000 });

                const seen = [];
                page.on("dialog", async (d) => { seen.push(d.message()); await d.dismiss(); });

                await dragProjectTo(page, project.id,
                                    `.goal-card[data-goal-id="${goals[2].id}"]`);
                await page.waitForTimeout(800);

                expect(seen.length).toBe(1);
                expect(seen[0]).toMatch(/1 repeating task/i);
                expect(seen[0]).toMatch(/across 2 goals/i);

                // Dismissed: the template kept its own goal.
                expect(await recurringGoalOf(request, rt.id)).toBe(goals[1].id);
            } finally {
                await request.delete(`/api/tasks/${task.id}`);
                await request.delete(`/api/recurring/${rt.id}`);
                await request.delete(`/api/projects/${project.id}`);
            }
        });

    test("the project chip advertises that it can be dragged", async ({
        page, request,
    }) => {
        // Discoverability, not just function: a chip that looks like a
        // static label tells nobody it can be moved.
        const goals = await activeGoals(request);
        const project = await makeProject(request, goals[0].id);
        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await expandAll(page);
            const li = chip(page, project.id);
            await expect(li).toBeVisible({ timeout: 10000 });
            const look = await li.evaluate((el) => ({
                cursor: getComputedStyle(el).cursor,
                grip: getComputedStyle(el, "::before").content,
                draggable: el.draggable,
            }));
            expect(look.cursor).toBe("grab");
            expect(look.grip).toContain("⠿");   // the braille grip glyph
            expect(look.draggable).toBe(true);
        } finally {
            await request.delete(`/api/projects/${project.id}`);
        }
    });

    test("a collapsed card shows its project COUNT", async ({ page, request }) => {
        // The count is what makes collapsing acceptable — without it a
        // collapsed goal looks like a goal with no projects.
        const goals = await activeGoals(request);
        const project = await makeProject(request, goals[0].id);
        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            const toggle = goalCard(page, goals[0].id)
                .locator(".goal-card-projects-toggle");
            await expect(toggle).toBeVisible({ timeout: 10000 });
            await expect(toggle).toHaveText(/Projects \(\d+\)/);
            await expect(toggle).toHaveAttribute("aria-expanded", "false");
        } finally {
            await request.delete(`/api/projects/${project.id}`);
        }
    });

    // --- the touch path -----------------------------------------------------
    // HTML5 drag-and-drop does not fire from a finger, so /goals has its
    // own long-press path. Without these the feature could be green on
    // desktop and simply absent on the phone.

    test("long-press then drag moves the project on touch", async ({
        page, request,
    }) => {
        const goals = await activeGoals(request);
        const [from, to] = goals;
        const project = await makeProject(request, from.id);

        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await expandAll(page);
            await expect(chip(page, project.id)).toHaveCount(1, { timeout: 10000 });

            const started = await page.evaluate(async ({ p, g }) => {
                const fire = (el, type, x, y, released) => {
                    const touch = new Touch({
                        identifier: 1, target: el, clientX: x, clientY: y,
                    });
                    el.dispatchEvent(new TouchEvent(type, {
                        bubbles: true, cancelable: true,
                        touches: released ? [] : [touch],
                        targetTouches: released ? [] : [touch],
                        changedTouches: [touch],
                    }));
                };
                const li = document.querySelector(
                    `.goal-card-project[data-project-id="${p}"]`);
                const dest = document.querySelector(
                    `.goal-card[data-goal-id="${g}"]`);
                dest.scrollIntoView({ block: "center" });
                await new Promise((r) => setTimeout(r, 200));
                const r0 = li.getBoundingClientRect();
                fire(li, "touchstart", r0.left + 20, r0.top + 10, false);
                await new Promise((r) => setTimeout(r, 650));  // past the 500ms hold
                const dragging = li.classList.contains("dragging");
                const rd = dest.getBoundingClientRect();
                const cx = rd.left + rd.width / 2;
                const cy = rd.top + rd.height / 2;
                fire(document, "touchmove", cx, cy, false);
                const marked = dest.classList.contains("goal-card-drop-ok");
                fire(document, "touchend", cx, cy, true);
                return { dragging, marked };
            }, { p: project.id, g: to.id });

            expect(started.dragging).toBe(true);
            expect(started.marked).toBe(true);

            await expect.poll(() => goalIdOf(request, project.id),
                              { timeout: 10000 }).toBe(to.id);
        } finally {
            await request.delete(`/api/projects/${project.id}`);
        }
    });

    test("a touch drop does not also open the goal detail panel", async ({
        page, request,
    }) => {
        // The goal card's click opens the editor, and a touchend
        // synthesises a click. Without preventDefault the user would drop
        // a project and get an edit form over the result.
        const goals = await activeGoals(request);
        const [from, to] = goals;
        const project = await makeProject(request, from.id);

        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await expandAll(page);
            await expect(chip(page, project.id)).toHaveCount(1, { timeout: 10000 });

            await page.evaluate(async ({ p, g }) => {
                const fire = (el, type, x, y, released) => {
                    const touch = new Touch({
                        identifier: 1, target: el, clientX: x, clientY: y,
                    });
                    el.dispatchEvent(new TouchEvent(type, {
                        bubbles: true, cancelable: true,
                        touches: released ? [] : [touch],
                        targetTouches: released ? [] : [touch],
                        changedTouches: [touch],
                    }));
                };
                const li = document.querySelector(
                    `.goal-card-project[data-project-id="${p}"]`);
                const dest = document.querySelector(
                    `.goal-card[data-goal-id="${g}"]`);
                dest.scrollIntoView({ block: "center" });
                await new Promise((r) => setTimeout(r, 200));
                const r0 = li.getBoundingClientRect();
                fire(li, "touchstart", r0.left + 20, r0.top + 10, false);
                await new Promise((r) => setTimeout(r, 650));
                const rd = dest.getBoundingClientRect();
                fire(document, "touchmove", rd.left + rd.width / 2,
                     rd.top + rd.height / 2, false);
                fire(document, "touchend", rd.left + rd.width / 2,
                     rd.top + rd.height / 2, true);
            }, { p: project.id, g: to.id });

            await expect.poll(() => goalIdOf(request, project.id),
                              { timeout: 10000 }).toBe(to.id);
            await expect(page.locator("#goalDetailOverlay")).toBeHidden();
        } finally {
            await request.delete(`/api/projects/${project.id}`);
        }
    });

    test("a tap and a scroll are not drags", async ({ page, request }) => {
        // The two ways the touch path could ruin ordinary phone use:
        // tapping a chip, and scrolling the board with a finger that
        // happens to start on one.
        const goals = await activeGoals(request);
        const project = await makeProject(request, goals[0].id);
        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await expandAll(page);
            await expect(chip(page, project.id)).toBeVisible({ timeout: 10000 });

            const out = await page.evaluate(async (p) => {
                const fire = (el, type, x, y, released) => {
                    const touch = new Touch({
                        identifier: 1, target: el, clientX: x, clientY: y,
                    });
                    el.dispatchEvent(new TouchEvent(type, {
                        bubbles: true, cancelable: true,
                        touches: released ? [] : [touch],
                        targetTouches: released ? [] : [touch],
                        changedTouches: [touch],
                    }));
                };
                const li = document.querySelector(
                    `.goal-card-project[data-project-id="${p}"]`);
                const r = li.getBoundingClientRect();
                const x = r.left + 20;
                const y = r.top + 10;

                // A quick tap, released well inside the hold window.
                fire(li, "touchstart", x, y, false);
                await new Promise((s) => setTimeout(s, 120));
                fire(document, "touchend", x, y, true);
                await new Promise((s) => setTimeout(s, 500));
                const afterTap = li.classList.contains("dragging");

                // A scroll: moved well past the 10px jitter tolerance.
                fire(li, "touchstart", x, y, false);
                fire(document, "touchmove", x, y + 60, false);
                await new Promise((s) => setTimeout(s, 650));
                const afterScroll = li.classList.contains("dragging");
                fire(document, "touchend", x, y + 60, true);
                await new Promise((s) => setTimeout(s, 200));

                // A few px of jitter during a hold is still a hold.
                fire(li, "touchstart", x, y, false);
                fire(document, "touchmove", x + 3, y + 4, false);
                await new Promise((s) => setTimeout(s, 650));
                const afterJitter = li.classList.contains("dragging");
                fire(document, "touchend", x + 3, y + 4, true);
                await new Promise((s) => setTimeout(s, 200));

                return { afterTap, afterScroll, afterJitter };
            }, project.id);

            expect(out.afterTap).toBe(false);
            expect(out.afterScroll).toBe(false);
            expect(out.afterJitter).toBe(true);
        } finally {
            await request.delete(`/api/projects/${project.id}`);
        }
    });
});

test.describe("Goals - archive, unarchive, and a guarded delete (#349)", () => {
    // The bug: `delete_goal` is a SOFT delete, but the button said
    // "Delete", the board hard-filtered to active goals with no filter
    // control, and nothing could unarchive. So one click made a goal
    // permanently invisible and unrecoverable from the UI while the row
    // survived in the database.
    //
    // Every test asserts PERSISTED state via the API, not that a class
    // appeared — #347 is open precisely because a test that watched the
    // shape of a request passed while the request was failing.

    const goalCard = (page, id) =>
        page.locator(`.goal-card[data-goal-id="${id}"]`);

    // `create_goal` deliberately ignores `is_active` — a goal cannot be
    // born archived — so an archived fixture has to go through the real
    // archive action, which is DELETE /api/goals/<id>.
    async function makeGoal(request, opts) {
        const r = await request.post("/api/goals", {
            data: {
                title: `E2E arch ${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
                category: "work", priority: "should",
            },
        });
        expect(r.ok()).toBe(true);
        const goal = await r.json();
        if (opts && opts.archived) {
            const d = await request.delete(`/api/goals/${goal.id}`);
            expect(d.status()).toBe(204);
            goal.is_active = false;
        }
        return goal;
    }

    const goalById = async (request, id) => {
        const r = await request.get("/api/goals?is_active=all");
        return (await r.json()).find((g) => g.id === id);
    };

    async function setFilter(page, value) {
        await page.selectOption("#filterArchived", value);
        await page.waitForTimeout(150);          // re-render is synchronous
    }

    async function openGoal(page, id) {
        await goalCard(page, id).click();
        await expect(page.locator("#goalDetailOverlay")).toBeVisible();
    }

    test("an archived goal is hidden by default and found under Archived", async ({
        page, request,
    }) => {
        const goal = await makeGoal(request, { archived: true });
        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");

            // Default view: gone.
            await expect(goalCard(page, goal.id)).toHaveCount(0);

            // Archived: there, and badged.
            await setFilter(page, "archived");
            await expect(goalCard(page, goal.id)).toHaveCount(1, { timeout: 10000 });
            await expect(goalCard(page, goal.id).locator(".badge-archived"))
                .toHaveText(/archived/i);

            // All: there too.
            await setFilter(page, "all");
            await expect(goalCard(page, goal.id)).toHaveCount(1);
        } finally {
            await request.delete(`/api/goals/${goal.id}`);
            await request.delete(`/api/goals/${goal.id}/permanent`);
        }
    });

    test("the button says Archive, not Delete, and archives", async ({
        page, request,
    }) => {
        // The label is the fix. A destructive word on a non-destructive
        // action is what made this unrecoverable in the first place.
        const goal = await makeGoal(request);
        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await openGoal(page, goal.id);

            await expect(page.locator("#goalDelete")).toHaveText(/^Archive$/);

            await page.locator("#goalDelete").click();
            await expect.poll(async () => (await goalById(request, goal.id)).is_active,
                              { timeout: 10000 }).toBe(false);
            // ...and the row still exists. That is the difference
            // between archiving and deleting.
            expect(await goalById(request, goal.id)).toBeTruthy();
        } finally {
            await request.delete(`/api/goals/${goal.id}/permanent`);
        }
    });

    test("an archived goal offers Unarchive, and it comes back", async ({
        page, request,
    }) => {
        const goal = await makeGoal(request, { archived: true });
        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await setFilter(page, "archived");
            await openGoal(page, goal.id);

            await expect(page.locator("#goalDelete")).toHaveText(/^Unarchive$/);

            await page.locator("#goalDelete").click();
            await expect.poll(async () => (await goalById(request, goal.id)).is_active,
                              { timeout: 10000 }).toBe(true);
        } finally {
            await request.delete(`/api/goals/${goal.id}`);
            await request.delete(`/api/goals/${goal.id}/permanent`);
        }
    });

    test("permanent delete is refused on an ACTIVE goal, and says why", async ({
        page, request,
    }) => {
        const goal = await makeGoal(request);
        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await openGoal(page, goal.id);

            await expect(page.locator("#goalHardDelete")).toBeDisabled();
            await expect(page.locator("#goalHardDeleteHint"))
                .toContainText(/archive this goal first/i);
        } finally {
            await request.delete(`/api/goals/${goal.id}`);
            await request.delete(`/api/goals/${goal.id}/permanent`);
        }
    });

    test("permanent delete is refused while a task points at it, and names it",
        async ({ page, request }) => {
            // A disabled button with no explanation is its own usability
            // bug. The hint has to say what is in the way.
            const goal = await makeGoal(request, { archived: true });
            const taskRes = await request.post("/api/tasks", {
                data: {
                    title: `E2E clinger ${Date.now()}`, type: "work",
                    tier: "inbox", goal_id: goal.id,
                },
            });
            const task = await taskRes.json();
            try {
                await page.goto("/goals?nosw=1");
                await page.waitForLoadState("networkidle");
                await setFilter(page, "archived");
                await openGoal(page, goal.id);

                await expect(page.locator("#goalHardDelete")).toBeDisabled();
                await expect(page.locator("#goalHardDeleteHint"))
                    .toContainText(/1 task/i);
                await expect(page.locator("#goalHardDeleteHint"))
                    .toContainText(/pointing at nothing/i);

                // And the goal is still there.
                expect(await goalById(request, goal.id)).toBeTruthy();
            } finally {
                await request.delete(`/api/tasks/${task.id}`);
                await request.delete(`/api/goals/${goal.id}/permanent`);
            }
        });

    test("permanent delete removes an archived, unreferenced goal", async ({
        page, request,
    }) => {
        const goal = await makeGoal(request, { archived: true });
        let gone = false;
        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await setFilter(page, "archived");
            await openGoal(page, goal.id);

            await expect(page.locator("#goalHardDelete")).toBeEnabled({
                timeout: 10000,
            });
            await expect(page.locator("#goalHardDeleteHint"))
                .toContainText(/nothing points at this goal/i);

            page.once("dialog", (d) => d.accept());
            await page.locator("#goalHardDelete").click();

            await expect.poll(() => goalById(request, goal.id),
                              { timeout: 10000 }).toBeUndefined();
            gone = true;
        } finally {
            if (!gone) await request.delete(`/api/goals/${goal.id}/permanent`);
        }
    });

    test("dismissing the permanent-delete confirm changes nothing", async ({
        page, request,
    }) => {
        const goal = await makeGoal(request, { archived: true });
        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await setFilter(page, "archived");
            await openGoal(page, goal.id);
            await expect(page.locator("#goalHardDelete")).toBeEnabled({
                timeout: 10000,
            });

            const seen = [];
            page.once("dialog", async (d) => { seen.push(d.message()); await d.dismiss(); });
            await page.locator("#goalHardDelete").click();
            await page.waitForTimeout(800);       // a late DELETE would lose

            expect(seen.length).toBe(1);
            expect(seen[0]).toMatch(/cannot be undone/i);
            expect(seen[0]).toMatch(/recycle bin will not bring it back/i);
            expect(await goalById(request, goal.id)).toBeTruthy();
        } finally {
            await request.delete(`/api/goals/${goal.id}/permanent`);
        }
    });

    test("a brand-new goal shows no archive or delete controls", async ({
        page,
    }) => {
        // Neither action means anything for a goal that does not exist
        // yet, and an enabled-looking destructive button on a blank form
        // is exactly the kind of thing that gets clicked.
        await page.goto("/goals?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator("#addGoalBtn").click();
        await expect(page.locator("#goalDetailOverlay")).toBeVisible();

        await expect(page.locator("#goalDelete")).toBeHidden();
        await expect(page.locator("#goalDangerZone")).toBeHidden();
    });
});

test.describe("An archived link stays representable (#355)", () => {
    // The bug: every select that restores a stored project_id / goal_id
    // built its <option> list from the ACTIVE rows only. An archived
    // stored value matched no option, so selectedIndex went to -1 and the
    // select read back "". The save path cannot tell that apart from "the
    // user picked — None —", so a save with nothing edited destroyed the
    // link. Worse, the phantom diff looked like a real edit, which tripped
    // #148's revival branch (buildTaskDetailPayload adds status:"active"
    // when a completed task "changed") and un-completed the task.
    //
    // Live exposure when this was written: 270 completed tasks across 8
    // archived projects, 262 of them also carrying a goal_id, plus 2
    // recurring templates still spawning into an archived project.
    //
    // Every assertion reads PERSISTED state back through the API. A test
    // that only checked the option's label would pass while the save was
    // still detaching — that is #347's whole lesson.

    const stamp = () =>
        `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

    // The fixture has to be built live, not taken from the seed: the gate
    // runner never seeds, and the archived state must be reached the way
    // prod reached it.
    //
    // PATCH is_active:false, the Archive button's path. (Until #353 the
    // DELETE route also nulled Task.project_id, per PR63 #129, which would
    // have dismantled this fixture. ADR-038 removed that detach, so both
    // paths now keep the link.)
    async function archivedFixture(request, { withTemplate = false } = {}) {
        const s = stamp();
        const g = await request.post("/api/goals", {
            data: { title: `E2E 355 goal ${s}`, category: "work",
                    priority: "should" },
        });
        expect(g.ok()).toBe(true);
        const goal = await g.json();

        const p = await request.post("/api/projects", {
            data: { name: `E2E 355 project ${s}`, type: "work",
                    goal_id: goal.id },
        });
        expect(p.ok()).toBe(true);
        const project = await p.json();

        const t = await request.post("/api/tasks", {
            data: { title: `E2E 355 task ${s}`, type: "work", tier: "today",
                    project_id: project.id, goal_id: goal.id },
        });
        expect(t.ok()).toBe(true);
        let task = await t.json();
        const done = await request.post(`/api/tasks/${task.id}/complete`);
        expect(done.ok()).toBe(true);
        task = await done.json();
        expect(task.status).toBe("archived");

        let template = null;
        if (withTemplate) {
            const r = await request.post("/api/recurring", {
                data: { title: `E2E 355 template ${s}`, frequency: "daily",
                        type: "work", project_id: project.id,
                        goal_id: goal.id },
            });
            expect(r.ok()).toBe(true);
            template = await r.json();
        }

        // Archive both links, in the order that leaves the rows intact.
        const ap = await request.patch(`/api/projects/${project.id}`, {
            data: { is_active: false },
        });
        expect(ap.ok()).toBe(true);
        const ag = await request.delete(`/api/goals/${goal.id}`);   // soft
        expect(ag.status()).toBe(204);

        // #353: archiving the project PAUSED the template. Turn it back
        // on, which is the real-world state this fixture models: a
        // template the user resumed while its project stays archived. It
        // is also the only way it can appear on /recurring, which lists
        // active templates only (#363).
        if (template) {
            const paused = await (
                await request.get(`/api/recurring/${template.id}`)).json();
            expect(paused.is_active).toBe(false);
            const resumed = await request.patch(
                `/api/recurring/${template.id}`, { data: { is_active: true } });
            expect(resumed.ok()).toBe(true);
        }

        // The link really did survive being archived — otherwise the rest
        // of the test would be asserting against an already-empty field.
        const check = await (await request.get(`/api/tasks/${task.id}`)).json();
        expect(check.project_id).toBe(project.id);
        expect(check.goal_id).toBe(goal.id);

        return { goal, project, task, template };
    }

    // Unwind in dependency order. The dev DB is shared with every other
    // local spec, so a leftover archived project would change what the
    // project filter bar and the goal pickers render for the next test.
    // hard_delete_goal refuses while ANY row still points at the goal,
    // and it counts tasks, projects and recurring templates regardless of
    // is_active — so every link has to be nulled, not merely archived.
    // DELETE on a task or a template is a soft-delete that keeps the
    // foreign key.
    async function cleanup(request, { goal, project, task, template }) {
        if (template) {
            await request.patch(`/api/recurring/${template.id}`, {
                data: { project_id: null, goal_id: null },
            });
            await request.delete(`/api/recurring/${template.id}`);
        }
        await request.patch(`/api/tasks/${task.id}`, {
            data: { project_id: null, goal_id: null },
        });
        await request.delete(`/api/tasks/${task.id}`);
        await request.patch(`/api/projects/${project.id}`, {
            data: { goal_id: null },
        });
        await request.delete(`/api/projects/${project.id}`);
        await request.delete(`/api/goals/${goal.id}/permanent`);
    }

    // Opens the completed task through the BOARD's Completed section, not
    // the dedicated /completed page. That is the surface the user actually
    // reaches these tasks through. (When #355 shipped, /completed rendered
    // an empty list — init()'s panel-only branch, #270's `isBoard` gate,
    // returned before loadCompletedTasks(). That was filed and fixed
    // separately as #358; this test stays on the board's section.)
    async function openCompletedTask(page, taskId) {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator("#tierCompleted .collapse-toggle").click();
        const card = page.locator(
            `#completedList .task-card[data-id="${taskId}"]`);
        await expect(card).toHaveCount(1, { timeout: 10000 });
        // #281: click the title's top-left, not the card centre.
        await card.locator(".task-title").click({ position: { x: 4, y: 4 } });
        await expect(page.locator("#detailPanel")).toBeVisible({
            timeout: 2000,
        });
    }

    test("saving a completed task on an archived project keeps the link and stays completed", async ({
        page, request,
    }) => {
        const fx = await archivedFixture(request);
        try {
            await openCompletedTask(page, fx.task.id);

            // The selects must actually hold the stored ids. Reading ""
            // here IS the bug.
            await expect(page.locator("#detailProject"))
                .toHaveValue(fx.project.id);
            await expect(page.locator("#detailGoal"))
                .toHaveValue(fx.goal.id);

            // Save with nothing edited — the absent-minded save that
            // used to destroy the link.
            await page.locator("#detailForm button[type=submit]").click();
            await page.waitForTimeout(600);

            const after = await (
                await request.get(`/api/tasks/${fx.task.id}`)).json();
            expect(after.project_id).toBe(fx.project.id);
            expect(after.goal_id).toBe(fx.goal.id);
            // #148's revival branch must NOT fire: nothing was edited.
            expect(after.status).toBe("archived");
        } finally {
            await cleanup(request, fx);
        }
    });

    test("the archived option is labelled and disabled, so it can be left but not chosen", async ({
        page, request,
    }) => {
        const fx = await archivedFixture(request);
        try {
            await openCompletedTask(page, fx.task.id);

            const state = await page.evaluate(({ pid, gid }) => {
                const read = (selId, optId) => {
                    const sel = document.getElementById(selId);
                    const opt = sel.querySelector(`option[value="${optId}"]`);
                    return opt
                        ? { label: opt.textContent, disabled: opt.disabled }
                        : null;
                };
                return { proj: read("detailProject", pid),
                         goal: read("detailGoal", gid) };
            }, { pid: fx.project.id, gid: fx.goal.id });

            // Present at all — the option has to exist for the select to
            // hold the value.
            expect(state.proj).not.toBeNull();
            expect(state.goal).not.toBeNull();
            // Say WHY it looks different, rather than showing a live name.
            expect(state.proj.label).toContain("(archived)");
            expect(state.goal.label).toContain("(archived)");
            // Disabled, not enabled: the link is readable and keepable,
            // but an archived row is not a thing you can newly pick.
            expect(state.proj.disabled).toBe(true);
            expect(state.goal.disabled).toBe(true);
        } finally {
            await cleanup(request, fx);
        }
    });

    test("— None — still unlinks a task whose project is archived", async ({
        page, request,
    }) => {
        // The other half of the contract: keeping the link must stay
        // possible WITHOUT making the field read-only. Clearing it is a
        // deliberate choice and has to keep working.
        const fx = await archivedFixture(request);
        try {
            await openCompletedTask(page, fx.task.id);
            await page.locator("#detailProject").selectOption("");
            await page.locator("#detailForm button[type=submit]").click();
            await page.waitForTimeout(600);

            const after = await (
                await request.get(`/api/tasks/${fx.task.id}`)).json();
            expect(after.project_id).toBeNull();
            // This WAS a real edit, so #148 revival is correct here.
            expect(after.status).toBe("active");
        } finally {
            await cleanup(request, fx);
        }
    });

    test("a recurring template on an archived project survives an edit @noviewport", async ({
        page, request,
    }) => {
        // The /recurring editor is the worst case: it has no "did anything
        // change" guard at all, so collectEditor() sent
        // project_id: value || null on EVERY save. One edited title
        // detached a template that is still spawning tasks.
        const fx = await archivedFixture(request, { withTemplate: true });
        try {
            await page.goto("/recurring?nosw=1");
            await page.waitForLoadState("networkidle");

            const row = page.locator(
                `.recurring-row:has(input[data-id="${fx.template.id}"])`);
            await expect(row).toHaveCount(1, { timeout: 10000 });
            // The list view must name the archived project, not "(none)".
            await expect(row.locator(".recurring-row-meta"))
                .toContainText("(archived)");

            await row.locator(".recurring-row-info").click();
            await expect(page.locator("#recurEditOverlay")).toBeVisible({
                timeout: 2000,
            });
            await expect(page.locator("#recurEditProject"))
                .toHaveValue(fx.project.id);
            await expect(page.locator("#recurEditGoal"))
                .toHaveValue(fx.goal.id);

            // Edit something unrelated and save.
            await page.locator("#recurEditNotes").fill("edited by #355 e2e");
            await page.locator("#recurEditForm button[type=submit]").click();
            await page.waitForTimeout(600);

            const after = await (
                await request.get(`/api/recurring/${fx.template.id}`)).json();
            expect(after.notes).toBe("edited by #355 e2e");
            expect(after.project_id).toBe(fx.project.id);
            expect(after.goal_id).toBe(fx.goal.id);
        } finally {
            await cleanup(request, fx);
        }
    });
});

test.describe("Archiving a project pauses its repeating tasks (#353) @noviewport", () => {
    // The pause is server-side, on every archive path (pytest pins that).
    // What this proves is the /projects half: the user is TOLD which
    // repeating tasks will pause before the archive happens, and only
    // when there are any. Every assertion on the pause itself reads
    // persisted state back through the API.
    //
    // @noviewport: desktop only. The dialogs are browser confirm()s, so
    // there's no layout to differ, and mobile is covered by Phase 6.

    const stamp = () =>
        `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const TAIL = "They resume when you unarchive the project.";

    async function projectWith(request, { templates = 0 } = {}) {
        const s = stamp();
        const p = await request.post("/api/projects", {
            data: { name: `E2E 353 project ${s}`, type: "work" },
        });
        expect(p.ok()).toBe(true);
        const project = await p.json();
        const made = [];
        for (let i = 0; i < templates; i++) {
            const r = await request.post("/api/recurring", {
                data: { title: `E2E 353 routine ${i} ${s}`, frequency: "daily",
                        type: "work", project_id: project.id },
            });
            expect(r.ok()).toBe(true);
            made.push(await r.json());
        }
        return { project, templates: made };
    }

    // Projects have no hard delete (#357), so an archived project is the
    // floor. Detach + soft-delete the templates so nothing keeps firing.
    async function cleanup(request, fixtures) {
        for (const { project, templates } of fixtures) {
            for (const t of templates) {
                await request.patch(`/api/recurring/${t.id}`, {
                    data: { project_id: null },
                });
                await request.delete(`/api/recurring/${t.id}`);
            }
            await request.delete(`/api/projects/${project.id}`);
        }
    }

    async function templateActive(request, id) {
        return (await (await request.get(`/api/recurring/${id}`)).json()).is_active;
    }

    async function openProjects(page, filter = "active") {
        await page.goto("/projects?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator("#projectFilterActive").selectOption(filter);
    }

    async function openPanel(page, projectId) {
        await page.locator(`.project-card[data-project-id="${projectId}"]`).click();
        await expect(page.locator("#projectArchiveToggle")).toBeVisible({ timeout: 3000 });
    }

    test("the archive confirm names the template; unarchive resumes it with no dialog", async ({
        page, request,
    }) => {
        const fx = await projectWith(request, { templates: 1 });
        try {
            await openProjects(page);
            await openPanel(page, fx.project.id);

            const shown = [];
            page.once("dialog", (d) => { shown.push(d.message()); d.accept(); });
            await page.locator("#projectArchiveToggle").click();
            await expect.poll(async () => (await (await request.get(
                `/api/projects/${fx.project.id}`)).json()).is_active).toBe(false);

            expect(shown).toHaveLength(1);
            expect(shown[0]).toContain(`"${fx.templates[0].title}"`);
            expect(shown[0]).toContain(TAIL);
            expect(await templateActive(request, fx.templates[0].id)).toBe(false);

            // Unarchive: restoring a prior state is not a decision, so
            // any dialog here is a failure.
            const unexpected = [];
            page.on("dialog", (d) => { unexpected.push(d.message()); d.dismiss(); });
            await openProjects(page, "archived");
            await openPanel(page, fx.project.id);
            await expect(page.locator("#projectArchiveToggle")).toHaveText("Unarchive");
            await page.locator("#projectArchiveToggle").click();
            await expect.poll(() => templateActive(request, fx.templates[0].id)).toBe(true);
            expect(unexpected).toEqual([]);
        } finally {
            await cleanup(request, [fx]);
        }
    });

    test("cancelling the confirm archives nothing", async ({ page, request }) => {
        const fx = await projectWith(request, { templates: 1 });
        try {
            await openProjects(page);
            await openPanel(page, fx.project.id);
            page.once("dialog", (d) => d.dismiss());
            await page.locator("#projectArchiveToggle").click();
            await page.waitForTimeout(600);

            const proj = await (await request.get(`/api/projects/${fx.project.id}`)).json();
            expect(proj.is_active).toBe(true);
            expect(await templateActive(request, fx.templates[0].id)).toBe(true);
        } finally {
            await cleanup(request, [fx]);
        }
    });

    test("archiving a project with no repeating tasks shows no dialog", async ({
        page, request,
    }) => {
        const fx = await projectWith(request);
        try {
            const unexpected = [];
            page.on("dialog", (d) => { unexpected.push(d.message()); d.dismiss(); });
            await openProjects(page);
            await openPanel(page, fx.project.id);
            await page.locator("#projectArchiveToggle").click();
            await expect.poll(async () => (await (await request.get(
                `/api/projects/${fx.project.id}`)).json()).is_active).toBe(false);
            expect(unexpected).toEqual([]);
        } finally {
            await cleanup(request, [fx]);
        }
    });

    test("the bulk Archive confirm lists templates across two projects", async ({
        page, request,
    }) => {
        const a = await projectWith(request, { templates: 1 });
        const b = await projectWith(request, { templates: 1 });
        try {
            await openProjects(page);
            await page.locator("#projectsBulkToggle").click();
            for (const fx of [a, b]) {
                await page.locator(
                    `.project-card[data-project-id="${fx.project.id}"]`).click();
            }
            const shown = [];
            page.once("dialog", (d) => { shown.push(d.message()); d.accept(); });
            await page.locator("#projectsBulkArchive").click();
            await expect.poll(() => templateActive(request, b.templates[0].id)).toBe(false);

            expect(shown).toHaveLength(1);
            expect(shown[0]).toContain("Archive 2 project(s)?");
            expect(shown[0]).toContain(`"${a.templates[0].title}"`);
            expect(shown[0]).toContain(`"${b.templates[0].title}"`);
            expect(await templateActive(request, a.templates[0].id)).toBe(false);
        } finally {
            await cleanup(request, [a, b]);
        }
    });

    test("the bulk Delete confirm names the template too", async ({ page, request }) => {
        const fx = await projectWith(request, { templates: 1 });
        try {
            await openProjects(page);
            await page.locator("#projectsBulkToggle").click();
            await page.locator(
                `.project-card[data-project-id="${fx.project.id}"]`).click();
            const shown = [];
            page.once("dialog", (d) => { shown.push(d.message()); d.accept(); });
            await page.locator("#projectsBulkDelete").click();
            await expect.poll(() => templateActive(request, fx.templates[0].id)).toBe(false);

            expect(shown).toHaveLength(1);
            expect(shown[0]).toContain("Soft-delete (archive) 1 project(s)?");
            expect(shown[0]).toContain(`"${fx.templates[0].title}"`);
        } finally {
            await cleanup(request, [fx]);
        }
    });

    test("if the template lookup fails, the archive still goes through", async ({
        page, request,
    }) => {
        // The server cascade is the control; the dialog is only
        // information. A failed lookup must not block archiving.
        //
        // A 500, not a dropped connection: a true network failure trips
        // apiFetch's app-wide "Reload the page to recover?" prompt
        // (PR47 #112), which is right there, because the archive PATCH
        // right after would fail too. The case where the LOOKUP fails but
        // archiving can still succeed is a server error on this endpoint.
        const fx = await projectWith(request, { templates: 1 });
        try {
            await page.route("**/api/recurring", (r) => r.fulfill({
                status: 500, contentType: "application/json",
                body: JSON.stringify({ error: "boom" }),
            }));
            const unexpected = [];
            page.on("dialog", (d) => { unexpected.push(d.message()); d.dismiss(); });
            await openProjects(page);
            await openPanel(page, fx.project.id);
            await page.locator("#projectArchiveToggle").click();
            await expect.poll(async () => (await (await request.get(
                `/api/projects/${fx.project.id}`)).json()).is_active).toBe(false);

            expect(unexpected).toEqual([]);
            // ...and the server still paused it.
            expect(await templateActive(request, fx.templates[0].id)).toBe(false);
        } finally {
            await cleanup(request, [fx]);
        }
    });
});

test.describe("Archiving a goal pauses its repeating tasks (#368) @noviewport", () => {
    // The pause is server-side on every path (pytest pins that). This
    // proves the /goals half: the user is TOLD which repeating tasks will
    // pause before the archive, only when there are any, and a failed
    // lookup never blocks the archive. Assertions read persisted state
    // back through the API.
    //
    // @noviewport: desktop only; the dialog is a browser confirm(), and
    // mobile is covered by Phase 6.

    const stamp = () =>
        `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const TAIL = "They resume when you unarchive the goal.";

    async function goalWith(request, { templates = 0 } = {}) {
        const s = stamp();
        const g = await request.post("/api/goals", {
            data: { title: `E2E 368 goal ${s}`, category: "work", priority: "should" },
        });
        expect(g.ok()).toBe(true);
        const goal = await g.json();
        const made = [];
        for (let i = 0; i < templates; i++) {
            const r = await request.post("/api/recurring", {
                data: { title: `E2E 368 routine ${i} ${s}`, frequency: "daily",
                        type: "work", goal_id: goal.id },
            });
            expect(r.ok()).toBe(true);
            made.push(await r.json());
        }
        return { goal, templates: made };
    }

    // Detach + soft-delete the templates so nothing references the goal,
    // then archive and hard-delete it (#349 requires both).
    async function cleanup(request, { goal, templates }) {
        for (const t of templates) {
            await request.patch(`/api/recurring/${t.id}`, { data: { goal_id: null } });
            await request.delete(`/api/recurring/${t.id}`);
        }
        await request.delete(`/api/goals/${goal.id}`);
        await request.delete(`/api/goals/${goal.id}/permanent`);
    }

    const goalActive = async (request, id) =>
        (await (await request.get("/api/goals?is_active=all")).json())
            .find((g) => g.id === id).is_active;

    const templateActive = async (request, id) =>
        (await (await request.get(`/api/recurring/${id}`)).json()).is_active;

    async function openGoal(page, id, filter = "active") {
        await page.goto("/goals?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.selectOption("#filterArchived", filter);
        await page.locator(`.goal-card[data-goal-id="${id}"]`).click();
        await expect(page.locator("#goalDetailOverlay")).toBeVisible();
    }

    test("the archive confirm names the template; unarchive resumes it with no dialog", async ({
        page, request,
    }) => {
        const fx = await goalWith(request, { templates: 1 });
        try {
            await openGoal(page, fx.goal.id);
            const shown = [];
            page.once("dialog", (d) => { shown.push(d.message()); d.accept(); });
            await page.locator("#goalDelete").click();
            await expect.poll(() => goalActive(request, fx.goal.id)).toBe(false);

            expect(shown).toHaveLength(1);
            expect(shown[0]).toContain(`"${fx.templates[0].title}"`);
            expect(shown[0]).toContain(TAIL);
            expect(await templateActive(request, fx.templates[0].id)).toBe(false);

            const unexpected = [];
            page.on("dialog", (d) => { unexpected.push(d.message()); d.dismiss(); });
            await openGoal(page, fx.goal.id, "archived");
            await expect(page.locator("#goalDelete")).toHaveText(/^Unarchive$/);
            await page.locator("#goalDelete").click();
            await expect.poll(() => templateActive(request, fx.templates[0].id)).toBe(true);
            expect(unexpected).toEqual([]);
        } finally {
            await cleanup(request, fx);
        }
    });

    test("cancelling the confirm archives nothing", async ({ page, request }) => {
        const fx = await goalWith(request, { templates: 1 });
        try {
            await openGoal(page, fx.goal.id);
            page.once("dialog", (d) => d.dismiss());
            await page.locator("#goalDelete").click();
            await page.waitForTimeout(600);

            expect(await goalActive(request, fx.goal.id)).toBe(true);
            expect(await templateActive(request, fx.templates[0].id)).toBe(true);
        } finally {
            await cleanup(request, fx);
        }
    });

    test("archiving a goal with no repeating tasks shows no dialog", async ({
        page, request,
    }) => {
        const fx = await goalWith(request);
        try {
            const unexpected = [];
            page.on("dialog", (d) => { unexpected.push(d.message()); d.dismiss(); });
            await openGoal(page, fx.goal.id);
            await page.locator("#goalDelete").click();
            await expect.poll(() => goalActive(request, fx.goal.id)).toBe(false);
            expect(unexpected).toEqual([]);
        } finally {
            await cleanup(request, fx);
        }
    });

    test("lookup failure archives without a dialog", async ({ page, request }) => {
        // A 500, not route.abort: an aborted fetch trips apiFetch's
        // app-wide reload prompt (#353's ruling).
        const fx = await goalWith(request, { templates: 1 });
        try {
            await openGoal(page, fx.goal.id);
            await page.route("**/api/recurring", (r) =>
                r.fulfill({ status: 500, contentType: "application/json", body: "{}" }));
            const unexpected = [];
            page.on("dialog", (d) => { unexpected.push(d.message()); d.dismiss(); });
            await page.locator("#goalDelete").click();
            await expect.poll(() => goalActive(request, fx.goal.id)).toBe(false);
            expect(unexpected).toEqual([]);
            // The server still paused it; only the warning was lost.
            expect(await templateActive(request, fx.templates[0].id)).toBe(false);
        } finally {
            await page.unroute("**/api/recurring");
            await cleanup(request, fx);
        }
    });
});

test.describe("Import undo names the repeating tasks it pauses (#369) @noviewport", () => {
    // The pause is server-side (pytest pins it, incl. the parity test).
    // This proves the /settings half: Import History → Undo names the
    // repeating tasks before the undo, reads as before when there are
    // none, and a failed lookup never blocks the undo.
    //
    // @noviewport: desktop only; the dialog is a browser confirm(), and
    // mobile is covered by Phase 6.

    const stamp = () =>
        `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const TAIL = "They resume if you restore this import from the Recycle Bin.";

    // One imported project (its own batch), plus an optional template on it.
    async function importWith(request, { template = false } = {}) {
        const s = stamp();
        const source = `E2E 369 import ${s}`;
        const r = await request.post("/api/import/projects/confirm", {
            data: { candidates: [{ name: `E2E 369 project ${s}`, type: "work" }], source },
        });
        expect(r.ok()).toBe(true);
        const project = (await r.json()).projects[0];
        const logs = await (await request.get("/api/settings/imports")).json();
        const batchId = logs.find((l) => l.source === source).batch_id;
        let rt = null;
        if (template) {
            const t = await request.post("/api/recurring", {
                data: { title: `E2E 369 routine ${s}`, frequency: "daily",
                        type: "work", project_id: project.id },
            });
            expect(t.ok()).toBe(true);
            rt = await t.json();
        }
        return { source, batchId, project, rt };
    }

    // Soft-delete the template, then undo (if still live) and purge the batch.
    async function cleanup(request, { batchId, rt }) {
        if (rt) await request.delete(`/api/recurring/${rt.id}`);
        await request.post(`/api/recycle-bin/undo/${batchId}`);
        await request.post(`/api/recycle-bin/purge/${batchId}`, {
            data: { confirmation: "DELETE" },
        });
    }

    const undoneAt = async (request, source) =>
        (await (await request.get("/api/settings/imports")).json())
            .find((l) => l.source === source).undone_at;

    const templateActive = async (request, id) =>
        (await (await request.get(`/api/recurring/${id}`)).json()).is_active;

    async function undoButton(page, source) {
        await page.goto("/settings?nosw=1");
        const btn = page.locator("#settingsImportBody tr", { hasText: source })
            .locator("button");
        await expect(btn).toHaveText("Undo");
        return btn;
    }

    test("the undo confirm names the template; OK undoes and pauses it", async ({
        page, request,
    }) => {
        const fx = await importWith(request, { template: true });
        try {
            const btn = await undoButton(page, fx.source);
            const shown = [];
            page.once("dialog", (d) => { shown.push(d.message()); d.accept(); });
            await btn.click();
            await expect.poll(() => undoneAt(request, fx.source)).not.toBeNull();

            expect(shown).toHaveLength(1);
            expect(shown[0]).toContain("Move this import to the recycle bin?");
            expect(shown[0]).toContain(
                `This will pause 1 repeating task: "${fx.rt.title}". ${TAIL}`);
            expect(await templateActive(request, fx.rt.id)).toBe(false);
        } finally {
            await cleanup(request, fx);
        }
    });

    test("an import with no repeating tasks gets today's confirm", async ({
        page, request,
    }) => {
        const fx = await importWith(request);
        try {
            const btn = await undoButton(page, fx.source);
            const shown = [];
            page.once("dialog", (d) => { shown.push(d.message()); d.accept(); });
            await btn.click();
            await expect.poll(() => undoneAt(request, fx.source)).not.toBeNull();

            expect(shown).toHaveLength(1);
            expect(shown[0]).toContain("Move this import to the recycle bin?");
            expect(shown[0]).not.toMatch(/repeating task/i);
        } finally {
            await cleanup(request, fx);
        }
    });

    test("cancel leaves the import live and the button usable", async ({
        page, request,
    }) => {
        const fx = await importWith(request, { template: true });
        try {
            const btn = await undoButton(page, fx.source);
            page.once("dialog", (d) => d.dismiss());
            await btn.click();
            await expect(btn).toHaveText("Undo");
            await expect(btn).toBeEnabled();

            expect(await undoneAt(request, fx.source)).toBeNull();
            expect(await templateActive(request, fx.rt.id)).toBe(true);
        } finally {
            await cleanup(request, fx);
        }
    });

    test("lookup failure falls back to today's confirm and still undoes", async ({
        page, request,
    }) => {
        // A 500, not route.abort: an aborted fetch trips apiFetch's
        // app-wide reload prompt (#353's ruling).
        const fx = await importWith(request, { template: true });
        try {
            const btn = await undoButton(page, fx.source);
            await page.route("**/api/recycle-bin/impact/**", (r) =>
                r.fulfill({ status: 500, contentType: "application/json", body: "{}" }));
            const shown = [];
            page.once("dialog", (d) => { shown.push(d.message()); d.accept(); });
            await btn.click();
            await expect.poll(() => undoneAt(request, fx.source)).not.toBeNull();

            expect(shown).toHaveLength(1);
            expect(shown[0]).toContain("Move this import to the recycle bin?");
            expect(shown[0]).not.toMatch(/repeating task/i);
            // The server still paused it; only the warning was lost.
            expect(await templateActive(request, fx.rt.id)).toBe(false);
        } finally {
            await page.unroute("**/api/recycle-bin/impact/**");
            await cleanup(request, fx);
        }
    });
});

test.describe("/completed lists completed tasks on load (#358)", () => {
    // #358: init()'s "is this the board?" test only matched
    // `.task-list[data-tier]`, so /completed (whose list carries
    // data-archived-list instead) took #270's panel-only branch and
    // returned before loadCompletedTasks() and setupNavTabs(). The list
    // filled only on the 55s poll, and the view tabs had no handler.
    async function completedPair(request) {
        const ids = {};
        for (const type of ["work", "personal"]) {
            const resp = await request.post("/api/tasks", {
                data: { title: `BUG358 ${type} card`, type, tier: "today" },
            });
            const task = await resp.json();
            await request.post(`/api/tasks/${task.id}/complete`);
            ids[type] = task.id;
        }
        return ids;
    }

    const card = (page, id) =>
        page.locator(`#tierDetailList .task-card[data-id="${id}"]`);

    test("cards and count render on load, not on the poll", async ({
        page, request,
    }) => {
        const ids = await completedPair(request);
        try {
            await page.goto("/completed?nosw=1");
            // 5s is far inside the 55s freshness poll, so the poll can't
            // be what makes this pass.
            await expect(card(page, ids.work)).toBeVisible({ timeout: 5000 });
            await expect(card(page, ids.personal)).toBeVisible();
            const rendered = await page
                .locator("#tierDetailList .task-card").count();
            await expect(page.locator("#tierDetailCount"))
                .toHaveText(String(rendered));
        } finally {
            await request.delete(`/api/tasks/${ids.work}`);
            await request.delete(`/api/tasks/${ids.personal}`);
        }
    });

    test("the Work / All view tabs filter the list", async ({
        page, request,
    }) => {
        const ids = await completedPair(request);
        try {
            await page.goto("/completed?nosw=1");
            await expect(card(page, ids.personal)).toBeVisible({ timeout: 5000 });

            await page.locator('.view-filter-btn[data-view="work"]').click();
            await expect(card(page, ids.work)).toBeVisible();
            await expect(card(page, ids.personal)).toHaveCount(0);
            await expect(page.locator('.view-filter-btn[data-view="work"]'))
                .toHaveClass(/active/);

            await page.locator('.view-filter-btn[data-view="all"]').click();
            await expect(card(page, ids.work)).toBeVisible();
            await expect(card(page, ids.personal)).toBeVisible();
        } finally {
            await request.delete(`/api/tasks/${ids.work}`);
            await request.delete(`/api/tasks/${ids.personal}`);
        }
    });
});

test.describe("Goals - a linked task opens the task panel (#372)", () => {
    // #372: the goal panel's Linked Tasks list rendered each task as inert
    // text. goals.html never included the task detail panel markup, so
    // there was nothing to open. Now the row opens the panel, stacked on
    // top of the goal panel (user decision 2026-10-03), and a save
    // refreshes the still-open goal panel through window.taskDetailAfterSave.
    //
    // Persisted state is read back through the API wherever a save is
    // involved (#347: a test that watches the UI alone can pass while the
    // request fails).

    const stamp = () =>
        `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

    async function makeGoal(request, s, suffix = "") {
        const r = await request.post("/api/goals", {
            data: { title: `E2E 372 goal ${s}${suffix}`, category: "work",
                    priority: "should" },
        });
        expect(r.ok()).toBe(true);
        return r.json();
    }

    async function fixture(request, { secondGoal = false } = {}) {
        const s = stamp();
        const goal = await makeGoal(request, s);
        const other = secondGoal ? await makeGoal(request, s, " B") : null;
        const t = await request.post("/api/tasks", {
            data: { title: `E2E 372 task ${s}`, type: "work", tier: "today",
                    goal_id: goal.id },
        });
        expect(t.ok()).toBe(true);
        const task = await t.json();
        return { goal, other, task };
    }

    // DELETE on a task is a soft delete that keeps goal_id, and
    // hard_delete_goal refuses while any row points at the goal, so the
    // link is nulled first.
    async function cleanup(request, { goal, other, task }) {
        await request.patch(`/api/tasks/${task.id}`,
                            { data: { goal_id: null } });
        await request.delete(`/api/tasks/${task.id}`);
        for (const g of [goal, other]) {
            if (!g) continue;
            await request.delete(`/api/goals/${g.id}`);
            await request.delete(`/api/goals/${g.id}/permanent`);
        }
    }

    const linkedRow = (page, title) =>
        page.locator("#linkedTasksList .linked-task-row")
            .filter({ hasText: title });

    async function openGoal(page, goalId, { filter } = {}) {
        await page.goto("/goals?nosw=1");
        await page.waitForLoadState("networkidle");
        if (filter) await page.selectOption("#filterArchived", filter);
        await page.locator(`.goal-card[data-goal-id="${goalId}"]`).click();
        await expect(page.locator("#goalDetailOverlay")).toBeVisible();
    }

    const taskPatch = (page, taskId) => page.waitForResponse((r) =>
        r.url().endsWith(`/api/tasks/${taskId}`)
        && r.request().method() === "PATCH");

    const apiTask = async (request, id) =>
        (await request.get(`/api/tasks/${id}`)).json();

    test("clicking a linked task stacks the task panel on the goal panel", async ({
        page, request,
    }) => {
        const fx = await fixture(request);
        try {
            await openGoal(page, fx.goal.id);
            await linkedRow(page, fx.task.title).click();
            await expect(page.locator("#detailOverlay")).toBeVisible();
            await expect(page.locator("#detailTitle"))
                .toHaveValue(fx.task.title);

            // Stacked, not underneath: the topmost element at the task
            // panel's centre belongs to the task overlay. A template that
            // moved the include above #goalDetailOverlay would flip this.
            const onTop = await page.evaluate(() => {
                const r = document.getElementById("detailPanel")
                    .getBoundingClientRect();
                const el = document.elementFromPoint(
                    r.left + r.width / 2, r.top + Math.min(r.height / 2, 200));
                return !!(el && el.closest("#detailOverlay"));
            });
            expect(onTop).toBe(true);

            await page.locator("#detailClose").click();
            await expect(page.locator("#detailOverlay")).toBeHidden();
            await expect(page.locator("#goalDetailOverlay")).toBeVisible();
        } finally {
            await cleanup(request, fx);
        }
    });

    test("saving from the panel refreshes the open goal panel", async ({
        page, request,
    }) => {
        const fx = await fixture(request);
        const renamed = `${fx.task.title} renamed`;
        try {
            await openGoal(page, fx.goal.id);
            await linkedRow(page, fx.task.title).click();
            await page.locator("#detailTitle").fill(renamed);
            const saved = taskPatch(page, fx.task.id);
            await page.locator("#detailForm button[type=submit]").click();
            expect((await saved).ok()).toBe(true);

            // No page.reload(): the goal panel's own list re-rendered.
            await expect(page.locator("#goalDetailOverlay")).toBeVisible();
            await expect(linkedRow(page, renamed)).toHaveCount(1);
            expect((await apiTask(request, fx.task.id)).title).toBe(renamed);
        } finally {
            await cleanup(request, fx);
        }
    });

    test("Enter on a focused linked row opens the panel", async ({
        page, request,
    }) => {
        const fx = await fixture(request);
        try {
            await openGoal(page, fx.goal.id);
            const row = linkedRow(page, fx.task.title);
            await expect(row).toHaveAttribute("role", "button");
            await expect(row).toHaveAttribute("tabindex", "0");
            await expect(row).toHaveAttribute(
                "aria-label", `Open task: ${fx.task.title}`);
            await row.focus();
            await page.keyboard.press("Enter");
            await expect(page.locator("#detailOverlay")).toBeVisible();
        } finally {
            await cleanup(request, fx);
        }
    });

    test("checkbox completes without opening the panel", async ({
        page, request,
    }) => {
        // The checkbox's click bubbles to the row; without a stop it
        // would complete the task AND pop the panel open.
        const fx = await fixture(request);
        try {
            await openGoal(page, fx.goal.id);
            await linkedRow(page, fx.task.title)
                .locator('input[type="checkbox"]').click();
            await expect.poll(async () =>
                (await apiTask(request, fx.task.id)).status).toBe("archived");
            await expect(page.locator("#detailOverlay")).toBeHidden();
        } finally {
            await cleanup(request, fx);
        }
    });

    test("Space on the checkbox does not open the panel", async ({
        page, request,
    }) => {
        // A keydown on the focused checkbox bubbles to the row's keydown
        // handler, which must ignore anything not aimed at the row itself.
        const fx = await fixture(request);
        try {
            await openGoal(page, fx.goal.id);
            await linkedRow(page, fx.task.title)
                .locator('input[type="checkbox"]').focus();
            await page.keyboard.press("Space");
            await expect.poll(async () =>
                (await apiTask(request, fx.task.id)).status).toBe("archived");
            await expect(page.locator("#detailOverlay")).toBeHidden();
        } finally {
            await cleanup(request, fx);
        }
    });

    test("re-goaling a task removes it from the open goal panel", async ({
        page, request,
    }) => {
        const fx = await fixture(request, { secondGoal: true });
        try {
            await openGoal(page, fx.goal.id);
            await expect(page.locator("#linkedTaskCount")).toHaveText("1");
            await linkedRow(page, fx.task.title).click();
            await page.selectOption("#detailGoal", fx.other.id);
            const saved = taskPatch(page, fx.task.id);
            await page.locator("#detailForm button[type=submit]").click();
            expect((await saved).ok()).toBe(true);

            await expect(linkedRow(page, fx.task.title)).toHaveCount(0);
            await expect(page.locator("#linkedTaskCount")).toHaveText("0");
            expect((await apiTask(request, fx.task.id)).goal_id)
                .toBe(fx.other.id);
        } finally {
            await cleanup(request, fx);
        }
    });

    test("#355: a task on an archived goal keeps its goal after a save", async ({
        page, request,
    }) => {
        // #372 is the first route into the panel from a page that LISTS
        // archived goals, so #355's guarantee is asserted from here too.
        // DELETE /api/goals/<id> is the Archive button's soft delete.
        const fx = await fixture(request);
        try {
            const ar = await request.delete(`/api/goals/${fx.goal.id}`);
            expect(ar.status()).toBe(204);
            await openGoal(page, fx.goal.id, { filter: "archived" });
            await linkedRow(page, fx.task.title).click();
            await expect(page.locator("#detailGoal")).toHaveValue(fx.goal.id);
            const saved = taskPatch(page, fx.task.id);
            await page.locator("#detailForm button[type=submit]").click();
            expect((await saved).ok()).toBe(true);
            expect((await apiTask(request, fx.task.id)).goal_id)
                .toBe(fx.goal.id);
        } finally {
            await cleanup(request, fx);
        }
    });
});

test.describe("Projects - a linked task opens the task panel (#372)", () => {
    // #372: task lines on /projects (on each card, and in the project
    // panel's list) were inert text. projects.html now hosts the task
    // detail panel, a line click opens it, and a save refreshes the page
    // and the still-open project panel through window.taskDetailAfterSave.
    // The card lines are also the #344 drag source, so a touch long-press
    // must still drag rather than open.

    const stamp = () =>
        `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

    async function fixture(request) {
        const s = stamp();
        const p = await request.post("/api/projects", {
            data: { name: `E2E 372 project ${s}`, type: "work" },
        });
        expect(p.ok()).toBe(true);
        const project = await p.json();
        const t = await request.post("/api/tasks", {
            data: { title: `E2E 372 task ${s}`, type: "work", tier: "today",
                    project_id: project.id },
        });
        expect(t.ok()).toBe(true);
        const task = await t.json();
        return { project, task };
    }

    // DELETE on a task or a project is a soft delete that keeps the
    // foreign key, so the link is nulled first.
    async function cleanup(request, { project, task }) {
        await request.patch(`/api/tasks/${task.id}`,
                            { data: { project_id: null } });
        await request.delete(`/api/tasks/${task.id}`);
        await request.delete(`/api/projects/${project.id}`);
    }

    const cardLine = (page, taskId) =>
        page.locator(`.project-card-task[data-task-id="${taskId}"]`);
    const sideLine = (page, title) =>
        page.locator("#projectTaskList .project-side-task")
            .filter({ hasText: title });

    async function openProjects(page, filter) {
        await page.goto("/projects?nosw=1");
        await page.waitForLoadState("networkidle");
        if (filter) await page.selectOption("#projectFilterActive", filter);
    }

    // The card's top-left corner is its name, never one of its task
    // lines — a centre click could land on a line and open the task.
    async function openProjectPanel(page, projectId) {
        await page.locator(`.project-card[data-project-id="${projectId}"]`)
            .click({ position: { x: 8, y: 8 } });
        await expect(page.locator("#projectDetailOverlay")).toBeVisible();
    }

    const taskPatch = (page, taskId) => page.waitForResponse((r) =>
        r.url().endsWith(`/api/tasks/${taskId}`)
        && r.request().method() === "PATCH");

    const apiTask = async (request, id) =>
        (await request.get(`/api/tasks/${id}`)).json();

    test("clicking a card task line opens only the task panel", async ({
        page, request,
    }) => {
        const fx = await fixture(request);
        try {
            await openProjects(page);
            await cardLine(page, fx.task.id).click();
            await expect(page.locator("#detailOverlay")).toBeVisible();
            await expect(page.locator("#detailTitle"))
                .toHaveValue(fx.task.title);
            // The line still stops its click from reaching the card.
            await expect(page.locator("#projectDetailOverlay")).toBeHidden();
        } finally {
            await cleanup(request, fx);
        }
    });

    test("a side-list task stacks on the project panel and refreshes on save", async ({
        page, request,
    }) => {
        const fx = await fixture(request);
        const renamed = `${fx.task.title} renamed`;
        try {
            await openProjects(page);
            await openProjectPanel(page, fx.project.id);
            await sideLine(page, fx.task.title).click();
            await expect(page.locator("#detailOverlay")).toBeVisible();

            const onTop = await page.evaluate(() => {
                const r = document.getElementById("detailPanel")
                    .getBoundingClientRect();
                const el = document.elementFromPoint(
                    r.left + r.width / 2, r.top + Math.min(r.height / 2, 200));
                return !!(el && el.closest("#detailOverlay"));
            });
            expect(onTop).toBe(true);

            await page.locator("#detailTitle").fill(renamed);
            const saved = taskPatch(page, fx.task.id);
            await page.locator("#detailForm button[type=submit]").click();
            expect((await saved).ok()).toBe(true);

            // No reload: the open project panel's list re-rendered.
            await expect(sideLine(page, renamed)).toHaveCount(1);
            expect((await apiTask(request, fx.task.id)).title).toBe(renamed);
            await expect(page.locator("#detailOverlay")).toBeHidden();
            await expect(page.locator("#projectDetailOverlay")).toBeVisible();
        } finally {
            await cleanup(request, fx);
        }
    });

    test("completing from the panel refreshes the side list", async ({
        page, request,
    }) => {
        // The page lists active tasks only, so a completed task must
        // leave the side list and the summary count must drop.
        const fx = await fixture(request);
        try {
            await openProjects(page);
            await openProjectPanel(page, fx.project.id);
            await expect(page.locator("#projectTaskCount")).toHaveText("1");
            await sideLine(page, fx.task.title).click();
            await page.locator("#detailComplete").click();

            await expect.poll(async () =>
                (await apiTask(request, fx.task.id)).status).toBe("archived");
            await expect(sideLine(page, fx.task.title)).toHaveCount(0);
            await expect(page.locator("#projectTaskCount")).toHaveText("0");
        } finally {
            await cleanup(request, fx);
        }
    });

    test("Enter on a focused card line opens the panel", async ({
        page, request,
    }) => {
        const fx = await fixture(request);
        try {
            await openProjects(page);
            const line = cardLine(page, fx.task.id);
            await expect(line).toHaveAttribute("role", "button");
            await expect(line).toHaveAttribute("tabindex", "0");
            await expect(line).toHaveAttribute(
                "aria-label", `Open task: ${fx.task.title}`);
            await line.focus();
            await page.keyboard.press("Enter");
            await expect(page.locator("#detailOverlay")).toBeVisible();
            await expect(page.locator("#projectDetailOverlay")).toBeHidden();
        } finally {
            await cleanup(request, fx);
        }
    });

    test("#355: a task on an archived project keeps its project after a save", async ({
        page, request,
    }) => {
        // #372 is the first route into the panel from a page that LISTS
        // archived projects, so #355's guarantee is asserted from here.
        const fx = await fixture(request);
        try {
            const ar = await request.patch(`/api/projects/${fx.project.id}`,
                                           { data: { is_active: false } });
            expect(ar.ok()).toBe(true);
            await openProjects(page, "archived");
            await cardLine(page, fx.task.id).click();
            await expect(page.locator("#detailProject"))
                .toHaveValue(fx.project.id);
            const saved = taskPatch(page, fx.task.id);
            await page.locator("#detailForm button[type=submit]").click();
            expect((await saved).ok()).toBe(true);
            expect((await apiTask(request, fx.task.id)).project_id)
                .toBe(fx.project.id);
        } finally {
            await cleanup(request, fx);
        }
    });

    test("a long-press does not open the panel; a tap does", async ({
        page, request,
    }) => {
        // Synthetic TouchEvents never synthesize a click, so the test
        // dispatches the click a touch browser would send on release.
        const fx = await fixture(request);
        try {
            await openProjects(page);
            await expect(cardLine(page, fx.task.id)).toBeVisible();

            const longPressOpened = await page.evaluate(async (id) => {
                const fire = (el, type, x, y, released) => {
                    const touch = new Touch({
                        identifier: 1, target: el, clientX: x, clientY: y,
                    });
                    el.dispatchEvent(new TouchEvent(type, {
                        bubbles: true, cancelable: true,
                        touches: released ? [] : [touch],
                        targetTouches: released ? [] : [touch],
                        changedTouches: [touch],
                    }));
                };
                const li = document.querySelector(
                    `.project-card-task[data-task-id="${id}"]`);
                const r = li.getBoundingClientRect();
                const x = r.left + 10;
                const y = r.top + r.height / 2;
                fire(li, "touchstart", x, y, false);
                await new Promise((s) => setTimeout(s, 600));  // past the hold
                fire(document, "touchend", x, y, true);
                li.click();
                await new Promise((s) => setTimeout(s, 100));
                return document.getElementById("detailOverlay")
                    .style.display !== "none";
            }, fx.task.id);
            expect(longPressOpened).toBe(false);

            // Releasing over the line's own card is a same-project drop:
            // nothing moves.
            expect((await apiTask(request, fx.task.id)).project_id)
                .toBe(fx.project.id);

            // Past the guard window, a quick tap opens the panel.
            await page.waitForTimeout(800);
            await page.evaluate(async (id) => {
                const fire = (el, type, x, y, released) => {
                    const touch = new Touch({
                        identifier: 1, target: el, clientX: x, clientY: y,
                    });
                    el.dispatchEvent(new TouchEvent(type, {
                        bubbles: true, cancelable: true,
                        touches: released ? [] : [touch],
                        targetTouches: released ? [] : [touch],
                        changedTouches: [touch],
                    }));
                };
                const li = document.querySelector(
                    `.project-card-task[data-task-id="${id}"]`);
                const r = li.getBoundingClientRect();
                const x = r.left + 10;
                const y = r.top + r.height / 2;
                fire(li, "touchstart", x, y, false);
                await new Promise((s) => setTimeout(s, 120));
                fire(document, "touchend", x, y, true);
                li.click();
            }, fx.task.id);
            await expect(page.locator("#detailOverlay")).toBeVisible();
        } finally {
            await cleanup(request, fx);
        }
    });
});

test.describe("Panel hosts /goals and /projects keep their state (#372 review)", () => {
    // Found by #372's final review. Hosting the task panel made these
    // pages register window.taskDetailAfterSave, and app.js's 60s poll,
    // tab-visible and cross-tab refreshes all call loadTasks(), which
    // hands off to that hook. So the hook is a page-wide refresh, not
    // just a post-save one: it must keep page state, never tear a live
    // drag out from under the finger, and never throw. Separately, the
    // panel's Goal dropdown needs goal_filter_helpers.js for the #142
    // work/personal split, as on the board and /calendar.

    const stamp = () =>
        `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

    async function post(request, url, data) {
        const r = await request.post(url, { data });
        expect(r.ok()).toBe(true);
        return r.json();
    }

    test("a personal task's Goal dropdown leaves out work goals on /goals and /projects (#142)", async ({
        page, request,
    }) => {
        const s = stamp();
        const home = await post(request, "/api/goals", {
            title: `E2E 372r health ${s}`, category: "health",
            priority: "should" });
        const work = await post(request, "/api/goals", {
            title: `E2E 372r work ${s}`, category: "work",
            priority: "should" });
        const project = await post(request, "/api/projects", {
            name: `E2E 372r personal ${s}`, type: "personal" });
        const task = await post(request, "/api/tasks", {
            title: `E2E 372r task ${s}`, type: "personal", tier: "today",
            goal_id: home.id, project_id: project.id });
        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.locator(`.goal-card[data-goal-id="${home.id}"]`)
                .click({ position: { x: 8, y: 8 } });
            await page.locator("#linkedTasksList .linked-task-row")
                .filter({ hasText: task.title }).click();
            await expect(page.locator("#detailOverlay")).toBeVisible();
            await expect(page.locator(
                `#detailGoal option[value="${home.id}"]`)).toHaveCount(1);
            await expect(page.locator(
                `#detailGoal option[value="${work.id}"]`)).toHaveCount(0);

            await page.goto("/projects?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.locator(
                `.project-card-task[data-task-id="${task.id}"]`).click();
            await expect(page.locator("#detailOverlay")).toBeVisible();
            await expect(page.locator(
                `#detailGoal option[value="${work.id}"]`)).toHaveCount(0);
        } finally {
            await request.patch(`/api/tasks/${task.id}`,
                { data: { goal_id: null, project_id: null } });
            await request.delete(`/api/tasks/${task.id}`);
            await request.delete(`/api/projects/${project.id}`);
            for (const g of [home, work]) {
                await request.delete(`/api/goals/${g.id}`);
                await request.delete(`/api/goals/${g.id}/permanent`);
            }
        }
    });

    test("/projects: an expanded card stays expanded across the poll's refresh", async ({
        page, request,
    }) => {
        const s = stamp();
        const project = await post(request, "/api/projects", {
            name: `E2E 372r many ${s}`, type: "work" });
        const tasks = [];
        for (let i = 0; i < 6; i++) {
            tasks.push(await post(request, "/api/tasks", {
                title: `E2E 372r line ${i} ${s}`, type: "work",
                tier: "today", project_id: project.id }));
        }
        try {
            await page.goto("/projects?nosw=1");
            await page.waitForLoadState("networkidle");
            const card = page.locator(
                `.project-card[data-project-id="${project.id}"]`);
            await card.locator(".project-card-toggle").click();
            await expect(card.locator(".project-card-task")).toHaveCount(6);
            await expect(card.locator(".project-card-task").nth(5))
                .toBeVisible();
            // The 60s poll's path: app.js loadTasks() → the page hook.
            await page.evaluate(() => loadTasks());
            await page.evaluate(() => window.taskDetailAfterSave());
            await expect(card.locator(".project-card-task").nth(5))
                .toBeVisible();
            await expect(card.locator(".project-card-toggle"))
                .toHaveText("Hide");
        } finally {
            for (const t of tasks) {
                await request.patch(`/api/tasks/${t.id}`,
                    { data: { project_id: null } });
                await request.delete(`/api/tasks/${t.id}`);
            }
            await request.delete(`/api/projects/${project.id}`);
        }
    });

    test("/projects: a refresh never re-renders under a live task drag", async ({
        page,
    }) => {
        await page.goto("/projects?nosw=1");
        await page.waitForLoadState("networkidle");
        await expect(page.locator(".project-card-task[data-task-id]").first())
            .toBeVisible({ timeout: 10000 });
        const kept = await page.evaluate(async () => {
            const li = document.querySelector(
                ".project-card-task[data-task-id]");
            li.dispatchEvent(new DragEvent("dragstart",
                { dataTransfer: new DataTransfer(), bubbles: true }));
            await window.taskDetailAfterSave();
            const still = document.contains(li);
            li.dispatchEvent(new DragEvent("dragend", { bubbles: true }));
            return still;
        });
        expect(kept).toBe(true);
    });

    test("/goals: a refresh never re-renders under a live project drag", async ({
        page, request,
    }) => {
        const s = stamp();
        const goal = await post(request, "/api/goals", {
            title: `E2E 372r goal ${s}`, category: "work",
            priority: "should" });
        const project = await post(request, "/api/projects", {
            name: `E2E 372r chip ${s}`, type: "work", goal_id: goal.id });
        try {
            await page.goto("/goals?nosw=1");
            await page.waitForLoadState("networkidle");
            const kept = await page.evaluate(async (pid) => {
                const li = document.querySelector(
                    `.goal-card-project[data-project-id="${pid}"]`);
                li.dispatchEvent(new DragEvent("dragstart",
                    { dataTransfer: new DataTransfer(), bubbles: true }));
                await window.taskDetailAfterSave();
                const still = document.contains(li);
                li.dispatchEvent(new DragEvent("dragend", { bubbles: true }));
                return still;
            }, project.id);
            expect(kept).toBe(true);
        } finally {
            await request.patch(`/api/projects/${project.id}`,
                { data: { goal_id: null } });
            await request.delete(`/api/projects/${project.id}`);
            await request.delete(`/api/goals/${goal.id}`);
            await request.delete(`/api/goals/${goal.id}/permanent`);
        }
    });

    for (const path of ["/goals", "/projects"]) {
        test(`${path}: a failed background refresh does not throw`, async ({
            page,
        }) => {
            await page.goto(`${path}?nosw=1`);
            await page.waitForLoadState("networkidle");
            await page.route("**/api/**", (route) => route.abort());
            // Resolves rather than rejecting: an unhandled rejection from
            // the poll would be reported as a client error every minute
            // the network is down.
            const outcome = await page.evaluate(() =>
                window.taskDetailAfterSave().then(() => "resolved",
                                                  (e) => `rejected: ${e}`));
            expect(outcome).toBe("resolved");
        });
    }

    test("/projects: in Select mode a click on a task line selects the card", async ({
        page, request,
    }) => {
        // Bulk mode is for selecting cards; the task lines cover much of
        // a card, so they must not hijack that click into opening a task.
        const s = stamp();
        const project = await post(request, "/api/projects", {
            name: `E2E 372r bulk ${s}`, type: "work" });
        const task = await post(request, "/api/tasks", {
            title: `E2E 372r bulk task ${s}`, type: "work", tier: "today",
            project_id: project.id });
        try {
            await page.goto("/projects?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.locator("#projectsBulkToggle").click();
            await page.locator(
                `.project-card-task[data-task-id="${task.id}"]`).click();
            await expect(page.locator("#detailOverlay")).toBeHidden();
            await expect(page.locator(
                `.project-card[data-project-id="${project.id}"]`))
                .toHaveClass(/bulk-selected/);
        } finally {
            await request.patch(`/api/tasks/${task.id}`,
                { data: { project_id: null } });
            await request.delete(`/api/tasks/${task.id}`);
            await request.delete(`/api/projects/${project.id}`);
        }
    });
});
