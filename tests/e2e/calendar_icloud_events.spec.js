/**
 * #371a: the user's iCloud Calendar events on /calendar, read-only.
 * /api/icloud/events is stubbed (the dev server has no ICLOUD_* set, so
 * its real answer is {enabled: false} -- the quiet case at the bottom).
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

function isoLocal(d) {
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
        "-" + String(d.getDate()).padStart(2, "0");
}
const today = new Date();
const TODAY = isoLocal(today);
const TOMORROW = isoLocal(new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1));
const DAY_AFTER = isoLocal(new Date(today.getFullYear(), today.getMonth(), today.getDate() + 2));
const THREE_DAYS = isoLocal(new Date(today.getFullYear(), today.getMonth(), today.getDate() + 3));

const DENTIST = {
    uid: "d|1", title: "E2E371 Dentist", start: `${TODAY}T09:30-04:00`,
    end: `${TODAY}T10:30-04:00`, all_day: false, location: "12 Main St",
    calendar: "Home", color: "#1BADF8",
};
const TRIP = {
    // All-day ends are exclusive: tomorrow and the day after.
    uid: "t|1", title: "E2E371 Trip", start: TOMORROW, end: THREE_DAYS,
    all_day: true, location: "", calendar: "Family", color: "",
};

async function stubEvents(page, body, status = 200) {
    const seen = [];
    await page.route("**/api/icloud/events?*", async (route) => {
        seen.push(route.request().url());
        await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    });
    return seen;
}

async function openCalendar(page) {
    await page.goto("/calendar?nosw=1");
    await page.waitForLoadState("networkidle");
}

test.describe("#371a iCloud events on /calendar", () => {
    test("events draw in their cells, above the tasks, and open read-only details", async ({ page }) => {
        const seen = await stubEvents(page, { enabled: true, events: [DENTIST, TRIP] });
        await openCalendar(page);
        expect(seen.length).toBeGreaterThan(0);
        expect(seen[0]).toMatch(/start=\d{4}-\d{2}-\d{2}&end=\d{4}-\d{2}-\d{2}/);

        await expect(page.locator("#calendarIcloud")).toBeVisible();
        await expect(page.locator("#calendarIcloud")).toContainText("Showing your iCloud Calendar");
        await expect(page.locator("#calendarIcloudError")).toBeHidden();

        const todayCell = page.locator(`.calendar-cell[data-date="${TODAY}"]`);
        const line = todayCell.locator(".calendar-event-item");
        await expect(line).toHaveCount(1);
        await expect(line).toContainText("9:30 AM");
        await expect(line).toContainText("E2E371 Dentist");
        await expect(line).toHaveAttribute("role", "button");
        // The calendar's color is the stripe.
        expect(await line.evaluate((el) => getComputedStyle(el).borderLeftColor))
            .toBe("rgb(27, 173, 248)");
        // Events sit above the cell's task list, and aren't tasks.
        const order = await todayCell.evaluate((cell) =>
            Array.from(cell.children).map((c) => c.className));
        const ev = order.indexOf("calendar-cell-events");
        const tasks = order.findIndex((c) => c.startsWith("calendar-cell-tasks"));
        expect(ev).toBeGreaterThan(-1);
        if (tasks > -1) expect(ev).toBeLessThan(tasks);
        await expect(line).not.toHaveAttribute("draggable", "true");

        // A two-day all-day event shows on both days, with no time.
        await expect(page.locator(`.calendar-cell[data-date="${TOMORROW}"] .calendar-event-item`))
            .toHaveText("E2E371 Trip");
        await expect(page.locator(`.calendar-cell[data-date="${DAY_AFTER}"] .calendar-event-item`))
            .toHaveText("E2E371 Trip");
        await expect(page.locator(`.calendar-cell[data-date="${THREE_DAYS}"] .calendar-event-item`))
            .toHaveCount(0);

        await line.click();
        const dlg = page.locator("#calendarEventOverlay");
        await expect(dlg).toBeVisible();
        await expect(page.locator("#calendarEventTitle")).toHaveText("E2E371 Dentist");
        const details = page.locator("#calendarEventDetails");
        await expect(details).toContainText("9:30 AM – 10:30 AM");
        await expect(details).toContainText("12 Main St");
        await expect(details).toContainText("Home");
        // Clicking an event opened no task panel.
        await expect(page.locator("#detailOverlay")).toBeHidden();
        await page.locator("#calendarEventClose").click();
        await expect(dlg).toBeHidden();
    });

    test("by keyboard: Enter opens, Escape closes and focus is back on the line", async ({ page }) => {
        await stubEvents(page, { enabled: true, events: [DENTIST] });
        await openCalendar(page);
        const line = page.locator(`.calendar-cell[data-date="${TODAY}"] .calendar-event-item`);
        await line.focus();
        await page.keyboard.press("Enter");
        await expect(page.locator("#calendarEventOverlay")).toBeVisible();
        await expect(page.locator("#calendarEventClose")).toBeFocused();
        await page.keyboard.press("Escape");
        await expect(page.locator("#calendarEventOverlay")).toBeHidden();
        await expect(line).toBeFocused();
    });

    test("iCloud failing says so above the grid, and the tasks still draw", async ({ page }) => {
        await stubEvents(page, {
            enabled: true,
            error: "iCloud refused the app-specific password. It may have been revoked.",
            auth: true,
        }, 502);
        await openCalendar(page);
        await expect(page.locator("#calendarIcloudError")).toBeVisible();
        await expect(page.locator("#calendarIcloudError"))
            .toContainText("Couldn't show iCloud events: iCloud refused the app-specific password");
        await expect(page.locator("#calendarIcloudError")).toContainText("Your tasks are shown as usual.");
        await expect(page.locator(".calendar-event-item")).toHaveCount(0);
        await expect(page.locator(".calendar-cell").first()).toBeVisible();
        await expect(page.locator("#calendarLoadError")).toHaveCount(0);
        // A 502 is not "sign in again": no recovery prompt took over.
        await expect(page.locator(`.calendar-cell[data-date="${TODAY}"]`)).toBeVisible();
    });

    test("Refresh asks the server to forget its cache, then reads again", async ({ page }) => {
        const seen = await stubEvents(page, { enabled: true, events: [DENTIST] });
        let refreshes = 0;
        await page.route("**/api/icloud/refresh", async (route) => {
            expect(route.request().method()).toBe("POST");
            refreshes += 1;
            await route.fulfill({ status: 200, contentType: "application/json", body: '{"ok":true}' });
        });
        await openCalendar(page);
        const before = seen.length;
        const btn = page.locator("#calendarIcloudRefresh");
        await btn.dblclick();
        await expect.poll(() => seen.length).toBeGreaterThan(before);
        await expect(btn).toHaveText("↻ Refresh iCloud");
        await expect(btn).toBeEnabled();
        expect(refreshes).toBe(1);
    });

    test("not set up: no strip, no events (the quiet case)", async ({ page }) => {
        // The real dev server answer -- no stub.
        const answers = [];
        page.on("response", async (r) => {
            if (r.url().includes("/api/icloud/events")) answers.push({ status: r.status(), body: await r.json() });
        });
        await openCalendar(page);
        await expect.poll(() => answers.length).toBeGreaterThan(0);
        expect(answers[0].status).toBe(200);
        expect(answers[0].body).toEqual({ enabled: false, events: [] });
        await expect(page.locator("#calendarIcloud")).toBeHidden();
        await expect(page.locator(".calendar-event-item")).toHaveCount(0);
    });

    test.describe("at 375", () => {
        test.use({ viewport: { width: 375, height: 812 } });
        test("event lines are 44px tall and nothing scrolls sideways", async ({ page }) => {
            await stubEvents(page, { enabled: true, events: [DENTIST, TRIP] });
            await openCalendar(page);
            const line = page.locator(`.calendar-cell[data-date="${TODAY}"] .calendar-event-item`);
            await expect(line).toBeVisible();
            const h = await line.evaluate((el) => el.getBoundingClientRect().height);
            expect(h).toBeGreaterThanOrEqual(44);
            const rb = await page.locator("#calendarIcloudRefresh")
                .evaluate((el) => el.getBoundingClientRect().height);
            expect(rb).toBeGreaterThanOrEqual(44);
            const sw = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
            expect(sw).toBe(true);
        });
    });
});
