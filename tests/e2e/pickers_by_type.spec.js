/**
 * #483: pickers list only projects of the item's own type.
 *
 * Since #475 the server refuses a task or repeating task on a project of the
 * other type, but five pickers listed every project, so the pick failed on
 * Save: the /recurring editor and its bulk Project ▾, the /import review
 * row, the /plan row, and the board's bulk Project ▾ in the All view.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

async function projectsByType(request) {
    const all = await (await request.get("/api/projects")).json();
    return {
        work: all.filter((p) => p.type === "work").map((p) => p.name).sort(),
        personal: all.filter((p) => p.type === "personal").map((p) => p.name).sort(),
    };
}

const optionNames = (loc) => loc.evaluate((sel) =>
    [...sel.options].filter((o) => o.value).map((o) => o.textContent.trim()).sort());

test.describe("#483 pickers offer only the item's type", () => {
    test("/recurring editor: Project follows Type", async ({ page, request }) => {
        const want = await projectsByType(request);
        await page.goto("/recurring?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.click("#recurringNew");
        await expect(page.locator("#recurEditOverlay")).toBeVisible();
        await expect(page.locator("#recurEditType")).toHaveValue("work");
        expect(await optionNames(page.locator("#recurEditProject"))).toEqual(want.work);
        await page.selectOption("#recurEditType", "personal");
        expect(await optionNames(page.locator("#recurEditProject"))).toEqual(want.personal);
    });

    test("/recurring editor: a Type change clears a picked project of the other type",
        async ({ page, request }) => {
            const all = await (await request.get("/api/projects")).json();
            const work = all.find((p) => p.type === "work");
            await page.goto("/recurring?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.click("#recurringNew");
            await page.selectOption("#recurEditProject", work.id);
            await page.selectOption("#recurEditType", "personal");
            await expect(page.locator("#recurEditProject")).toHaveValue("");
        });

    test("/recurring Select → Project ▾: the selection's type, or 'both types'", async ({ page, request }) => {
        const want = await projectsByType(request);
        const made = [];
        for (const type of ["work", "personal"]) {
            const r = await request.post("/api/recurring", {
                data: { title: `E2E483 ${type} tmpl`, type, frequency: "daily" },
            });
            expect(r.status()).toBe(201);
            made.push(await r.json());
        }
        try {
            await page.goto("/recurring?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.click("#recurringSelectToggle");
            const tick = (t) => page.locator(`.recurring-row input[data-id="${t.id}"]`).check();
            await tick(made[0]);
            await page.click("#recurringBulkProject");
            const menu = page.locator(".bulk-dropdown").last();
            await expect(menu).toBeVisible();
            const names = (await menu.locator("button").allTextContents())
                .map((s) => s.trim()).filter((s) => s !== "(none)").sort();
            expect(names).toEqual(want.work);
            await page.keyboard.press("Escape");
            await tick(made[1]);
            await page.click("#recurringBulkProject");
            await expect(page.locator(".bulk-dropdown").last())
                .toContainText("both Work and Personal");
        } finally {
            for (const t of made) await request.delete(`/api/recurring/${t.id}`);
        }
    });

    test("/import review: a row's Project follows its Type", async ({ page, request }) => {
        const want = await projectsByType(request);
        await page.route("**/api/import/tasks/parse", (r) => r.fulfill({ json: {
            total: 1, candidates: [{ title: "E2E483 row", type: "work", tier: "inbox" }],
        } }));
        await page.goto("/import?nosw=1");
        await page.click("#importTasksBtn");
        await page.fill("#importText", "E2E483 row");
        await page.click("#importParseTasksBtn");
        const proj = page.locator(".import-candidate-project").first();
        await expect(proj).toBeAttached();
        expect(await optionNames(proj)).toEqual(want.work);
        await page.locator(".import-candidate-type").first().selectOption("personal");
        expect(await optionNames(proj)).toEqual(want.personal);
    });

    test("/plan row: the task's type only", async ({ page, request }) => {
        const want = await projectsByType(request);
        await page.route("**/api/planner/weekly", (r) => r.fulfill({ json: {
            start_date: "2026-10-19", end_date: "2026-10-25",
            active_count: 1, stale_freezer_count: 0, velocity_warning: null,
            goal_hints: [], day_by_day_plan: {}, stale_freezer_review: [],
            per_task_suggestions: [{
                task_id: "e2e483-plan", title: "E2E483 plan row", task_type: "personal",
                action: "keep", suggested_tier: null, suggested_due_date: null,
                suggested_project_id: null, suggested_goal_id: null, reason: "483",
            }],
        } }));
        await page.goto("/plan?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.click("#planGenerateBtn");
        const sel = page.locator('.plan-row [data-field="project"]').first();
        await expect(sel).toBeVisible();
        expect(await optionNames(sel)).toEqual(want.personal);
    });

    test("board All view: Project ▾ lists the selected tasks' type, or says both",
        async ({ page, request }) => {
            const want = await projectsByType(request);
            const made = [];
            for (const type of ["work", "personal"]) {
                const r = await request.post("/api/tasks", {
                    data: { title: `E2E483 ${type} card`, type, tier: "today" },
                });
                made.push(await r.json());
            }
            try {
                await page.goto("/tier/today?nosw=1");
                await page.waitForLoadState("networkidle");
                const tick = (t) => page.locator(`.task-card[data-id="${t.id}"] .bulk-select-check`).check();
                await tick(made[0]);
                await page.click("#bulkActionProject");
                const menu = page.locator(".bulk-dropdown").last();
                await expect(menu).toBeVisible();
                const names = (await menu.locator("button").allTextContents())
                    .map((s) => s.trim()).filter((s) => s !== "(no project)").sort();
                expect(names).toEqual(want.work);
                await page.keyboard.press("Escape");
                await tick(made[1]);
                await page.click("#bulkActionProject");
                await expect(page.locator(".bulk-dropdown").last())
                    .toContainText("both Work and Personal");
            } finally {
                for (const t of made) await request.delete(`/api/tasks/${t.id}`);
            }
        });
});
