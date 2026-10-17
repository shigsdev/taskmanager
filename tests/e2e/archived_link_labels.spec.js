/**
 * #361: a link to an archived project / goal is shown the same way
 * wherever it's shown read-only — "<name> (archived)" — like the pickers
 * (#355) and the Work-view header (#434). Before: the /projects card's goal
 * line read like a live goal, the board card's badges vanished, and
 * /recurring had its own copy of the rule. Real data, real archive.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

test.describe("#361 archived links read '(archived)' everywhere", () => {
    test("board badges, /projects goal line and /recurring all mark it", async ({ page, request }) => {
        const tag = `E2E361 ${Date.now()}`;
        const goal = await (await request.post("/api/goals", {
            data: { title: tag + " goal", category: "work", priority: "should" } })).json();
        const gone = await (await request.post("/api/projects", {
            data: { name: tag + " gone", type: "work", goal_id: goal.id } })).json();
        // A live project on the goal: its /projects card shows the goal line.
        const live = await (await request.post("/api/projects", {
            data: { name: tag + " live", type: "work", goal_id: goal.id } })).json();
        const task = await (await request.post("/api/tasks", {
            data: { title: tag + " task", type: "work", tier: "today",
                project_id: gone.id, goal_id: goal.id } })).json();
        const rt = await (await request.post("/api/recurring", {
            data: { title: tag + " repeat", frequency: "daily", type: "work",
                project_id: gone.id, goal_id: goal.id } })).json();
        expect((await request.delete(`/api/projects/${gone.id}`)).ok()).toBe(true);
        expect((await request.delete(`/api/goals/${goal.id}`)).ok()).toBe(true);
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            const card = page.locator(`.task-card[data-id="${task.id}"]`);
            await expect(card.locator(".badge-project")).toHaveText(tag + " gone (archived)");
            await expect(card.locator(".badge-goal")).toHaveText(tag + " goal (archived)");
            await expect(card.locator(".badge-archived-link")).toHaveCount(2);

            await page.goto("/projects?nosw=1");
            await page.waitForLoadState("networkidle");
            await expect(page.locator(".project-card", { hasText: tag + " live" }))
                .toContainText(`Goal: ${tag} goal (archived)`);

            await page.goto("/recurring?nosw=1");
            await page.waitForLoadState("networkidle");
            const row = page.locator(".recurring-row", { hasText: tag + " repeat" });
            await expect(row.locator(".recurring-row-meta")).toContainText(`proj: ${tag} gone (archived)`);
            await expect(row.locator(".recurring-row-meta")).toContainText(`goal: ${tag} goal (archived)`);
        } finally {
            await request.delete(`/api/recurring/${rt.id}`);
            await request.delete(`/api/tasks/${task.id}`);
            await request.delete(`/api/projects/${live.id}`);
        }
    });

    test("a live link reads plain (the quiet case)", async ({ page, request }) => {
        const tag = `E2E361 ${Date.now()}`;
        const goal = await (await request.post("/api/goals", {
            data: { title: tag + " goal", category: "work", priority: "should" } })).json();
        const proj = await (await request.post("/api/projects", {
            data: { name: tag + " proj", type: "work", goal_id: goal.id } })).json();
        const task = await (await request.post("/api/tasks", {
            data: { title: tag + " task", type: "work", tier: "today",
                project_id: proj.id, goal_id: goal.id } })).json();
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            const card = page.locator(`.task-card[data-id="${task.id}"]`);
            await expect(card.locator(".badge-project")).toHaveText(tag + " proj");
            await expect(card.locator(".badge-goal")).toHaveText(tag + " goal");
            await expect(card.locator(".badge-project")).toBeVisible();
            await expect(card.locator(".badge-archived-link")).toHaveCount(0);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
            await request.delete(`/api/projects/${proj.id}`);
            await request.delete(`/api/goals/${goal.id}`);
        }
    });
});
