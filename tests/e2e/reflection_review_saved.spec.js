/**
 * #495: a reflection's proposals are saved with it, but once the review
 * screen was gone History only offered "↻ Re-analyze" — a second Claude
 * call. "📋 Review proposals" re-opens the saved review for free; rows an
 * earlier Apply landed show "✓ applied" (#437) and Apply sends only the
 * rest. The History list is stubbed (no Claude anywhere in this test).
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const ID = "00000000-0000-0000-0000-000000000495";
const A = { op: "create", entity: "task", target: "E2E495 first", reason: "a" };
const B = { op: "create", entity: "task", target: "E2E495 second", reason: "b" };

function row(over) {
    return {
        id: ID, iso_week: "2026-W42", title: "E2E495 sitting", input_mode: "typed",
        transcript: "495.", audio_duration_seconds: null, audio_cost_usd: null, ai_cost_usd: 0.02,
        proposed_actions: { explicit: [A, B], suggested: [] }, raw_segments: [],
        is_archived: false, is_active: true, is_draft: false, continued_from_id: null,
        continued_from: null, synthesis_of: null, context_files: [],
        updated_at: "2026-10-16T12:00:00+00:00", applied_actions: null, applied_at: null,
        created_at: "2026-10-16T12:00:00+00:00", ...over,
    };
}

async function stubHistory(page, reflections) {
    await page.route(/\/api\/reflection(\?.*)?$/, (route) => {
        if (route.request().method() !== "GET") return route.fallback();
        return route.fulfill({ json: { reflections } });
    });
}

test.describe("#495 History re-opens the saved proposals", () => {
    test("Review proposals shows them with no new call; landed rows are marked", async ({ page }) => {
        // B already landed in an earlier, partial apply.
        await stubHistory(page, [row({ applied_actions: { actions: [B], summary: {} } })]);
        let analyzed = false;
        await page.route(/\/api\/reflection\/[^/]+\/analyze$/, (route) => { analyzed = true; return route.abort(); });
        let sent = null;
        await page.route(`**/api/reflection/${ID}/confirm`, async (route) => {
            sent = route.request().postDataJSON();
            await route.fulfill({ json: { id: ID, applied_at: "2026-10-16T13:00:00Z",
                summary: { created: { task: 1, goal: 0, project: 0 }, updated: {}, deleted: {},
                    errors: [], failed: [], already_applied: 0 } } });
        });
        try {
            await page.goto("/reflection?nosw=1");
            await page.waitForLoadState("networkidle");
            // History rows are <details>: open the row first.
            await page.locator("#reflHistory summary", { hasText: "E2E495 sitting" }).click();
            await page.getByRole("button", { name: "📋 Review proposals" }).click();
            await expect(page.locator("#reflStateReview")).toBeVisible();
            await expect(page.locator("#reflStateReview")).toContainText("Saved proposals — no new Claude call.");
            const rows = page.locator(".reflection-action-row");
            await expect(rows).toHaveCount(2);
            await expect(rows.nth(1)).toContainText("✓ applied");
            await expect(rows.nth(1).locator(".reflection-action-check")).toBeDisabled();
            await expect(rows.nth(0).locator(".reflection-action-check")).toBeChecked();
            await page.click("#reflApplyBtn");
            await expect(page.locator("#reflStateDone")).toBeVisible();
            expect(analyzed).toBe(false);
            expect(JSON.stringify(sent)).toContain("E2E495 first");
            expect(JSON.stringify(sent)).not.toContain("E2E495 second");
        } finally {
            await page.evaluate(() => fetch("/api/reflection/draft",
                { method: "DELETE", credentials: "same-origin" })).catch(() => {});
        }
    });

    test("no button on a fully applied reflection or one with no proposals (the quiet case)", async ({ page }) => {
        await stubHistory(page, [
            row({ applied_at: "2026-10-16T13:00:00+00:00" }),
            row({ id: "00000000-0000-0000-0000-000000000496", title: "E2E495 empty",
                proposed_actions: { explicit: [], suggested: [] } }),
        ]);
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#reflHistory")).toContainText("E2E495");
        // Open every row, or a missing button proves nothing.
        await page.evaluate(() => document.querySelectorAll("#reflHistory details").forEach((d) => { d.open = true; }));
        await expect(page.getByRole("button", { name: "↻ Re-analyze" }).first()).toBeVisible();
        await expect(page.getByRole("button", { name: "📋 Review proposals" })).toHaveCount(0);
    });
});
