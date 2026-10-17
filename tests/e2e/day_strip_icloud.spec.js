/**
 * #498: the board's day strip shows each day's iCloud events — its first
 * event and "+N" on wide screens, a dot on narrow ones — and opens
 * /calendar. /api/icloud/events is stubbed (the dev server has no
 * ICLOUD_*: its real answer is the quiet case at the bottom).
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

function isoLocal(n) {
    const d = new Date();
    d.setDate(d.getDate() + n);
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
        "-" + String(d.getDate()).padStart(2, "0");
}
const TODAY = isoLocal(0);
const EVENTS = [
    { uid: "a", title: "E2E498 Dentist", start: `${TODAY}T09:30-04:00`, end: `${TODAY}T10:30-04:00`,
        all_day: false, location: "", calendar: "Home", color: "" },
    { uid: "b", title: "E2E498 Call", start: `${TODAY}T14:00-04:00`, end: `${TODAY}T15:00-04:00`,
        all_day: false, location: "", calendar: "Home", color: "" },
    { uid: "c", title: "E2E498 Gym", start: `${TODAY}T18:00-04:00`, end: `${TODAY}T19:00-04:00`,
        all_day: false, location: "", calendar: "Home", color: "" },
];

async function stub(page) {
    let calls = 0;
    await page.route("**/api/icloud/events?*", async (route) => {
        calls += 1;
        await route.fulfill({ status: 200, contentType: "application/json",
            body: JSON.stringify({ enabled: true, events: EVENTS }) });
    });
    return () => calls;
}

test.describe("#498 iCloud events on the board's day strip", () => {
    test("wide: today's box shows its first event and +2, and links to /calendar", async ({ page }) => {
        await page.setViewportSize({ width: 1280, height: 800 });
        const calls = await stub(page);
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        const cell = page.locator(`#dayStrip .day-cell[data-date="${TODAY}"]`);
        const link = cell.locator(".day-cell-event");
        await expect(link).toBeVisible();
        await expect(link.locator(".day-cell-event-text")).toHaveText("9:30am E2E498 Dentist");
        await expect(link.locator(".day-cell-event-more")).toHaveText("+2");
        await expect(link).toHaveAttribute("href", "/calendar");
        await expect(link).toHaveAttribute("aria-label",
            "iCloud: 9:30 AM E2E498 Dentist and 2 more — open the calendar");
        // A day with nothing has no event line.
        await expect(page.locator("#dayStrip .day-cell-event")).toHaveCount(1);
        // Drawing the board again (a task change) doesn't ask again within a minute.
        await page.evaluate(() => window.renderBoard && window.renderBoard());
        expect(calls()).toBe(1);
        await link.click();
        await expect(page).toHaveURL(/\/calendar/);
    });

    test("narrow: a dot, the whole box is the link, and the strip keeps its height", async ({ page }) => {
        await page.setViewportSize({ width: 375, height: 812 });
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        const before = await page.locator("#dayStrip").evaluate((el) => el.getBoundingClientRect().height);

        await stub(page);
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        const link = page.locator(`#dayStrip .day-cell[data-date="${TODAY}"] .day-cell-event`);
        await expect(link).toBeAttached();
        await expect(link.locator(".day-cell-event-text")).toBeHidden();
        const h = await link.evaluate((el) => el.getBoundingClientRect().height);
        expect(h).toBeGreaterThanOrEqual(44);
        const after = await page.locator("#dayStrip").evaluate((el) => el.getBoundingClientRect().height);
        expect(Math.round(after)).toBe(Math.round(before));
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    });

    test("not set up: the strip is exactly as before (the quiet case)", async ({ page }) => {
        const answers = [];
        page.on("response", async (r) => {
            if (r.url().includes("/api/icloud/events")) answers.push(await r.json());
        });
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        await expect.poll(() => answers.length).toBeGreaterThan(0);
        expect(answers[0]).toEqual({ enabled: false, events: [] });
        await expect(page.locator("#dayStrip .day-cell")).toHaveCount(14);
        await expect(page.locator("#dayStrip .day-cell-event")).toHaveCount(0);
    });
});
