/**
 * #398 + #354 (2026-10-08): mobile tap targets reach the 44px floor.
 *
 * Measured at 375x812 before the fix: /docs and /architecture TOC links
 * were 20px tall (~5px apart), the /goals filter selects 31px and the
 * /projects filter selects 32px. CLAUDE.md's floor for tappable controls on
 * mobile is 44px. Mobile only: on desktop these are mouse targets.
 *
 * #453 (2026-10-15): the rest of the deep review's list, measured the same
 * way (docs/design/453-tap-targets.md). Checkboxes and radios get 24px
 * (WCAG 2.5.8 AA, the size the board's card checkbox already has) — a 44px
 * box would swallow the row's own click. Glyph-only buttons (✕, ↑, ℹ️) are
 * held to 44 in both directions.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

// floor: the minimum. dims: "h" = height only, "both" = width and height.
const SURFACES = [
    { path: "/docs", selector: ".docs-toc a", min: 30 },
    { path: "/architecture", selector: ".docs-toc a", min: 11 },
    { path: "/goals", selector: ".goals-filters select", min: 5 },
    { path: "/projects", selector: ".projects-filters select", min: 3 },
    // #399: the rest of the sub-44px selects, and the inputs/buttons sharing
    // their rows (measured 33/34/40/21px at 375x812 before the fix).
    { path: "/", selector: ".capture-bar select, .capture-bar input[type=\"text\"]", min: 2 },
    { path: "/", selector: ".weekly-focus-slot select, .weekly-focus-slot input, .weekly-focus-slot button", min: 6 },
    { path: "/utilities", selector: ".pg-goal-select", min: 1 },
    // #453 (heights measured before the fix in the comments).
    { path: "/", selector: "#taskSearchInput", min: 1 },                         // 35
    { path: "/completed", selector: "#taskSearchInput", min: 1 },                // 35
    { path: "/", selector: ".weekly-focus-tab", min: 2 },                        // 23
    { path: "/", selector: ".tier-heading-link", min: 3 },                       // 21
    { path: "/", selector: ".task-card .triage-check", min: 1, floor: 24, dims: "both" },  // 20
    { path: "/", selector: ".badge-url", min: 1, floor: 24 },                    // 19
    { path: "/recurring", selector: ".recurring-row > input[type=checkbox]", min: 3, floor: 24, dims: "both" }, // 13
    { path: "/calendar", selector: ".calendar-cell-tasks li.calendar-task-link", min: 1 },  // 24
    { path: "/calendar", selector: ".calendar-cell-add", min: 7, dims: "both" },   // #454's new + per day
    { path: "/scan", selector: "input[name=parseAs]", min: 3, floor: 24, dims: "both" },   // 13
    { path: "/reflection", selector: "#reflShowArchived", min: 1, floor: 24, dims: "both" }, // 13
    { path: "/reflection", selector: ".reflection-history-select", min: 1, floor: 24, dims: "both" }, // 22
    { path: "/reflection", selector: ".reflection-recently-deleted summary", min: 1 },     // 20
    { path: "/plan", selector: "#planStartDate", min: 1 },                       // 39
    { path: "/strength-forge", selector: ".sf-track-del", min: 1, dims: "both" },          // 21x22
    { path: "/strength-forge", selector: ".sf-exrow-info", min: 1, dims: "both" },         // 34x34
    { path: "/strength-forge", selector: ".sf-track-expandable", min: 1 },                 // 18
    { path: "/utilities", selector: ".utility-runs-link", min: 1 },              // 20
    { path: "/print", selector: ".print-actions button, .print-actions a", min: 2 },       // 40, 17
];

// Every visible match's box, and the page's overflow.
const measure = (page, sel) => page.evaluate((s) => ({
    boxes: [...document.querySelectorAll(s)]
        .map((el) => el.getBoundingClientRect())
        .filter((r) => r.width > 0 && r.height > 0)
        .map((r) => ({ h: r.height, w: r.width })),
    sw: document.documentElement.scrollWidth,
    iw: window.innerWidth,
}), sel);

// Half a pixel of slack for sub-pixel layout (a 24px box measured
// 23.9998 under load); every real miss was 4px or more.
const SLACK = 0.5;

function expectFloor(m, { min = 1, floor = 44, dims = "h" }, label) {
    expect(m.boxes.length, `${label}: how many`).toBeGreaterThanOrEqual(min);
    expect(Math.min(...m.boxes.map((b) => b.h)), `${label}: height`).toBeGreaterThanOrEqual(floor - SLACK);
    if (dims === "both") {
        expect(Math.min(...m.boxes.map((b) => b.w)), `${label}: width`).toBeGreaterThanOrEqual(floor - SLACK);
    }
    expect(m.sw, `${label}: page width`).toBeLessThanOrEqual(m.iw);
}

test.describe("#398 + #354 + #399 + #453 mobile tap targets", () => {
    for (const s of SURFACES) {
        test(`${s.path}: every ${s.selector} meets the ${s.floor || 44}px floor`, async ({ page, viewport }) => {
            test.skip(viewport.width >= 700, "mobile-only: desktop targets are mouse targets");

            await page.goto(`${s.path}?nosw=1`);
            await expect(page.locator(s.selector).first()).toBeVisible();
            expectFloor(await measure(page, s.selector), s, s.selector);
        });
    }
});

test.describe("#453 tap targets that only show after a tap", () => {
    test.beforeEach(({ viewport }) => {
        test.skip(viewport.width >= 700, "mobile-only: desktop targets are mouse targets");
    });

    test("board bulk toolbar buttons and its Status menu", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator(".task-card .bulk-select-check").first().check();
        await expect(page.locator("#bulkActionStatus")).toBeVisible();
        expectFloor(await measure(page, ".bulk-toolbar-actions .btn-sm"), { min: 5 }, "toolbar buttons");     // 40
        expectFloor(await measure(page, "#bulkActionMoveUp, #bulkActionMoveDown"), { min: 2, dims: "both" }, "↑↓"); // 40x25
        await page.locator("#bulkActionStatus").click();
        await expect(page.locator(".bulk-dropdown button").first()).toBeVisible();
        expectFloor(await measure(page, ".bulk-dropdown button"), { min: 2 }, "Status menu items");           // 32
    });

    test("task panel: subtask checkbox, checklist checkbox and ✕", async ({ page }) => {
        await page.goto("/?nosw=1");
        const ids = await page.evaluate(async () => {
            const mk = async (body) => (await (await fetch("/api/tasks", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            })).json()).id;
            const parent = await mk({ title: "E2E453 parent", type: "work", tier: "inbox" });
            const child = await mk({ title: "E2E453 child", type: "work", tier: "inbox", parent_id: parent });
            return { parent, child };
        });
        try {
            await page.goto(`/?task=${ids.parent}&nosw=1`);
            await expect(page.locator(".subtask-row input[type=checkbox]").first()).toBeVisible({ timeout: 10000 });
            await page.locator("#addChecklistItem").click();
            await expect(page.locator(".checklist-item .remove-item").first()).toBeVisible();

            expectFloor(await measure(page, ".subtask-row input[type=checkbox]"), { floor: 24, dims: "both" }, "subtask box");   // 13
            expectFloor(await measure(page, ".checklist-item input[type=checkbox]"), { floor: 24, dims: "both" }, "checklist box"); // 13
            expectFloor(await measure(page, ".checklist-item .remove-item"), { dims: "both" }, "checklist ✕");
        } finally {
            await page.evaluate(async (t) => {
                for (const id of [t.child, t.parent]) await fetch(`/api/tasks/${id}`, { method: "DELETE" });
            }, ids);
        }
    });

    test("goal panel: linked-task checkbox", async ({ page }) => {
        await page.goto("/goals?nosw=1");
        await page.waitForLoadState("networkidle");
        // A goal card that has tasks ("N of M tasks done" with M > 0).
        const card = page.locator(".goal-card", { hasText: /of [1-9]\d* tasks? done/ }).first();
        await card.click();
        const box = page.locator(".linked-task-row input[type=checkbox]").first();
        await expect(box).toBeVisible({ timeout: 10000 });
        expectFloor(await measure(page, ".linked-task-row input[type=checkbox]"), { floor: 24, dims: "both" }, "linked box"); // 13
    });

    test("Auto-categorize ✕", async ({ page }) => {
        await page.route("**/api/inbox/categorize", (route) => route.fulfill({
            status: 200, contentType: "application/json",
            body: JSON.stringify({ count: 0, capped: false, suggestions: [] }),
        }));
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator("#autoCategorizeBtn").click();
        await expect(page.locator("#autoCategorizeClose")).toBeVisible({ timeout: 10000 });
        expectFloor(await measure(page, "#autoCategorizeClose"), { dims: "both" }, "Auto-categorize ✕");
    });

    test("/projects Select: card checkboxes and the bulk menu items", async ({ page }) => {
        await page.goto("/projects?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator("#projectsBulkToggle").click();
        expectFloor(await measure(page, ".project-bulk-cb"), { floor: 24, dims: "both" }, "project box"); // 18
        await page.locator("#projectsBulkType").click();
        expectFloor(await measure(page, ".bulk-dropdown-item"), { min: 2 }, "Type menu items");
    });
});
