/**
 * #464: a failed Finish & analyze always went to the error screen with
 * "Your transcript was saved … it's in your history", and stopped the
 * autosave. A failure before the server saves (the rate limit, a dropped
 * connection) saved nothing — it now goes back to writing with the text,
 * like #431. Only an answer saying `saved: true` gets the old screen.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const draftText = (page) => page.evaluate(async () => {
    const r = await fetch("/api/reflection/draft", { credentials: "same-origin" });
    const body = await r.json();
    return body.draft ? body.draft.transcript : null;
});

const deleteDraft = (page) => page.evaluate(() => fetch("/api/reflection/draft", {
    method: "DELETE", credentials: "same-origin",
}));

// Only the submit itself; drafts, history and the rest go through.
const stubSubmit = (page, reply) => page.route("**/api/reflection", (route) =>
    route.request().method() === "POST" ? route.fulfill(reply) : route.fallback());

test.describe("#464 a failed Finish & analyze", () => {
    test.beforeEach(async ({ page }) => {
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        await deleteDraft(page);
        await page.reload();
        await page.waitForLoadState("networkidle");
    });

    test.afterEach(async ({ page }) => {
        await page.unroute("**/api/reflection").catch(() => {});
        await deleteDraft(page).catch(() => {});
    });

    test("that saved nothing (429) keeps the text and the draft, and says so", async ({ page }) => {
        const text = "A long sitting that must not vanish.";
        await page.locator("#reflText").fill(text);
        await expect.poll(() => draftText(page), { timeout: 10000 }).toBe(text);

        await stubSubmit(page, {
            status: 429, contentType: "text/html",
            body: "<h1>Too Many Requests</h1>",
        });
        await page.locator("#reflAnalyzeBtn").click();

        await expect(page.locator("#reflStateInput")).toBeVisible();
        await expect(page.locator("#reflStateError")).toBeHidden();
        await expect(page.locator("#reflText")).toHaveValue(text);
        await expect(page.locator("#reflInterimError")).toHaveText(
            "Couldn't send it for analysis: too many analyses in a minute — wait a minute "
            + "and try again. Nothing went to your history — your text is still here, and "
            + "still saved as your draft.");

        // The autosave is still on: an edit reaches the draft.
        await page.locator("#reflText").press("End");
        await page.locator("#reflText").type(" More.");
        await expect(page.locator("#reflInterimError")).toBeHidden();
        await page.evaluate(() => window.__reflectionSaveDraftNow());
        await expect.poll(() => draftText(page), { timeout: 10000 }).toBe(text + " More.");
    });

    test("a lost connection also stays on the writing view", async ({ page }) => {
        const text = "Written on a train.";
        await page.locator("#reflText").fill(text);
        // apiFetch retries once, then offers a reload (a confirm — dismissed).
        page.on("dialog", (d) => d.dismiss());
        await page.route("**/api/reflection", (route) =>
            route.request().method() === "POST" ? route.abort("connectionreset") : route.fallback());
        await page.locator("#reflAnalyzeBtn").click();
        await expect(page.locator("#reflStateInput")).toBeVisible();
        await expect(page.locator("#reflText")).toHaveValue(text);
        await expect(page.locator("#reflInterimError")).toHaveText(
            "Couldn't send it for analysis: Failed to fetch. Nothing went to your history — "
            + "your text is still here, and still saved as your draft.");
    });

    test("a refused input stays on the writing view with the server's reason", async ({ page }) => {
        const text = "Something the server turned down.";
        await page.locator("#reflText").fill(text);
        await stubSubmit(page, { status: 400, json: { error: "JSON body or audio file required" } });
        await page.locator("#reflAnalyzeBtn").click();
        await expect(page.locator("#reflStateInput")).toBeVisible();
        await expect(page.locator("#reflText")).toHaveValue(text);
        await expect(page.locator("#reflInterimError")).toHaveText(
            "Couldn't send it for analysis: JSON body or audio file required. Nothing went "
            + "to your history — your text is still here, and still saved as your draft.");
    });

    test("that saved the transcript keeps the history screen (the quiet case)", async ({ page }) => {
        await page.locator("#reflText").fill("Saved, then the analysis failed.");
        await stubSubmit(page, {
            status: 422,
            json: { error: "Analysis failed: the model is busy.", saved: true, reflection_id: "x" },
        });
        await page.locator("#reflAnalyzeBtn").click();
        await expect(page.locator("#reflStateError")).toBeVisible();
        await expect(page.locator("#reflErrorMessage")).toHaveText("Analysis failed: the model is busy.");
        await expect(page.locator("#reflErrorSaved")).toBeVisible();
    });
});
