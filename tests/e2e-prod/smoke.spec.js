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

// Inject the cookie into every test's browser context. We add it under
// BOTH names so the same env var works regardless of credential format:
//
//   - "validator_token" — a long-lived signed cookie minted via
//     `flask mint-validator-cookie` or `scripts/mint_validator_cookie.py`.
//     Authenticates GET routes (page renders, /api/tasks list) thanks
//     to login_required's read-only branch.
//
//   - "session" — a real Flask session cookie copied from a logged-in
//     browser. Legacy path; works for everything but expires on
//     Flask-Dance token refresh.
//
// Whichever credential the env var actually is, one of the two cookie
// names will hit the right server-side path. The other is silently
// ignored.
test.beforeEach(async ({ context, baseURL }) => {
    if (!COOKIE_VALUE) {
        throw new Error(
            "TASKMANAGER_SESSION_COOKIE env var is required for prod smoke tests. " +
            "See README 'Post-deploy validation' section.",
        );
    }
    const url = new URL(baseURL);
    const baseCookie = {
        value: COOKIE_VALUE,
        domain: url.hostname,
        path: "/",
        httpOnly: true,
        secure: true,
        sameSite: "Lax",
    };
    await context.addCookies([
        { ...baseCookie, name: "validator_token" },
        { ...baseCookie, name: "session" },
    ]);
});

test.describe("Prod smoke — auth preflight", () => {
    test("session cookie is accepted by /api/auth/status", async ({
        page,
    }) => {
        // page.request shares the browser context's cookie jar, so the
        // cookies set in beforeEach are sent. The standalone `request`
        // fixture has its OWN jar and would need extraHTTPHeaders
        // configured separately.
        const resp = await page.request.get("/api/auth/status");
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

    /**
     * Bug #55 (2026-04-25): /architecture pages embed Mermaid diagrams
     * loaded from cdn.jsdelivr.net via <script type="module">. After a
     * deploy, a stale-SW-cache combo could leave the diagrams
     * unrendered (raw text inside <pre>). Phase 6 verification ran in
     * dev-bypass (no CSP, no SW) and missed it. This test runs
     * against the live URL and asserts at least one Mermaid SVG
     * actually rendered — catching CSP regressions, jsdelivr
     * outages, ad-blocker effects, and stale-SW combos.
     */
    test("architecture page renders Mermaid diagrams", async ({ page }) => {
        const errors = [];
        page.on("pageerror", (err) => errors.push(err.message));

        await page.goto("/architecture?nosw=1");
        await page.waitForLoadState("networkidle");

        // Mermaid script loads from CDN then converts every
        // <pre class="mermaid"> into an <svg>. Wait up to 10s for the
        // first conversion to complete — accommodates slow CDN fetch
        // on a first-deploy cold container.
        await expect(
            page.locator("pre.mermaid svg").first(),
        ).toBeVisible({ timeout: 10_000 });

        // Sanity: should have multiple diagrams rendered, not just one.
        // /architecture currently has 10 (1 ER + 4 simple flows + 4
        // detailed flows + 1 ship-lifecycle). Assert >=5 to leave
        // headroom for content changes without breaking the gate.
        const svgCount = await page.locator("pre.mermaid svg").count();
        expect(svgCount).toBeGreaterThanOrEqual(5);

        expect(errors).toEqual([]);
    });
});

test.describe("Prod smoke — API responds correctly", () => {
    test("/api/tasks returns an array (shape check, not content)", async ({
        page,
    }) => {
        // Use page.request so the validator_token cookie is sent.
        const resp = await page.request.get("/api/tasks");
        expect(resp.status()).toBe(200);
        const body = await resp.json();
        expect(Array.isArray(body)).toBe(true);
        // Don't assert length — production data is whatever the user has.
    });

    test("/healthz reports ok and exposes git_sha", async ({ page }) => {
        // /healthz is public so request fixture would also work, but we
        // standardize on page.request for consistency.
        const resp = await page.request.get("/healthz");
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

// ============================================================================
// PR37 — feature-specific prod smoke. Each shipped feature this session
// gets at least one assertion against the LIVE deployed URL so the
// "DEPLOY GREEN + 6/6 generic smoke" gate actually proves the user-
// facing surface works on prod, not just that the box is on.
// ============================================================================

test.describe("Prod smoke — pages render", () => {
    const pages = [
        { path: "/import?nosw=1", anchor: "#importTasksBtn" },
        { path: "/calendar?nosw=1", anchor: "#calendarGrid" },
        { path: "/recurring?nosw=1", anchor: ".recurring-page" },
        { path: "/projects?nosw=1", anchor: "#projectsBoard" },
        { path: "/scan?nosw=1", anchor: "#scanContainer" },
        { path: "/voice-memo?nosw=1", anchor: "#voiceMemoContainer" },
        { path: "/recycle-bin?nosw=1", anchor: "#recycleContainer" },
        { path: "/docs?nosw=1", anchor: "#filters" },  // PR25 docs section
    ];
    for (const pg of pages) {
        test(`${pg.path} loads without JS errors`, async ({ page }) => {
            const errors = [];
            page.on("pageerror", (err) => errors.push(err.message));
            await page.goto(pg.path);
            await page.waitForLoadState("networkidle");
            await expect(page.locator(pg.anchor).first()).toBeVisible({ timeout: 5_000 });
            expect(errors).toEqual([]);
        });
    }
});

test.describe("Prod smoke — feature surfaces", () => {
    test("/projects bulk Select toggle is wired (#90)", async ({ page }) => {
        await page.goto("/projects?nosw=1");
        await page.waitForLoadState("networkidle");
        const toggle = page.locator("#projectsBulkToggle");
        await expect(toggle).toBeVisible();
        await toggle.click();
        await expect(page.locator("#projectsBulkToolbar")).toBeVisible();
        // checkboxes must appear on each card
        await expect(page.locator(".project-bulk-cb").first()).toBeVisible({ timeout: 3_000 });
    });

    test("/projects has goal filter dropdown (#96)", async ({ page }) => {
        await page.goto("/projects?nosw=1");
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#projectFilterGoal")).toBeVisible();
        // Should have at least one option ("All goals" + N goals)
        const opts = await page.locator("#projectFilterGoal option").count();
        expect(opts).toBeGreaterThanOrEqual(1);
    });

    test("/import shows Excel template download links (#91)", async ({ page }) => {
        await page.goto("/import?nosw=1");
        await page.waitForLoadState("networkidle");
        // Expand the Tasks Excel mode and confirm the template link points right
        await page.click("#importTasksExcelBtn");
        const link = page.locator('a[href="/api/import/template/tasks.xlsx"]').first();
        await expect(link).toBeVisible();
    });

    test("/api/import/template/{kind}.xlsx serves a workbook for each kind (#91)", async ({ page }) => {
        for (const kind of ["tasks", "goals", "projects"]) {
            const resp = await page.request.get(`/api/import/template/${kind}.xlsx`);
            expect(resp.status()).toBe(200);
            const ct = resp.headers()["content-type"] || "";
            expect(ct).toContain("spreadsheetml");
            const buf = await resp.body();
            // Real .xlsx is a ZIP — magic bytes "PK\x03\x04"
            expect(buf[0]).toBe(0x50);
            expect(buf[1]).toBe(0x4b);
        }
    });

    test("/calendar renders day cells + Unscheduled side panel (#94)", async ({ page }) => {
        await page.goto("/calendar?nosw=1");
        await page.waitForLoadState("networkidle");
        // 12 cells (Mon–Sat × 2 weeks per #72)
        await expect(page.locator(".calendar-cell").first()).toBeVisible({ timeout: 5_000 });
        const cellCount = await page.locator(".calendar-cell").count();
        expect(cellCount).toBe(12);
        await expect(page.locator("#calendarUnscheduled")).toBeVisible();
    });

    test("home board has both filter bars (#92)", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#projectFilterBar")).toBeVisible();
        await expect(page.locator("#goalFilterBar")).toBeVisible();
        // Each bar must have at least one chip rendered (the All button).
        await expect(page.locator("#projectFilterBar button").first()).toBeVisible();
        await expect(page.locator("#goalFilterBar button").first()).toBeVisible();
    });

    test("task detail panel exposes Stop-after end_date input (#101)", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        // The repeat-end-date row exists in the template (hidden until a
        // frequency is selected). Just confirm the markup shipped.
        await expect(page.locator("#detailRepeatEndDate")).toHaveCount(1);
    });
});

test.describe("Prod smoke — admin endpoints (read-only checks)", () => {
    test("backfill endpoints exist and reject unauthenticated POST", async ({ browser }) => {
        // PR38 audit fix D2: prior version accepted 200 as valid, which
        // would have masked a bug where the route ran the backfill
        // against prod data on an un-tokened request. Use a NEW
        // cookieless context so the validator cookie never attaches —
        // the only acceptable responses are 302 (OAuth redirect), 401,
        // 403, or 405. A 200 here means the auth gate is broken.
        const ctx = await browser.newContext();  // no cookies, no env
        try {
            for (const path of [
                "/api/debug/backfill/project-colors",
                "/api/debug/backfill/today-tomorrow-due-date",
                "/api/debug/backfill/task-goal-from-project",
            ]) {
                const resp = await ctx.request.post(
                    `https://web-production-3e3ae.up.railway.app${path}`,
                );
                expect(
                    [302, 401, 403, 405],
                    `${path} returned ${resp.status()} without auth — gate broken!`,
                ).toContain(resp.status());
                // 404 would mean the route was dropped — that's the failure
                // we want this test to catch.
                expect(resp.status()).not.toBe(404);
            }
        } finally {
            await ctx.close();
        }
    });
});
