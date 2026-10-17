/**
 * #364: archiving a project or goal pauses its repeating tasks on every
 * path, a reflection's "Delete project / goal" proposal included — but the
 * row never said so. The server now sends `archive_pauses` with the
 * reflection, and the row names them. History is stubbed (no Claude); the
 * map's server side is pytest's (test_reflection_archive_pauses.py).
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const ID = "00000000-0000-0000-0000-000000000364";
const PROJ = { op: "delete", entity: "project", id: "p-364", target: "E2E364 Kitchen", reason: "done" };
const GOAL = { op: "delete", entity: "goal", id: "g-364", target: "E2E364 Fitness", reason: "" };
const QUIET = { op: "delete", entity: "project", id: "q-364", target: "E2E364 Quiet", reason: "" };

function row() {
    return {
        id: ID, iso_week: "2026-W42", title: "E2E364 sitting", input_mode: "typed",
        transcript: "364.", audio_duration_seconds: null, audio_cost_usd: null, ai_cost_usd: 0.02,
        proposed_actions: { explicit: [PROJ, GOAL, QUIET], suggested: [] }, raw_segments: [],
        archive_pauses: { "project:p-364": ["Clean fridge", "Water plants"], "goal:g-364": ["Run"] },
        is_archived: false, is_active: true, is_draft: false, continued_from_id: null,
        continued_from: null, synthesis_of: null, context_files: [],
        updated_at: "2026-10-17T12:00:00+00:00", applied_actions: null, applied_at: null,
        created_at: "2026-10-17T12:00:00+00:00",
    };
}

test.describe("#364 an archive proposal names the repeating tasks it pauses", () => {
    test("project and goal rows say so; a row with nothing to pause doesn't", async ({ page }) => {
        await page.route(/\/api\/reflection(\?.*)?$/, (route) => {
            if (route.request().method() !== "GET") return route.fallback();
            return route.fulfill({ json: { reflections: [row()] } });
        });
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator("#reflHistory summary", { hasText: "E2E364 sitting" }).click();
        await page.getByRole("button", { name: "📋 Review proposals" }).click();
        await expect(page.locator("#reflStateReview")).toBeVisible();

        const rows = page.locator(".reflection-action-row");
        await expect(rows).toHaveCount(3);
        await expect(rows.nth(0).locator(".reflection-action-pause")).toHaveText(
            'This will pause 2 repeating tasks: "Clean fridge", "Water plants". '
            + "They resume when you unarchive the project.");
        await expect(rows.nth(1).locator(".reflection-action-pause")).toHaveText(
            'This will pause 1 repeating task: "Run". It resumes when you unarchive the goal.');
        // The quiet case: the row exists, the line doesn't.
        await expect(rows.nth(2)).toContainText("E2E364 Quiet");
        await expect(rows.nth(2).locator(".reflection-action-pause")).toHaveCount(0);
        // Information only: the tick boxes are as before.
        await expect(rows.nth(0).locator(".reflection-action-check")).toBeChecked();
    });
});
