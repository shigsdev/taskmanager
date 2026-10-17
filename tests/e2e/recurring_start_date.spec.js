/**
 * #501: set and change a repeating task's start date, in the task panel's
 * Repeat section and the /recurring editor.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

function isoLocal(n) {
    const d = new Date();
    d.setDate(d.getDate() + n);
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
        "-" + String(d.getDate()).padStart(2, "0");
}
const TODAY = isoLocal(0);
const DOW = (new Date().getDay() + 6) % 7;   // Mon=0, the app's weekday numbering

async function openCard(page, id) {
    await page.goto("/?nosw=1");
    await page.waitForLoadState("networkidle");
    await page.locator(`.task-card[data-id="${id}"] .task-title`).first()
        .click({ position: { x: 4, y: 4 } });
    await expect(page.locator("#detailPanel")).toBeVisible();
}

test.describe("#501 a repeating task's start date", () => {
    test("the panel shows it, a later one saves and moves the previews, and blank clears it", async ({ page, request }) => {
        const tag = `E2E501 panel ${Date.now()}`;
        const made = await (await request.post("/api/tasks", { data: {
            title: tag, type: "work", tier: "today", due_date: TODAY,
            repeat: { frequency: "weekly", day_of_week: DOW },
        } })).json();
        const tid = made.repeat.template_id;
        try {
            await openCard(page, made.id);
            const start = page.locator("#detailRepeatStartDate");
            await expect(start).toBeVisible();
            await expect(start).toHaveValue(TODAY);   // #147's default, now visible

            const later = isoLocal(14);
            await start.fill(later);
            await page.locator('#detailOverlay button[type="submit"]').click();
            await expect(page.locator("#detailOverlay")).toBeHidden();
            const after = await (await request.get(`/api/tasks/${made.id}`)).json();
            expect(after.repeat.start_date).toBe(later);
            expect(after.status).toBe("active");   // the task itself stays
            const previews = await (await request.get(
                `/api/recurring/previews?start=${isoLocal(1)}&end=${isoLocal(21)}`)).json();
            const mine = previews.filter((p) => p.title === tag).map((p) => p.fire_date);
            expect(mine.length).toBeGreaterThan(0);
            expect(mine.every((d) => d >= later)).toBe(true);

            // Reopen: it shows; clear it; Save: blank stays blank.
            await openCard(page, made.id);
            await expect(start).toHaveValue(later);
            await start.fill("");
            await page.locator('#detailOverlay button[type="submit"]').click();
            await expect(page.locator("#detailOverlay")).toBeHidden();
            const cleared = await (await request.get(`/api/tasks/${made.id}`)).json();
            expect(cleared.repeat.start_date).toBeUndefined();
            await openCard(page, made.id);
            await expect(start).toHaveValue("");
        } finally {
            await request.delete(`/api/tasks/${made.id}`);
            await request.delete(`/api/recurring/${tid}`);
        }
    });

    test("picking Weekly on a dated task fills Start on with its due date", async ({ page, request }) => {
        const tag = `E2E501 prefill ${Date.now()}`;
        const made = await (await request.post("/api/tasks", { data: {
            title: tag, type: "work", tier: "today", due_date: TODAY,
        } })).json();
        try {
            await openCard(page, made.id);
            const start = page.locator("#detailRepeatStartDate");
            await expect(start).toBeHidden();      // no repeat, no field
            await page.selectOption("#detailRepeat", "weekly");
            await expect(start).toBeVisible();
            await expect(start).toHaveValue(TODAY);
        } finally {
            await request.delete(`/api/tasks/${made.id}`);
        }
    });

    test("/recurring: a new template's Start on is blank, a set one saves, and after Stop after is refused", async ({ page, request }) => {
        const tag = `E2E501 tmpl ${Date.now()}`;
        await page.goto("/recurring?nosw=1");
        await page.waitForLoadState("networkidle");
        await page.locator("#recurringNew").click();
        const start = page.locator("#recurEditStartDate");
        await expect(start).toHaveValue("");
        await page.fill("#recurEditTitle", tag);
        const from = isoLocal(10);
        await start.fill(from);
        await page.locator("#recurEditSave").click();
        let tid = null;
        try {
            await expect(page.locator(".recurring-row", { hasText: tag }))
                .toContainText(`(from ${from})`);
            const all = await (await request.get("/api/recurring?all=1")).json();
            const rt = all.find((r) => r.title === tag);
            tid = rt.id;
            expect(rt.start_date).toBe(from);

            // Open it, put Stop after before Start on: refused in plain words.
            await page.locator(".recurring-row", { hasText: tag }).locator(".recurring-row-info").click();
            await expect(start).toHaveValue(from);
            await page.fill("#recurEditEndDate", isoLocal(5));
            await page.locator("#recurEditSave").click();
            await expect(page.locator("#recurEditResult"))
                .toContainText("The start date must be on or before the Stop after date.");
            const still = await (await request.get(`/api/recurring/${tid}`)).json();
            expect(still.end_date).toBeNull();
        } finally {
            if (tid) await request.delete(`/api/recurring/${tid}`);
        }
    });
});
