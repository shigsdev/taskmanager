/**
 * #454: projects, goals, recurring templates and calendar items opened only
 * on a click — there was no keyboard way to edit or archive them. Each is now
 * a Tab stop opened by Enter / Space; focus lands on the panel's ✕ and goes
 * back to what was opened when the panel closes (also after a save that
 * re-renders the list). The calendar gets a real "+" button per day, since
 * clicking a cell's empty space had no keyboard path.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const focusedAttr = (page, attr) => page.evaluate((a) =>
    document.activeElement && document.activeElement.getAttribute(a), attr);

test.describe("#454 open by keyboard, focus in and back", () => {
    test("/goals: Enter opens a goal card; Escape returns focus; Save too", async ({ page }) => {
        await page.goto("/goals?nosw=1");
        await page.waitForLoadState("networkidle");
        const card = page.locator(".goal-card[data-goal-id]").first();
        const id = await card.getAttribute("data-goal-id");
        await expect(card).toHaveAttribute("role", "button");
        await expect(card).toHaveAttribute("tabindex", "0");

        await card.focus();
        await page.keyboard.press("Enter");
        await expect(page.locator("#goalDetailOverlay")).toBeVisible();
        await expect(page.locator("#goalDetailClose")).toBeFocused();

        await page.keyboard.press("Escape");
        await expect(page.locator("#goalDetailOverlay")).toBeHidden();
        expect(await focusedAttr(page, "data-goal-id")).toBe(id);

        // Save re-renders every card: focus finds the new one.
        await page.keyboard.press("Enter");
        await expect(page.locator("#goalDetailOverlay")).toBeVisible();
        await page.locator("#goalDetailForm button[type=submit]").click();
        await expect(page.locator("#goalDetailOverlay")).toBeHidden();
        await expect.poll(() => focusedAttr(page, "data-goal-id")).toBe(id);
    });

    test("/projects: Space opens a project card; Escape returns focus", async ({ page }) => {
        await page.goto("/projects?nosw=1");
        await page.waitForLoadState("networkidle");
        const card = page.locator(".project-card[data-project-id]").first();
        const id = await card.getAttribute("data-project-id");
        await card.focus();
        await page.keyboard.press(" ");
        await expect(page.locator("#projectDetailOverlay")).toBeVisible();
        await expect(page.locator("#projectDetailClose")).toBeFocused();
        await page.keyboard.press("Escape");
        await expect(page.locator("#projectDetailOverlay")).toBeHidden();
        expect(await focusedAttr(page, "data-project-id")).toBe(id);
    });

    test("/recurring: Enter opens a template; Escape returns focus", async ({ page }) => {
        await page.goto("/recurring?nosw=1");
        await page.waitForLoadState("networkidle");
        const row = page.locator("[data-template-id]").first();
        const id = await row.getAttribute("data-template-id");
        await row.focus();
        await page.keyboard.press("Enter");
        await expect(page.locator("#recurEditOverlay")).toBeVisible();
        await expect(page.locator("#recurEditClose")).toBeFocused();
        await expect(page.locator("#recurEditTitle")).not.toHaveValue("");
        await page.keyboard.press("Escape");
        await expect(page.locator("#recurEditOverlay")).toBeHidden();
        expect(await focusedAttr(page, "data-template-id")).toBe(id);
    });

    test("/calendar: Enter opens a task line; Escape returns focus to it", async ({ page }) => {
        await page.goto("/calendar?nosw=1");
        await page.waitForLoadState("networkidle");
        const line = page.locator("li.calendar-task-link[data-task-id]").first();
        const id = await line.getAttribute("data-task-id");
        await line.focus();
        await page.keyboard.press("Enter");
        await expect(page.locator("#detailOverlay")).toBeVisible();
        await expect(page.locator("#detailClose")).toBeFocused();
        await page.keyboard.press("Escape");
        await expect(page.locator("#detailOverlay")).toBeHidden();
        await expect.poll(() => focusedAttr(page, "data-task-id")).toBe(id);
    });

    test("/calendar: a day's + button opens a new task on that day", async ({ page }) => {
        await page.goto("/calendar?nosw=1");
        await page.waitForLoadState("networkidle");
        const cell = page.locator(".calendar-cell:not(.calendar-cell-past)").nth(1);
        const iso = await cell.getAttribute("data-date");
        const add = cell.locator(".calendar-cell-add");
        await expect(add).toHaveAttribute("aria-label", /^Add a task on /);
        await add.focus();
        await page.keyboard.press("Enter");
        await expect(page.locator("#detailOverlay")).toBeVisible();
        await expect(page.locator("#detailDueDate")).toHaveValue(iso);
        // One panel, not two (the cell's own click must not fire as well).
        await expect(page.locator("#detailOverlay")).toHaveCount(1);
        await page.keyboard.press("Escape");
        await expect(page.locator("#detailOverlay")).toBeHidden();
    });

    test("a click still opens the same way (the quiet case)", async ({ page }) => {
        await page.goto("/goals?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator(".goal-card[data-goal-id]").first().click();
        await expect(page.locator("#goalDetailOverlay")).toBeVisible();
        await page.locator("#goalDetailClose").click();
        await expect(page.locator("#goalDetailOverlay")).toBeHidden();
    });
});
