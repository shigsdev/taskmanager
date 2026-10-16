/**
 * #462: above 600px a board card's quick actions (Today / Tomorrow / … /
 * + Subtask) were an invisible-until-hover bar on top of the title, still
 * clickable while invisible — a click aimed at the title moved the task. They
 * are now a "Move ▾" menu next to the ✓ (user's choice, 2026-10-15). At 600px
 * and below the row under the title is unchanged.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const LONG = "planning notes for the quarterly review with the platform team and the budget follow-ups";
const uniq = () => Math.random().toString(36).slice(2, 8);

async function backlogTask(request, extra) {
    return (await request.post("/api/tasks", {
        data: { title: `E2E462 ${uniq()} ${LONG}`, type: "work", tier: "backlog", ...(extra || {}) },
    })).json();
}
const cardIn = (page, tier, id) =>
    page.locator(`.task-list[data-tier="${tier}"] .task-card[data-id="${id}"]`);

async function openBoard(page) {
    await page.goto("/?nosw=1");
    await page.waitForLoadState("networkidle");
}

test.describe("#462 the title is never covered", () => {
    test("a click on the title's centre opens the task", async ({ page, request }) => {
        const task = await backlogTask(request);
        try {
            await openBoard(page);
            const title = cardIn(page, "backlog", task.id).locator(".task-title");
            await title.click();   // Playwright clicks the centre (and hovers first)
            await expect(page.locator("#detailOverlay")).toBeVisible();
            await expect(page.locator("#detailTitle")).toHaveValue(task.title);
            // …and the task didn't move.
            await expect(cardIn(page, "backlog", task.id)).toHaveCount(1);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("above 600px no quick-action button sits on the card", async ({ page, request }, testInfo) => {
        test.skip(testInfo.project.name === "chromium-mobile", "the phone row is below the title");
        const task = await backlogTask(request);
        try {
            await openBoard(page);
            const card = cardIn(page, "backlog", task.id);
            await card.hover();
            await expect(card.locator(".task-quick-actions")).toBeHidden();
            await expect(card.locator(".task-move-btn")).toBeVisible();
            // Walk the title and badge lines: only the card's own content, no button.
            const hits = await card.evaluate((el) => {
                const r = el.querySelector(".task-body").getBoundingClientRect();
                const out = [];
                for (let x = r.left + 2; x < r.right - 2; x += 20) {
                    for (const y of [r.top + 6, r.bottom - 6]) {
                        const h = document.elementFromPoint(x, y);
                        if (h && h.closest("button")) out.push(h.closest("button").textContent);
                    }
                }
                return out;
            });
            expect(hits).toEqual([]);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });
});

test.describe("#462 Move ▾", () => {
    test.beforeEach(async ({}, testInfo) => {
        test.skip(testInfo.project.name === "chromium-mobile", "the phone keeps its row");
    });

    test("lists the other sections and + Subtask, and moves the card", async ({ page, request }) => {
        const task = await backlogTask(request);
        try {
            await openBoard(page);
            const card = cardIn(page, "backlog", task.id);
            const move = card.locator(".task-move-btn");
            await move.click();
            const menu = page.locator(".task-move-menu");
            await expect(menu).toBeVisible();
            await expect(move).toHaveAttribute("aria-expanded", "true");
            await expect(menu.locator("button")).toHaveText(
                ["Today", "Tomorrow", "This Week", "Next Week", "Freezer", "+ Subtask"]);
            // The menu is wholly on screen.
            const box = await menu.boundingBox();
            const vp = page.viewportSize();
            expect(box.y).toBeGreaterThanOrEqual(0);
            expect(box.y + box.height).toBeLessThanOrEqual(vp.height);
            // Opening it didn't open the task.
            await expect(page.locator("#detailOverlay")).toBeHidden();

            await menu.locator("button", { hasText: "Freezer" }).click();
            await expect(cardIn(page, "freezer", task.id)).toHaveCount(1);
            await expect(cardIn(page, "backlog", task.id)).toHaveCount(0);
            await expect(page.locator(".task-move-menu")).toHaveCount(0);
            const saved = await (await request.get(`/api/tasks/${task.id}`)).json();
            expect(saved.tier).toBe("freezer");
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("a subtask's menu has no + Subtask; a second click closes it", async ({ page, request }) => {
        const parent = await backlogTask(request);
        const child = await backlogTask(request, { parent_id: parent.id });
        try {
            await openBoard(page);
            const move = cardIn(page, "backlog", child.id).locator(".task-move-btn");
            await move.click();
            await expect(page.locator(".task-move-menu button")).toHaveText(
                ["Today", "Tomorrow", "This Week", "Next Week", "Freezer"]);
            await move.click();
            await expect(page.locator(".task-move-menu")).toHaveCount(0);
            await expect(move).toHaveAttribute("aria-expanded", "false");
            // An outside click closes it too.
            await move.click();
            await page.locator("body").click({ position: { x: 2, y: 2 } });
            await expect(page.locator(".task-move-menu")).toHaveCount(0);
        } finally {
            await request.delete(`/api/tasks/${child.id}`);
            await request.delete(`/api/tasks/${parent.id}`);
        }
    });

    test("+ Subtask from the menu adds a subtask", async ({ page, request }) => {
        const task = await backlogTask(request);
        const subTitle = `E2E462 sub ${uniq()}`;
        try {
            await openBoard(page);
            page.once("dialog", (d) => d.accept(subTitle));
            await cardIn(page, "backlog", task.id).locator(".task-move-btn").click();
            await page.locator(".task-move-menu button", { hasText: "+ Subtask" }).click();
            await expect.poll(async () => {
                const all = await (await request.get("/api/tasks")).json();
                return all.filter((t) => t.parent_id === task.id && t.title === subTitle).length;
            }).toBe(1);
        } finally {
            const all = await (await request.get("/api/tasks")).json();
            for (const t of all.filter((t) => t.parent_id === task.id)) {
                await request.delete(`/api/tasks/${t.id}`);
            }
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("keyboard: Enter opens on the first item, Escape back to Move ▾, Tab on to ✓", async ({ page, request }) => {
        const task = await backlogTask(request);
        try {
            await openBoard(page);
            const card = cardIn(page, "backlog", task.id);
            const move = card.locator(".task-move-btn");
            await move.focus();
            await page.keyboard.press("Enter");
            const items = page.locator(".task-move-menu button");
            await expect(items.first()).toBeFocused();
            await expect(page.locator(".task-move-menu")).toHaveAttribute("role", "menu");
            await page.keyboard.press("ArrowDown");
            await expect(items.nth(1)).toBeFocused();
            await page.keyboard.press("Escape");
            await expect(page.locator(".task-move-menu")).toHaveCount(0);
            await expect(move).toBeFocused();
            await expect(page.locator("#detailOverlay")).toBeHidden();

            await page.keyboard.press("Enter");
            await expect(items.first()).toBeFocused();
            await page.keyboard.press("Tab");
            await expect(page.locator(".task-move-menu")).toHaveCount(0);
            await expect(card.locator(".task-complete-btn")).toBeFocused();
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });

    test("a scroll closes the menu", async ({ page, request }) => {
        const task = await backlogTask(request);
        try {
            await openBoard(page);
            await cardIn(page, "backlog", task.id).locator(".task-move-btn").click();
            await expect(page.locator(".task-move-menu")).toBeVisible();
            await page.mouse.wheel(0, 200);
            await expect(page.locator(".task-move-menu")).toHaveCount(0);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });
});

test.describe("#462 a touch screen wider than a phone", () => {
    test.use({ viewport: { width: 820, height: 1180 }, hasTouch: true });

    test("Move ▾ shows and works; nothing invisible is tappable", async ({ page, request }, testInfo) => {
        test.skip(testInfo.project.name === "chromium-mobile", "one run is enough");
        const task = await backlogTask(request);
        try {
            await openBoard(page);
            const card = cardIn(page, "backlog", task.id);
            await expect(card.locator(".task-quick-actions")).toBeHidden();
            await card.locator(".task-move-btn").tap();
            // The only way to move a card here, so a finger-sized target.
            const heights = await page.locator(".task-move-menu button").evaluateAll(
                (bs) => bs.map((b) => b.getBoundingClientRect().height));
            expect(Math.min(...heights)).toBeGreaterThanOrEqual(44);
            await page.locator(".task-move-menu button", { hasText: "Today" }).tap();
            await expect(cardIn(page, "today", task.id)).toHaveCount(1);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });
});

test.describe("#462 the phone row (unchanged)", () => {
    test("at 375 the row is under the title and there is no Move ▾", async ({ page, request }, testInfo) => {
        test.skip(testInfo.project.name !== "chromium-mobile", "phone only");
        const task = await backlogTask(request);
        try {
            await openBoard(page);
            const card = cardIn(page, "backlog", task.id);
            const row = card.locator(".task-quick-actions");
            await expect(row).toBeVisible();
            await expect(card.locator(".task-move-btn")).toBeHidden();
            const [rowBox, bodyBox] = [await row.boundingBox(), await card.locator(".task-body").boundingBox()];
            expect(rowBox.y).toBeGreaterThanOrEqual(bodyBox.y + bodyBox.height - 4);
            await row.locator("button", { hasText: "Freezer" }).click();
            await expect(cardIn(page, "freezer", task.id)).toHaveCount(1);
        } finally {
            await request.delete(`/api/tasks/${task.id}`);
        }
    });
});
