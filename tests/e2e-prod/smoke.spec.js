/**
 * Post-deploy prod smoke tests.
 *
 * These run against the LIVE deployed Railway URL, not the local bypass
 * server. They exist to catch the class of bugs that works locally but
 * breaks in production — CSP headers, cookie domain/secure flags,
 * HTTPS-only redirects, real Postgres differences, Railway proxy quirks.
 *
 * Requires env var: TASKMANAGER_SESSION_COOKIE
 *   Set it to a valid Flask session cookie value (copy from a logged-in
 *   browser session — see README "Post-deploy validation" section for
 *   step-by-step instructions).
 *
 * Run:
 *   export TASKMANAGER_SESSION_COOKIE="<paste cookie value>"
 *   npm run test:e2e:prod
 *
 * If the cookie is expired or missing these tests will return 401/302
 * from the app and fail loudly. Run scripts/validate_deploy.py first —
 * its --auth-check mode gives much cleaner refresh instructions than
 * Playwright's failure output.
 */
// @ts-check
const { test, expect } = require("@playwright/test");

const COOKIE_VALUE = process.env.TASKMANAGER_SESSION_COOKIE;

// Inject the session cookie into every test's browser context. Runs
// before each test, so even a test that does its own navigation
// starts out authenticated.
test.beforeEach(async ({ context, baseURL }) => {
    if (!COOKIE_VALUE) {
        throw new Error(
            "TASKMANAGER_SESSION_COOKIE env var is required for prod smoke tests. " +
            "See README 'Post-deploy validation' section.",
        );
    }
    const url = new URL(baseURL);
    await context.addCookies([
        {
            name: "session",
            value: COOKIE_VALUE,
            domain: url.hostname,
            path: "/",
            httpOnly: true,
            secure: true,
            sameSite: "Lax",
        },
    ]);
});

test.describe("Prod smoke — auth preflight", () => {
    test("session cookie is accepted by /api/auth/status", async ({
        request,
    }) => {
        const resp = await request.get("/api/auth/status");
        expect(
            resp.status(),
            "cookie may be expired — run scripts/validate_deploy.py --auth-check for refresh instructions",
        ).toBe(200);
        const data = await resp.json();
        expect(data.authenticated).toBe(true);
        expect(data.email).toBeTruthy();
    });
});

test.describe("Prod smoke — page renders", () => {
    test("home page renders without JS errors", async ({ page }) => {
        const errors = [];
        page.on("pageerror", (err) => errors.push(err.message));

        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        // Look for the capture bar as proof we got the real Tasks page,
        // not a login redirect.
        await expect(page.locator("#captureInput")).toBeVisible();
        expect(errors).toEqual([]);
    });

    test("goals page renders without JS errors", async ({ page }) => {
        const errors = [];
        page.on("pageerror", (err) => errors.push(err.message));

        await page.goto("/goals?nosw=1");
        await page.waitForLoadState("networkidle");

        // Category filter confirms goals.js loaded and the template rendered.
        await expect(page.locator("#filterCategory")).toBeVisible();
        expect(errors).toEqual([]);
    });
});

test.describe("Prod smoke — API responds correctly", () => {
    test("/api/tasks returns an array (shape check, not content)", async ({
        request,
    }) => {
        const resp = await request.get("/api/tasks");
        expect(resp.status()).toBe(200);
        const body = await resp.json();
        expect(Array.isArray(body)).toBe(true);
        // Don't assert length — production data is whatever the user has.
    });

    test("/healthz reports ok and exposes git_sha", async ({ request }) => {
        const resp = await request.get("/healthz");
        expect(resp.status()).toBe(200);
        const data = await resp.json();
        expect(data.status).toBe("ok");
        // git_sha is "dev" locally, a real SHA on Railway — we don't
        // assert the value, just that it's present (a deploy without a
        // SHA would be a misconfigured build).
        expect(data.git_sha).toBeTruthy();
        expect(data.git_sha).not.toBe("dev");
    });
});
