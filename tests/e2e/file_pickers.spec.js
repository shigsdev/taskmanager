/**
 * #455: every file picker on /import and /scan was a `display:none` input
 * behind a <label> — the label isn't a Tab stop and a display:none input
 * can't take focus, so no Excel / .docx / transcript / scan flow could be
 * started from the keyboard. The inputs are now clipped (still focusable,
 * as /reflection's "+ Add file" already was) and the label shows the focus
 * ring. import.js also called input.click() from the label's own click,
 * on top of the label's native for= — a second picker request (the double
 * trigger scan.js documents as breaking iOS Safari).
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const PICKERS = [
    { path: "/import", open: "#importTasksExcelBtn", input: "#importTasksExcelFile", label: "#importTasksExcelFileLabel" },
    { path: "/import", open: "#importProjectsExcelBtn", input: "#importProjectsExcelFile", label: "#importProjectsExcelFileLabel" },
    { path: "/import", open: "#importDocxBtn", input: "#importDocxFile", label: "#importDocxFileLabel" },
    { path: "/import", open: "#importGoalsBtn", input: "#importFile", label: "#importFileLabel" },
    { path: "/import", open: "#importTranscriptUploadBtn", input: "#importTranscriptFile", label: "#importTranscriptFileLabel" },
    { path: "/scan", open: null, input: "#scanFile", label: "#scanFileLabel" },
];

test.describe("#455 file pickers work from the keyboard", () => {
    for (const p of PICKERS) {
        test(`${p.path} ${p.input}: Tab-reachable, Enter opens the picker, label shows focus`, async ({ page }) => {
            await page.goto(`${p.path}?nosw=1`);
            if (p.open) await page.locator(p.open).click();
            await expect(page.locator(p.label)).toBeVisible();

            // Reached by keyboard: Tab from the control just before it.
            await page.locator(p.input).evaluate((el) => {
                const all = [...document.querySelectorAll("a[href], button, input, select, textarea, [tabindex]")]
                    .filter((n) => n.tabIndex >= 0 && !n.disabled && n.getClientRects().length);
                const i = all.indexOf(el);
                (i > 0 ? all[i - 1] : document.body).focus();
            });
            await page.keyboard.press("Tab");
            await expect(page.locator(p.input)).toBeFocused();

            const outline = await page.locator(p.label).evaluate((el) => getComputedStyle(el).outlineStyle);
            expect(outline).not.toBe("none");

            const chooser = page.waitForEvent("filechooser", { timeout: 3000 });
            await page.keyboard.press("Enter");
            expect(await chooser).toBeTruthy();
        });
    }

    test("/import: a click on the label asks for ONE picker, not two", async ({ page }) => {
        await page.goto("/import?nosw=1");
        await page.locator("#importTasksExcelBtn").click();
        let opened = 0;
        page.on("filechooser", () => { opened += 1; });
        await page.locator("#importTasksExcelFileLabel").click();
        await page.waitForTimeout(800);
        expect(opened).toBe(1);
    });
});
