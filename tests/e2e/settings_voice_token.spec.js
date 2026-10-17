/**
 * #499: make, copy and revoke the Siri voice-review token on /settings —
 * on the phone, no laptop. Runs at 1280 (chromium) and 375
 * (chromium-mobile). Real API throughout. Whether a revoked token is
 * then REFUSED by /api/voice-review/* can't be seen here: the local dev
 * bypass authenticates every request before the bearer is read
 * (auth.voice_action_or_login). tests/test_voice_token_settings.py proves
 * that path; this checks what the server recorded.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const card = (page) => page.locator("#settingsVoiceToken");

async function openSettings(page) {
    await page.goto("/settings?nosw=1");
    await page.waitForLoadState("networkidle");
    await expect(card(page)).toBeVisible();
}

async function makeToken(page) {
    await card(page).getByRole("button", { name: "Make a new token" }).click();
    const field = page.locator("#voiceTokenValue");
    await expect(field).toBeVisible();
    const token = await field.inputValue();
    expect(token.length).toBeGreaterThan(40);
    const jti = (await page.locator("#voiceTokenMakeStatus").textContent())
        .match(/id ([0-9a-f]{16})/)[1];
    return { token, jti };
}

async function listed(request, jti) {
    const r = await request.get("/api/settings/voice-tokens");
    expect(r.status()).toBe(200);
    return (await r.json()).tokens.find((t) => t.jti === jti);
}

test.describe("#499 Siri voice token on /settings", () => {
    test("make → copy → listed → revoke → marked revoked", async ({ page, context, request }) => {
        await context.grantPermissions(["clipboard-read", "clipboard-write"]);
        await openSettings(page);
        const { token, jti } = await makeToken(page);
        await expect(card(page)).toContainText("this is the only time it's shown");
        await expect(card(page).locator(".voice-token-where")).toContainText("Authorization");

        await page.locator("#voiceTokenCopy").click();
        await expect(page.locator("#voiceTokenCopyStatus")).toHaveText(/Copied/);
        expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(token);

        await page.locator("#voiceTokenCopyHeader").click();
        await expect.poll(() => page.evaluate(() => navigator.clipboard.readText()))
            .toBe(`Bearer ${token}`);

        // Listed by id and dates only — the token itself is never sent back.
        const before = await listed(request, jti);
        expect(before.revoked).toBeNull();
        expect(JSON.stringify(before)).not.toContain(token);

        // The new row is listed, Active, with a Revoke.
        const row = page.locator(`.voice-token-row[data-jti="${jti}"]`);
        await expect(row).toContainText("Active");
        page.once("dialog", (d) => d.accept());
        await row.getByRole("button", { name: /Revoke/ }).click();
        await expect(page.locator("#voiceTokenRevokeStatus")).toHaveText(`Revoked ${jti}.`);
        await expect(page.locator(`.voice-token-row[data-jti="${jti}"]`)).toContainText("Revoked");
        await expect(page.locator(`.voice-token-row[data-jti="${jti}"] button`)).toHaveCount(0);

        expect((await listed(request, jti)).revoked).toBeTruthy();

        // Done hides the token and clears the field.
        await page.locator("#voiceTokenDone").click();
        await expect(page.locator("#voiceTokenNew")).toBeHidden();
        expect(await page.locator("#voiceTokenValue").inputValue()).toBe("");
    });

    test("with no clipboard API the token is selected for the iOS Copy menu", async ({ page }) => {
        await openSettings(page);
        const { token } = await makeToken(page);
        await page.evaluate(() => {
            Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
        });
        await page.locator("#voiceTokenCopy").click();
        await expect(page.locator("#voiceTokenCopyStatus")).toHaveText(/Copied|Selected/);
        const sel = await page.locator("#voiceTokenValue").evaluate(
            (el) => [el.selectionStart, el.selectionEnd]);
        expect(sel).toEqual([0, token.length]);
    });

    test("while the new token shows, a deploy reload holds off", async ({ page }) => {
        await openSettings(page);
        expect(await page.evaluate(() => window.__userIsBusy())).toBe(false);
        await makeToken(page);
        await page.locator("#voiceTokenCopy").blur();
        await page.evaluate(() => document.activeElement && document.activeElement.blur());
        expect(await page.evaluate(() => window.__userIsBusy())).toBe(true);
        await page.locator("#voiceTokenDone").click();
        await page.evaluate(() => document.activeElement && document.activeElement.blur());
        expect(await page.evaluate(() => window.__userIsBusy())).toBe(false);
    });

    test("Revoke by id: a laptop-made token's id, and a bad id says why", async ({ page, request }) => {
        await openSettings(page);
        const { jti } = await makeToken(page);
        await page.locator("#voiceTokenDone").click();

        await page.locator("#voiceTokenRevokeId").fill("not-an-id");
        await page.locator("#voiceTokenRevokeById").click();
        await expect(page.locator("#voiceTokenRevokeStatus")).toHaveText(/isn't a token id/);

        await page.locator("#voiceTokenRevokeId").fill(`jti=${jti.toUpperCase()}`);
        page.once("dialog", (d) => d.accept());
        await page.locator("#voiceTokenRevokeById").click();
        await expect(page.locator("#voiceTokenRevokeStatus")).toHaveText(`Revoked ${jti}.`);
        await expect(page.locator("#voiceTokenRevokeId")).toHaveValue("");
        expect((await listed(request, jti)).revoked).toBeTruthy();
    });

    test("a failed make says why and shows no token", async ({ page }) => {
        await openSettings(page);
        await page.route("**/api/settings/voice-tokens", (route) =>
            route.request().method() === "POST"
                ? route.fulfill({ status: 429, contentType: "application/json",
                    body: JSON.stringify({ error: "Too many new tokens — wait a while and try again." }) })
                : route.fallback());
        await card(page).getByRole("button", { name: "Make a new token" }).click();
        await expect(page.locator("#voiceTokenMakeStatus"))
            .toHaveText("Couldn't make a token: Too many new tokens — wait a while and try again.");
        await expect(page.locator("#voiceTokenNew")).toBeHidden();
    });

    test("fits the screen; phone tap targets are 44px", async ({ page }, testInfo) => {
        await openSettings(page);
        await makeToken(page);
        const overflow = await page.evaluate(
            () => document.documentElement.scrollWidth - window.innerWidth);
        expect(overflow).toBeLessThanOrEqual(0);
        if (testInfo.project.name === "chromium-mobile") {
            for (const sel of ["#voiceTokenMake", "#voiceTokenCopy", "#voiceTokenCopyHeader",
                "#voiceTokenDone", "#voiceTokenRevokeById", "#voiceTokenDays",
                "#voiceTokenRevokeId", ".voice-token-revoke"]) {
                const box = await page.locator(sel).first().boundingBox();
                expect(box.height, sel).toBeGreaterThanOrEqual(44);
            }
        }
    });
});
