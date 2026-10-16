/**
 * #488: the /scan review said "Review Task Candidates" and "Add All to
 * Inbox" whatever you scanned as. Goals go to /goals and projects to
 * /projects, so the heading, hint and both Add buttons now follow the kind
 * the scan came back as — and switch back for the next scan.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
const ROWS = {
    tasks: [{ title: "Call the dentist", type: "work", included: true }],
    goals: [{ title: "Run a half marathon", category: "health", priority: "should",
              target_quarter: "", actions: "", included: true }],
    projects: [{ title: "Kitchen renovation", type: "personal", target_quarter: "", included: true }],
};
const WANT = {
    tasks: ["Review Task Candidates", "before adding to inbox", "Add All to Inbox", "Add Selected to Inbox"],
    goals: ["Review Goal Candidates", "before adding to your goals", "Add All to Goals", "Add Selected to Goals"],
    projects: ["Review Project Candidates", "before adding to your projects", "Add All to Projects", "Add Selected to Projects"],
};

async function scanAs(page, kind) {
    await page.locator(`input[name=parseAs][value=${kind}]`).check();
    await page.setInputFiles("#scanFile", { name: "note.png", mimeType: "image/png", buffer: Buffer.from(PNG, "base64") });
    await page.locator("#scanSubmitBtn").click();
    await expect(page.locator("#scanReview")).toBeVisible({ timeout: 10000 });
}

async function expectCopy(page, kind) {
    const [heading, hint, all, selected] = WANT[kind];
    await expect(page.locator("#scanReview h2")).toHaveText(heading);
    await expect(page.locator("#scanReview p").first()).toContainText(hint);
    await expect(page.locator("#scanConfirmAll")).toHaveText(all);
    await expect(page.locator("#scanConfirmSelected")).toHaveText(selected);
}

test.describe("#488 the /scan review words itself by kind", () => {
    test.beforeEach(async ({ page }) => {
        await page.route("**/api/scan/upload", async (route) => {
            const kind = (route.request().postDataBuffer() || Buffer.from("")).toString("latin1")
                .match(/name="parse_as"\r\n\r\n(\w+)/)[1];
            await route.fulfill({ json: { ocr_text: "x", kind, candidates: ROWS[kind] } });
        });
        await page.goto("/scan?nosw=1");
    });

    for (const kind of ["goals", "projects"]) {
        test(`${kind}: heading, hint and both Add buttons name ${kind}`, async ({ page }) => {
            await scanAs(page, kind);
            await expectCopy(page, kind);
        });
    }

    test("tasks still say Inbox (the quiet case), and Scan Another resets it", async ({ page }) => {
        await scanAs(page, "goals");
        await expectCopy(page, "goals");
        await page.locator("#scanRescan").click();
        await scanAs(page, "tasks");
        await expectCopy(page, "tasks");
    });
});
