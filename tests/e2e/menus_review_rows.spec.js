/**
 * #487 (split from #452):
 *  - /projects' bulk menus always opened UNDER their button, which sits in
 *    the bottom toolbar: at 375x812 Status ended at 861px and Goal ran from
 *    791 to 1091px, off the bottom of the screen.
 *  - Review rows overflowed at 375: /scan Goals 718px wide, /scan Projects
 *    527px, an /import duplicate row 419px (the title box kept its ~199px
 *    built-in minimum width).
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const noSidewaysScroll = (page) => page.evaluate(() =>
    document.documentElement.scrollWidth <= window.innerWidth);

test.describe("#487 /projects bulk menus stay on screen", () => {
    test("every bulk menu fits the screen and its last option can be picked", async ({ page }) => {
        await page.goto("/projects?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator("#projectsBulkToggle").click();
        await page.locator(".project-bulk-cb").first().check();

        for (const id of ["projectsBulkType", "projectsBulkStatus", "projectsBulkPriority", "projectsBulkGoal"]) {
            await page.locator(`#${id}`).click();
            const pop = page.locator(".bulk-dropdown-popover");
            await expect(pop).toBeVisible();
            const m = await pop.evaluate((el) => {
                const r = el.getBoundingClientRect();
                const items = el.querySelectorAll(".bulk-dropdown-item");
                const last = items[items.length - 1];
                last.scrollIntoView({ block: "nearest" });
                const lr = last.getBoundingClientRect();
                const hit = document.elementFromPoint(lr.left + 10, lr.top + lr.height / 2);
                return { left: r.left, right: r.right, top: r.top, bottom: r.bottom,
                         vw: window.innerWidth, vh: window.innerHeight,
                         lastHittable: hit === last || last.contains(hit) };
            });
            expect(m.top, `${id} menu top`).toBeGreaterThanOrEqual(0);
            expect(m.bottom, `${id} menu bottom`).toBeLessThanOrEqual(m.vh);
            expect(m.left, `${id} menu left`).toBeGreaterThanOrEqual(0);
            expect(m.right, `${id} menu right`).toBeLessThanOrEqual(m.vw);
            expect(m.lastHittable, `${id} last option`).toBe(true);
            // Opening the next menu replaces this one (Escape is #457's).
            await expect(pop).toHaveCount(1);
        }
    });

    test("picking the last Status option sends it", async ({ page }) => {
        let body = null;
        await page.route("**/api/projects/bulk", async (route, request) => {
            body = request.postDataJSON();
            await route.fulfill({ status: 200, contentType: "application/json",
                body: JSON.stringify({ updated: body.project_ids.length, errors: [] }) });
        });
        await page.goto("/projects?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator("#projectsBulkToggle").click();
        await page.locator(".project-bulk-cb").first().check();
        await page.locator("#projectsBulkStatus").click();
        // A real click: Playwright refuses one on an option off the screen.
        await page.locator(".bulk-dropdown-popover .bulk-dropdown-item", { hasText: "On hold" }).click();
        await expect.poll(() => body && body.updates).toEqual({ status: "on_hold" });
    });
});

test.describe("#487 scan and import review rows fit the phone", () => {
    const stubbed = {
        tasks: [{ title: "Call the dentist about the crown replacement appointment", type: "work", included: true }],
        goals: [{ title: "Run a half marathon in under two hours", category: "health",
                  priority: "should", target_quarter: "Q2 2026", actions: "", included: true }],
        projects: [{ title: "Kitchen renovation budget and contractor bids", type: "personal",
                     target_quarter: "2026-Q4", included: true }],
    };

    for (const kind of ["tasks", "goals", "projects"]) {
        test(`/scan ${kind}: the review row stays inside the screen`, async ({ page }) => {
            await page.route("**/api/scan/upload", (route) => route.fulfill({
                status: 200, contentType: "application/json",
                body: JSON.stringify({ ocr_text: "x", kind, candidates: stubbed[kind] }),
            }));
            await page.goto("/scan?nosw=1");
            await page.locator(`input[name=parseAs][value=${kind}]`).check();
            // A real 1x1 PNG, so the page's resize-before-upload step works.
            await page.setInputFiles("#scanFile", {
                name: "note.png", mimeType: "image/png",
                buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "base64"),
            });
            await page.locator("#scanSubmitBtn").click();
            const row = page.locator(".scan-candidate").first();
            await expect(row).toBeVisible({ timeout: 10000 });

            expect(await noSidewaysScroll(page)).toBe(true);
            const outside = await row.evaluate((el) => {
                const r = el.getBoundingClientRect();
                return [...el.children].filter((c) => {
                    const k = c.getBoundingClientRect();
                    return k.right > r.right + 0.5 || k.left < r.left - 0.5;
                }).map((c) => c.className);
            });
            expect(outside).toEqual([]);
        });
    }

    test("/import: a duplicate row with its badge stays inside the screen", async ({ page, request }) => {
        // A name that already exists, so the review marks it a duplicate.
        const projects = await (await request.get("/api/projects")).json();
        const existing = (Array.isArray(projects) ? projects : projects.projects)[0].name;

        await page.goto("/import?nosw=1");
        await page.locator("#importProjectsTextBtn").click();
        await page.locator("textarea:visible").fill(`${existing}\nA brand new project for 487`);
        await page.getByRole("button", { name: /Parse/ }).filter({ visible: true }).click();
        await expect(page.locator(".import-duplicate .import-dup-badge")).toBeVisible({ timeout: 10000 });

        expect(await noSidewaysScroll(page)).toBe(true);
        const badgeInside = await page.locator(".import-duplicate").evaluate((row) => {
            const r = row.getBoundingClientRect();
            const b = row.querySelector(".import-dup-badge").getBoundingClientRect();
            return b.right <= r.right + 0.5;
        });
        expect(badgeInside).toBe(true);
    });
});
