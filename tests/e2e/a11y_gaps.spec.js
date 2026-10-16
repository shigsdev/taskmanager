/**
 * #458: the keyboard / screen-reader gaps left after #454-#457 — card quick
 * actions you could Tab to but not see, a mouse-only parent picker and
 * staged-change chips, controls with no name, dialogs not announced as
 * modal, no skip link, and tabs that don't say which one is showing.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

// Every page the nav reaches. The name check reads hidden controls too (a
// panel's fields are in the DOM before it opens), so it covers the panels.
const PAGES = ["/", "/tier/today", "/completed", "/goals", "/projects",
    "/recurring", "/calendar", "/review", "/settings", "/import", "/scan",
    "/recycle-bin", "/print", "/reflection", "/voice-memo", "/strength-forge",
    "/utilities", "/docs", "/plan"];

// The controls on the page with no accessible name. A placeholder alone
// doesn't count: it vanishes once you type and isn't a label.
function unnamedControls() {
    const t = (s) => (s || "").replace(/\s+/g, " ").trim();
    const named = (el) => {
        if (t(el.getAttribute("aria-label"))) return true;
        const lb = el.getAttribute("aria-labelledby");
        if (lb && lb.split(/\s+/).some((id) => t((document.getElementById(id) || {}).textContent))) return true;
        if (el.labels && Array.from(el.labels).some((l) => t(l.textContent))) return true;
        const tag = el.tagName;
        const textual = tag === "BUTTON" || tag === "A" || tag === "SUMMARY"
            || el.getAttribute("role") === "button";
        if (textual && t(el.textContent)) return true;
        const img = el.querySelector("img[alt]");
        if (img && t(img.alt)) return true;
        if (t(el.getAttribute("title"))) return true;
        if (tag === "INPUT" && /^(submit|button)$/.test(el.type) && t(el.value)) return true;
        return false;
    };
    const sel = "input:not([type=hidden]), select, textarea, button, a[href], "
        + "[role=button], [tabindex]:not([tabindex='-1']), summary";
    const out = {};
    for (const el of document.querySelectorAll(sel)) {
        if (named(el)) continue;
        const d = el.tagName.toLowerCase() + (el.id ? "#" + el.id : "")
            + (typeof el.className === "string" && el.className ? "." + el.className.split(" ")[0] : "");
        out[d] = (out[d] || 0) + 1;
    }
    return out;
}

test.describe("#458 every control has a name", () => {
    for (const path of PAGES) {
        test(`${path}`, async ({ page }) => {
            await page.goto(path + "?nosw=1");
            await page.waitForLoadState("networkidle");
            expect(await page.evaluate(unnamedControls)).toEqual({});
        });
    }
});

test.describe("#458 keyboard and screen reader", () => {
    // #458 made Tab onto the hidden hover bar show it; #462 replaced the bar
    // with Move ▾ above 600px, so the keyboard meets a visible button.
    test("Tab reaches a card's quick actions, and they're visible", async ({ page }, testInfo) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        const card = page.locator(".task-card:has(.task-quick-actions button)").first();
        if (testInfo.project.name === "chromium-mobile") {
            await card.locator(".task-complete-btn").focus();
            await page.keyboard.press("Tab");
            const first = card.locator(".task-quick-actions button").first();
            await expect(first).toBeFocused();
            await expect(first).toBeVisible();
        } else {
            await card.locator(".task-move-btn").focus();
            await expect(card.locator(".task-move-btn")).toBeVisible();
            await page.keyboard.press("Tab");
            await expect(card.locator(".task-complete-btn")).toBeFocused();
            await expect(card.locator(".task-quick-actions")).toBeHidden();
        }
    });

    test("parent picker: ↓ highlights, Enter picks, Escape closes the list only", async ({ page, request }) => {
        const stamp = Date.now();
        const parent = await (await request.post("/api/tasks", { data: { title: `E2E458 parent ${stamp}`, type: "work" } })).json();
        const child = await (await request.post("/api/tasks", { data: { title: `E2E458 child ${stamp}`, type: "work" } })).json();
        try {
            await page.goto("/?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.locator(`.task-card[data-id="${child.id}"] .task-title`).click({ position: { x: 4, y: 4 } });   // #281: not card center
            await expect(page.locator("#detailOverlay")).toBeVisible();

            const box = page.locator("#parentPickerInput");
            await expect(box).toHaveAttribute("role", "combobox");
            await box.fill(`E2E458 parent ${stamp}`);
            await expect(page.locator("#parentPickerResults")).toBeVisible();
            await expect(page.locator("#parentPickerResults")).toHaveAttribute("role", "listbox");
            await expect(box).toHaveAttribute("aria-expanded", "true");

            await page.keyboard.press("ArrowDown");
            const opt = page.locator("#parentPickerResults [role=option]").first();
            await expect(opt).toHaveAttribute("aria-selected", "true");
            await expect(box).toHaveAttribute("aria-activedescendant", await opt.getAttribute("id"));

            await page.keyboard.press("Enter");
            await expect(page.locator("#parentPickerCurrent")).toContainText(`E2E458 parent ${stamp}`);
            await expect(page.locator("#parentPickerResults")).toBeHidden();
            await expect(page.locator("#detailOverlay")).toBeVisible();   // Enter didn't save
            const still = await (await request.get(`/api/tasks/${child.id}`)).json();
            expect(still.parent_id).toBeFalsy();

            // Escape with the list open closes only the list…
            await box.fill(`E2E458 parent ${stamp}`);
            await expect(page.locator("#parentPickerResults")).toBeVisible();
            await page.keyboard.press("Escape");
            await expect(page.locator("#parentPickerResults")).toBeHidden();
            await expect(box).toHaveAttribute("aria-expanded", "false");
            await expect(page.locator("#detailOverlay")).toBeVisible();
            // …and the next one closes the panel.
            await page.keyboard.press("Escape");
            await expect(page.locator("#detailOverlay")).toBeHidden();
        } finally {
            await request.delete(`/api/tasks/${child.id}`);
            await request.delete(`/api/tasks/${parent.id}`);
        }
    });

    test("a staged bulk change is a button; Enter removes it", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator(".task-card .bulk-select-check").first().check();
        await page.locator("#bulkActionType").click();
        await page.locator(".bulk-dropdown button", { hasText: "Personal" }).click();
        const chip = page.locator("#bulkPendingList .bulk-pending-chip");
        await expect(chip).toHaveCount(1);
        expect(await chip.evaluate((el) => el.tagName)).toBe("BUTTON");
        await expect(chip).toHaveAttribute("aria-label", /Remove staged change: Type: Personal/);
        await chip.focus();
        await page.keyboard.press("Enter");
        await expect(chip).toHaveCount(0);
        await expect(page.locator("#bulkPending")).toBeHidden();
    });

    const DIALOGS = {
        "/": ["#detailPanel", ".weekly-focus-plan-dialog", "#autoCategorizeModal"],
        "/goals": ["#goalDetailPanel"],
        "/projects": ["#projectDetailPanel"],
        "/recurring": ["#recurEditPanel"],
        "/reflection": [".reflection-focus-dialog"],
        "/recycle-bin": [".modal"],
        "/strength-forge": [".sf-modal"],
    };
    for (const [path, sels] of Object.entries(DIALOGS)) {
        test(`dialogs on ${path} say they are modal and have a name`, async ({ page }) => {
            await page.goto(path + "?nosw=1");
            await page.waitForLoadState("networkidle");
            // The Strength Forge pop-up gets its title when it opens.
            if (path === "/strength-forge") await page.locator(".sf-exrow-info").first().click();
            for (const sel of sels) {
                const d = page.locator(sel).first();
                await expect(d, sel).toHaveAttribute("role", "dialog");
                await expect(d, sel).toHaveAttribute("aria-modal", "true");
                const name = await d.evaluate((el) => {
                    const lb = el.getAttribute("aria-labelledby");
                    const viaId = lb ? (document.getElementById(lb) || {}).textContent : "";
                    return (el.getAttribute("aria-label") || viaId || "").trim();
                });
                expect(name, sel).not.toBe("");
            }
        });
    }

    test("the first Tab lands on the skip link; Enter goes to the content", async ({ page }) => {
        for (const path of ["/", "/goals", "/settings"]) {
            await page.goto(path + "?nosw=1");
            await page.waitForLoadState("networkidle");
            await page.locator("body").focus();
            await page.keyboard.press("Tab");
            const skip = page.locator("a.skip-link");
            await expect(skip, path).toBeFocused();
            await expect(skip, path).toBeVisible();
            await page.keyboard.press("Enter");
            await expect(page.locator("main#main"), path).toBeFocused();
            // …and it lands below the pinned nav, not under it.
            const below = await page.evaluate(() => {
                const pinned = parseFloat(getComputedStyle(document.documentElement)
                    .getPropertyValue("--nav-pinned-h")) || 0;
                return document.getElementById("main").getBoundingClientRect().top - pinned;
            });
            expect(below, path).toBeGreaterThanOrEqual(-0.5);
        }
    });

    test("aria-selected follows the Focus tabs and the reflection tabs", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        const thisW = page.locator("#weeklyFocusTabThis");
        const nextW = page.locator("#weeklyFocusTabNext");
        await expect(thisW).toHaveAttribute("aria-selected", "true");
        await expect(nextW).toHaveAttribute("aria-selected", "false");
        await nextW.click();
        await expect(nextW).toHaveAttribute("aria-selected", "true");
        await expect(thisW).toHaveAttribute("aria-selected", "false");
        await thisW.click();
        await expect(thisW).toHaveAttribute("aria-selected", "true");

        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#reflTabType")).toHaveAttribute("aria-selected", "true");
        await expect(page.locator("#reflTabVoice")).toHaveAttribute("aria-selected", "false");
        await page.locator("#reflTabVoice").click();
        await expect(page.locator("#reflTabVoice")).toHaveAttribute("aria-selected", "true");
        await expect(page.locator("#reflTabType")).toHaveAttribute("aria-selected", "false");
    });
});
