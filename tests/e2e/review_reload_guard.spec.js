/**
 * #473: a deploy reload must not wipe a review screen that cost a paid call.
 *
 * base.html applies a new service worker (reloading the page) unless
 * window.__userIsBusy() objects. #446 covered every panel and pop-up; the
 * /scan, /import, /plan and /reflection reviews are part of the page, so
 * they publish to window.reloadGuard instead. Each test holds the paid
 * answer to see the in-flight case, then checks the review, then the quiet
 * case once there is nothing left to lose. (The idle first screen of each
 * page is #446's "idle pages are not busy" test.)
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const busy = (page) => page.evaluate(() => {
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    return window.__userIsBusy();
});

// Hold a stubbed answer until release() — the "still thinking" window.
async function held(page, pattern, json, { method = "POST", status = 200 } = {}) {
    let release;
    const gate = new Promise((r) => { release = r; });
    let seen = false;
    await page.route(pattern, async (route) => {
        if (route.request().method() !== method) return route.fallback();
        seen = true;
        await gate;
        await route.fulfill({ status, json }).catch(() => {});
    });
    return { release: () => release(), seen: () => seen };
}

const PNG = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    "base64");

test.describe("#473 review screens hold off a deploy reload", () => {
    test("/scan: busy while reading the image and on the review, not once added", async ({ page }) => {
        const upload = await held(page, "**/api/scan/upload", {
            ocr_text: "x", kind: "tasks",
            candidates: [{ title: "E2E473 scanned", type: "work", included: true }],
        });
        await page.route("**/api/scan/confirm", (route) => route.fulfill({ json: { created: 1 } }));
        await page.goto("/scan?nosw=1");
        await page.setInputFiles("#scanFile", { name: "note.png", mimeType: "image/png", buffer: PNG });
        await page.locator("#scanSubmitBtn").click();
        await expect.poll(upload.seen).toBe(true);
        expect(await busy(page), "upload in flight").toBe(true);

        upload.release();
        await expect(page.locator("#scanReview")).toBeVisible();
        expect(await busy(page), "on the review").toBe(true);

        await page.locator("#scanConfirmAll").click();
        await expect(page.locator("#scanDone")).toBeVisible();
        expect(await busy(page), "added: nothing to lose").toBe(false);
    });

    test("/scan: Rescan back to the upload screen is not busy", async ({ page }) => {
        await page.route("**/api/scan/upload", (route) => route.fulfill({ json: {
            ocr_text: "x", kind: "tasks", candidates: [{ title: "E2E473 scanned", type: "work", included: true }],
        } }));
        await page.goto("/scan?nosw=1");
        await page.setInputFiles("#scanFile", { name: "note.png", mimeType: "image/png", buffer: PNG });
        await page.locator("#scanSubmitBtn").click();
        await expect(page.locator("#scanReview")).toBeVisible();
        await page.locator("#scanRescan").click();
        await expect(page.locator("#scanReview")).toBeHidden();
        expect(await busy(page)).toBe(false);
    });

    test("/import: busy while parsing, on the review and the summary, not once imported", async ({ page }) => {
        const parse = await held(page, "**/api/import/tasks/parse", {
            total: 1, candidates: [{ title: "E2E473 imported", type: "work", tier: "inbox" }],
        });
        await page.route("**/api/import/*/confirm", (route) => route.fulfill({ json: { created: 1 } }));
        await page.goto("/import?nosw=1");
        await page.click("#importTasksBtn");
        await page.fill("#importText", "E2E473 imported");
        await page.click("#importParseTasksBtn");
        await expect.poll(parse.seen).toBe(true);
        expect(await busy(page), "parse in flight").toBe(true);

        parse.release();
        await expect(page.locator("#importReview")).toBeVisible();
        expect(await busy(page), "on the review").toBe(true);

        await page.click("#importConfirmAll");
        await expect(page.locator("#importConfirm")).toBeVisible();
        expect(await busy(page), "on the summary").toBe(true);

        await page.click("#importFinalConfirm");
        await expect(page.locator("#importDone")).toBeVisible();
        expect(await busy(page), "imported").toBe(false);
    });

    test("/import: Start Over leaves nothing to protect", async ({ page }) => {
        await page.route("**/api/import/tasks/parse", (route) => route.fulfill({ json: {
            total: 1, candidates: [{ title: "E2E473 imported", type: "work", tier: "inbox" }],
        } }));
        await page.goto("/import?nosw=1");
        await page.click("#importTasksBtn");
        await page.fill("#importText", "E2E473 imported");
        await page.click("#importParseTasksBtn");
        await expect(page.locator("#importReview")).toBeVisible();
        await page.click("#importStartOver");
        expect(await busy(page)).toBe(false);
    });

    test("/plan: busy while planning and while a row is undecided, not once all are", async ({ page }) => {
        const plan = await held(page, "**/api/planner/weekly", {
            start_date: "2026-10-19", end_date: "2026-10-25",
            active_count: 2, stale_freezer_count: 0, velocity_warning: null,
            goal_hints: [], day_by_day_plan: {}, stale_freezer_review: [],
            per_task_suggestions: ["e2e473-a", "e2e473-b"].map((id) => ({
                task_id: id, title: "E2E473 " + id, action: "keep",
                suggested_tier: null, suggested_due_date: null,
                suggested_project_id: null, suggested_goal_id: null, reason: "473",
            })),
        });
        await page.route("**/api/planner/ignore/*", (route) => route.fulfill({ json: { ok: true } }));
        await page.goto("/plan?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.click("#planGenerateBtn");
        await expect.poll(plan.seen).toBe(true);
        expect(await busy(page), "planning").toBe(true);

        plan.release();
        const rows = page.locator(".plan-row");
        await expect(rows).toHaveCount(2);
        expect(await busy(page), "two rows pending").toBe(true);

        await rows.nth(0).locator(".plan-ignore").click();
        await expect(rows.nth(0).locator(".plan-ignore")).toHaveText("Ignored");
        expect(await busy(page), "one row pending").toBe(true);

        await rows.nth(1).locator(".plan-ignore").click();
        await expect(rows.nth(1).locator(".plan-ignore")).toHaveText("Ignored");
        expect(await busy(page), "every row decided").toBe(false);
    });

    test("/reflection: busy while analyzing and on the review, not once applied", async ({ page }) => {
        const submit = await held(page, "**/api/reflection", {
            id: "00000000-0000-0000-0000-000000000473", iso_week: "2026-W42",
            input_mode: "typed", transcript: "473.", ai_cost_usd: null,
            proposed_actions: {
                explicit: [{ op: "create", entity: "task", target: "E2E473 reflected", reason: "a" }],
                suggested: [],
            },
            raw_segments: [], is_archived: false, is_active: true,
        }, { status: 201 });
        await page.route("**/api/reflection/*/confirm", (route) => route.fulfill({ json: {
            id: "x", applied_at: "2026-10-16T00:00:00Z",
            summary: { created: { task: 1, goal: 0, project: 0 }, updated: {}, deleted: {},
                errors: [], failed: [], already_applied: 0 },
        } }));
        try {
            await page.goto("/reflection?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.locator("#reflText").fill("473.");
            await page.locator("#reflAnalyzeBtn").click();
            await expect.poll(submit.seen).toBe(true);
            expect(await busy(page), "analyzing").toBe(true);

            submit.release();
            await expect(page.locator("#reflStateReview")).toBeVisible({ timeout: 10000 });
            expect(await busy(page), "on the review").toBe(true);

            await page.locator("#reflApplyBtn").click();
            await expect(page.locator("#reflStateDone")).toBeVisible();
            expect(await busy(page), "applied").toBe(false);
        } finally {
            await page.unroute("**/api/reflection").catch(() => {});
            await page.evaluate(() => fetch("/api/reflection/draft",
                { method: "DELETE", credentials: "same-origin" })).catch(() => {});
        }
    });
});
