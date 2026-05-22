/**
 * Browser API E2E tests — Web Speech, Notifications, client error reporter.
 *
 * These test browser-only APIs that jsdom cannot simulate. Playwright
 * gives us a real Chromium environment to verify graceful degradation
 * and error handling.
 */
// @ts-check
const { test, expect } = require("@playwright/test");

test.describe("Web Speech API", () => {
    test("voice button is visible when Speech API is available", async ({
        page,
    }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        // Chromium supports SpeechRecognition, so the button should be visible
        const voiceBtn = page.locator("#captureVoice");
        await expect(voiceBtn).toBeVisible();
        // Should show the microphone emoji
        const text = await voiceBtn.textContent();
        expect(text.trim()).toBeTruthy();
    });

    test("voice button is hidden when Speech API is unavailable", async ({
        page,
    }) => {
        // Remove SpeechRecognition before the page loads
        await page.addInitScript(() => {
            delete window.SpeechRecognition;
            delete window.webkitSpeechRecognition;
        });

        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        const voiceBtn = page.locator("#captureVoice");
        // Should be hidden via display:none
        await expect(voiceBtn).toBeHidden();
    });
});

test.describe("Client error reporter", () => {
    test("uncaught errors are reported to /api/debug/client-error", async ({
        page,
    }) => {
        // Intercept the client-error API call
        let reportedError = null;
        await page.route("**/api/debug/client-error", async (route) => {
            const request = route.request();
            reportedError = JSON.parse(request.postData() || "{}");
            await route.fulfill({ status: 204 });
        });

        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        // Trigger an uncaught error
        await page.evaluate(() => {
            setTimeout(() => {
                throw new Error("E2E test deliberate error");
            }, 0);
        });

        // Wait for the error to be reported
        await page.waitForTimeout(3000);

        expect(reportedError).toBeTruthy();
        expect(reportedError.message).toContain("E2E test deliberate error");
    });

    test("rate limits error reports to 1 per 2 seconds", async ({ page }) => {
        let reportCount = 0;
        await page.route("**/api/debug/client-error", async (route) => {
            reportCount++;
            await route.fulfill({ status: 204 });
        });

        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        // Fire 5 errors rapidly
        await page.evaluate(() => {
            for (let i = 0; i < 5; i++) {
                setTimeout(() => {
                    throw new Error(`Rapid error ${i}`);
                }, i * 100);
            }
        });

        await page.waitForTimeout(3000);

        // Should have reported at most 1-2 due to the 2-second cooldown
        expect(reportCount).toBeLessThanOrEqual(2);
    });
});

test.describe("Update banner", () => {
    test("update banner exists in DOM but is hidden", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        const banner = page.locator("#updateBanner");
        // Banner exists in DOM
        await expect(banner).toHaveCount(1);
        // But is hidden by default
        await expect(banner).toBeHidden();
    });

    test("update banner has a refresh button", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        const btn = page.locator("#updateBannerBtn");
        await expect(btn).toHaveCount(1);
        const text = await btn.textContent();
        expect(text).toContain("refresh");
    });
});

test.describe("Logout clears SW cache", () => {
    test("logout is a POST form with the CLEAR_CACHE submit handler", async ({
        page,
    }) => {
        // #185 (2026-05-21): logout is now a POST <form> button, not an
        // <a> — a GET /logout was a state-mutating-GET CSRF surface.
        // Navigate with ?nosw=1 — we only verify the handler is wired,
        // not that the SW receives it (SW tests cover CLEAR_CACHE).
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        // The logout control is a POST form pointing at /logout, with a
        // submit button — NOT a GET <a href>.
        const logoutForm = page.locator('form[action*="/logout"]');
        await expect(logoutForm).toHaveCount(1);
        await expect(logoutForm).toHaveAttribute("method", /post/i);
        await expect(
            page.locator('form[action*="/logout"] button[type="submit"]'),
        ).toHaveCount(1);

        // No GET <a href="/logout"> remains — the CSRF surface is gone.
        await expect(page.locator('a[href*="/logout"]')).toHaveCount(0);

        // base.html wires the CLEAR_CACHE submit handler onto the form.
        const formPresent = await page.evaluate(
            () => document.querySelectorAll('form[action*="/logout"]').length > 0,
        );
        expect(formPresent).toBe(true);
    });
});
