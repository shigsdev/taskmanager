/**
 * #457: the dropdown menus (Inbox triage, Re-open, the board's bulk menus,
 * Pick a date…, /projects and /recurring bulk menus) had no Escape, no
 * focus movement and no menu semantics. Each now opens with focus on its
 * first item, ↑ ↓ move between items, Escape closes it with focus back on
 * the button that opened it, and it is announced as a menu.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

// Open a menu from the keyboard and walk it: focus lands on item 1, ↓ moves
// to item 2, Escape closes and returns focus to the opener.
async function walkMenu(page, opener, menuSel) {
    await page.locator(opener).focus();
    await page.keyboard.press("Enter");
    const menu = page.locator(menuSel).last();
    await expect(menu).toBeVisible();
    await expect(menu).toHaveAttribute("role", "menu");
    await expect(page.locator(opener)).toHaveAttribute("aria-expanded", "true");
    const items = menu.locator("button");
    await expect(items.first()).toBeFocused();
    await expect(items.first()).toHaveAttribute("role", "menuitem");
    await page.keyboard.press("ArrowDown");
    await expect(items.nth(1)).toBeFocused();
    await page.keyboard.press("ArrowUp");
    await page.keyboard.press("ArrowUp");
    await expect(items.last()).toBeFocused();       // wraps
    await page.keyboard.press("Escape");
    await expect(page.locator(menuSel)).toHaveCount(0);
    await expect(page.locator(opener)).toBeFocused();
    await expect(page.locator(opener)).toHaveAttribute("aria-expanded", "false");
}

test.describe("#457 dropdown menus from the keyboard", () => {
    test("board bulk Status ▾, and Pick a date… closes on Escape", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator(".task-card .bulk-select-check").first().check();
        await walkMenu(page, "#bulkActionStatus", ".bulk-dropdown");

        // Due date ▾ → Pick a date… → the date popup; Escape back to the button.
        await page.locator("#bulkActionDueDate").focus();
        await page.keyboard.press("Enter");
        await page.locator(".bulk-dropdown button", { hasText: "Pick a date…" }).click();
        await expect(page.locator(".bulk-date-input")).toBeFocused();
        await page.keyboard.press("Escape");
        await expect(page.locator(".bulk-date-pick")).toHaveCount(0);
        await expect(page.locator("#bulkActionDueDate")).toBeFocused();
    });

    test("Inbox triage menu", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator('.tier[data-tier="inbox"] .triage-check').first().check();
        await walkMenu(page, "#bulkTriageBtn", ".triage-dropdown");
    });

    test("a completed card's Re-open menu", async ({ page, request }) => {
        const t = await (await request.post("/api/tasks", { data: { title: `E2E457 reopen ${Date.now()}`, type: "work" } })).json();
        await request.post(`/api/tasks/${t.id}/complete`);
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.click("#tierCompleted .collapse-toggle");
            const btn = `#completedList .task-card[data-id="${t.id}"] .reopen-btn`;
            await expect(page.locator(btn)).toBeVisible();
            await walkMenu(page, btn, `#completedList .task-card[data-id="${t.id}"] .reopen-dropdown`);
        } finally {
            await request.delete(`/api/tasks/${t.id}`);
        }
    });

    test("/projects bulk Type ▾", async ({ page }) => {
        await page.goto("/projects?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator("#projectsBulkToggle").click();
        await page.locator(".project-bulk-cb").first().check();
        await walkMenu(page, "#projectsBulkType", ".bulk-dropdown-popover");
    });

    test("/recurring bulk Frequency ▾ (and it stays on screen)", async ({ page }) => {
        await page.goto("/recurring?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator(".recurring-row > input[type=checkbox]").first().check();
        await page.locator("#recurringBulkFrequency").focus();
        await page.keyboard.press("Enter");
        const box = await page.locator(".bulk-dropdown").boundingBox();
        const vh = page.viewportSize().height;
        expect(box.y + box.height).toBeLessThanOrEqual(vh);
        await page.keyboard.press("Escape");
        await walkMenu(page, "#recurringBulkFrequency", ".bulk-dropdown");
    });

    test("a mouse click still picks an item (the quiet case)", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator(".task-card .bulk-select-check").first().check();
        await page.locator("#bulkActionStatus").click();
        await expect(page.locator(".bulk-dropdown")).toBeVisible();
        // The outside-click listener goes on one tick after opening (so the
        // opening click can't close it); a person is never that fast.
        await page.waitForTimeout(150);
        await page.mouse.click(5, 300);
        await expect(page.locator(".bulk-dropdown")).toHaveCount(0);
        await expect(page.locator("#bulkActionStatus")).toHaveAttribute("aria-expanded", "false");
    });
});
