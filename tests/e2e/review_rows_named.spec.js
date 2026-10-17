/**
 * #489: every control on a review screen has a name. #458's check reads each
 * page at load, but the review screens only build their rows after an upload
 * or a parse, so it never saw them: a screen reader heard "checkbox, not
 * checked" per row with no task named. Each screen is brought up with its
 * paid call stubbed, then checked with the same rule (a11y_names.js); a
 * row's tick box must name the row's title too.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server
const { unnamedControls } = require("./a11y_names");

const PNG = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    "base64");

const expectAllNamed = async (page) => expect(await page.evaluate(unnamedControls)).toEqual({});

test.describe("#489 review screens name every control", () => {
    test("/import tasks review", async ({ page }) => {
        await page.route("**/api/import/tasks/parse", (route) => route.fulfill({ json: {
            total: 1, candidates: [{ title: "E2E489 call the dentist", type: "work", tier: "inbox" }],
        } }));
        await page.goto("/import?nosw=1");
        await page.click("#importTasksBtn");
        await page.fill("#importText", "E2E489 call the dentist");
        await page.click("#importParseTasksBtn");
        await expect(page.locator("#importReview")).toBeVisible();
        await expectAllNamed(page);
        await expect(page.locator(".import-candidate input[type=checkbox]").first())
            .toHaveAccessibleName(/E2E489 call the dentist/);
    });

    test("/import goals review", async ({ page }) => {
        await page.route("**/api/import/goals/parse", (route) => route.fulfill({ json: {
            total: 1, candidates: [{ title: "E2E489 run a half", category: "health",
                priority: "should", status: "not_started", target_quarter: "", actions: "", notes: "" }],
        } }));
        await page.goto("/import?nosw=1");
        await page.click("#importGoalsBtn");
        await page.setInputFiles("#importFile", { name: "goals.xlsx",
            mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("x") });
        await page.click("#importParseGoalsBtn");
        await expect(page.locator("#importReview")).toBeVisible();
        await expectAllNamed(page);
        await expect(page.locator(".import-candidate input[type=checkbox]").first())
            .toHaveAccessibleName(/E2E489 run a half/);
    });

    test("/import projects review", async ({ page }) => {
        await page.route("**/api/import/projects/parse", (route) => route.fulfill({ json: {
            total: 1, candidates: [{ name: "E2E489 kitchen", type: "work", status: "not_started" }],
        } }));
        await page.goto("/import?nosw=1");
        await page.click("#importProjectsTextBtn");
        await page.fill("#importProjectsText", "E2E489 kitchen");
        await page.click("#importParseProjectsTextBtn");
        await expect(page.locator("#importReview")).toBeVisible();
        await expectAllNamed(page);
        await expect(page.locator(".import-candidate input[type=checkbox]").first())
            .toHaveAccessibleName(/E2E489 kitchen/);
    });

    for (const kind of ["tasks", "goals", "projects"]) {
        test(`/scan ${kind} review`, async ({ page }) => {
            const candidates = {
                tasks: [{ title: "E2E489 scanned", type: "work", included: true }],
                goals: [{ title: "E2E489 scanned", category: "health", priority: "should",
                    target_quarter: "", actions: "", included: true }],
                projects: [{ title: "E2E489 scanned", type: "work", target_quarter: "", included: true }],
            }[kind];
            await page.route("**/api/scan/upload", (route) => route.fulfill({
                json: { ocr_text: "x", kind, candidates } }));
            await page.goto("/scan?nosw=1");
            await page.locator(`input[name=parseAs][value=${kind}]`).check();
            await page.setInputFiles("#scanFile", { name: "n.png", mimeType: "image/png", buffer: PNG });
            await page.click("#scanSubmitBtn");
            await expect(page.locator("#scanReview")).toBeVisible({ timeout: 10000 });
            await expectAllNamed(page);
            await expect(page.locator(".scan-candidate input[type=checkbox]").first())
                .toHaveAccessibleName(/E2E489 scanned/);
        });
    }

    test("/voice-memo review", async ({ page }) => {
        // Real MediaRecorder on the fake mic; only the upload/parse is stubbed.
        await page.route("**/api/voice-memo", (route) => route.fulfill({ json: {
            transcript: "stubbed",
            candidates: [{ title: "E2E489 spoken", type: "work", tier: "inbox", due_date: null,
                route: "task", is_task: true }],
        } }));
        await page.goto("/voice-memo?nosw=1");
        await page.click("#voiceRecordBtn");
        await expect(page.locator("#voiceStopBtn")).toBeVisible({ timeout: 5000 });
        await page.waitForTimeout(600);
        await page.click("#voiceStopBtn");
        await expect(page.locator("#voiceCandidates .voice-candidate")).toHaveCount(1, { timeout: 10000 });
        await expectAllNamed(page);
        await expect(page.locator(".voice-candidate input[type=checkbox]").first())
            .toHaveAccessibleName(/E2E489 spoken/);
    });

    test("/plan review rows", async ({ page }) => {
        await page.route("**/api/planner/weekly", (route) => route.fulfill({ json: {
            start_date: "2026-10-19", end_date: "2026-10-25",
            active_count: 1, stale_freezer_count: 0, velocity_warning: null,
            goal_hints: [], day_by_day_plan: {}, stale_freezer_review: [],
            per_task_suggestions: [{ task_id: "e2e489-a", title: "E2E489 planned", action: "move",
                suggested_tier: "this_week", suggested_due_date: "2026-10-21",
                suggested_project_id: null, suggested_goal_id: null, reason: "489" }],
        } }));
        await page.goto("/plan?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.click("#planGenerateBtn");
        await expect(page.locator(".plan-row")).toHaveCount(1);
        await expectAllNamed(page);
    });

    test("board 💡 Auto-categorize rows", async ({ page, request }) => {
        const task = await (await request.post("/api/tasks", {
            data: { title: "E2E489 categorize me", type: "work", tier: "inbox" } })).json();
        try {
            await page.route("**/api/inbox/categorize", (route) => route.fulfill({ json: {
                count: 1, capped: false, suggestions: [{ task_id: task.id, title: task.title,
                    suggested_tier: "this_week", suggested_project_id: null, suggested_goal_id: null,
                    suggested_due_date: null, suggested_type: "work", reason: "489" }],
            } }));
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.click("#autoCategorizeBtn");
            await expect(page.locator(`#autoCategorizeRows tr[data-task-id="${task.id}"]`)).toBeVisible();
            await expectAllNamed(page);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("/reflection proposal rows", async ({ page }) => {
        await page.route("**/api/reflection", (route) => {
            if (route.request().method() !== "POST") return route.fallback();
            return route.fulfill({ status: 201, json: {
                id: "00000000-0000-0000-0000-000000000489", iso_week: "2026-W42",
                input_mode: "typed", transcript: "489.", ai_cost_usd: null,
                proposed_actions: {
                    explicit: [{ op: "create", entity: "task", target: "E2E489 reflected", reason: "a" }],
                    suggested: [{ op: "update", entity: "task", target: "E2E489 other", reason: "b" }],
                },
                raw_segments: [], is_archived: false, is_active: true,
            } });
        });
        try {
            await page.goto("/reflection?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.locator("#reflText").fill("489.");
            await page.locator("#reflAnalyzeBtn").click();
            await expect(page.locator("#reflStateReview")).toBeVisible({ timeout: 10000 });
            await expectAllNamed(page);
        } finally {
            await page.unroute("**/api/reflection").catch(() => {});
            await page.evaluate(() => fetch("/api/reflection/draft",
                { method: "DELETE", credentials: "same-origin" })).catch(() => {});
        }
    });

    test("/strength-forge log form", async ({ page }) => {
        await page.goto("/strength-forge?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.getByRole("button", { name: "🔁 Split" }).click();
        await page.locator('.sf-panel[data-tab="split"] .sf-log-detail-btn').click();
        await expect(page.locator(".sf-logform-overlay")).toBeVisible();
        await expectAllNamed(page);
    });
});
