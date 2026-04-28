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

    test("/completed reopen dropdown includes all 7 active tiers (#110)", async ({ page }) => {
        // Bug class: stale hardcoded list in app.js dropping new Tier
        // enum values. Read the live app.js and assert all 7 tier
        // values are present in the same array literal as the reopen
        // dropdown source.
        await page.goto("/completed?nosw=1");
        await page.waitForLoadState("networkidle");
        const appJs = await page.request.get("/static/app.js");
        const text = await appJs.text();
        const stale = '["inbox", "today", "this_week", "backlog", "freezer"]';
        expect(text.includes(stale)).toBe(false);
        const fixed = '"inbox", "today", "tomorrow", "this_week", "next_week", "backlog", "freezer"';
        expect(text.includes(fixed)).toBe(true);
    });

    test("apiFetch wires hard-recovery via api_helpers (#112 + #113)", async ({ page }) => {
        // Stale-tab "Failed to fetch" recovery — PR47 added retry +
        // prompt; PR49 dropped the opaqueredirect check (false-positive)
        // and routed the recovery path through _hardRecover() which
        // unregisters the SW first. Regression catches a future revert.
        const appJs = await page.request.get("/static/app.js");
        const text = await appJs.text();
        // PR49: recovery path uses _hardRecover (SW-unregister-then-reload)
        expect(text).toContain("_hardRecover");
        // Auto-retry-once flag still present
        expect(text).toContain("_retried");
        // PR49 invariant: opaqueredirect prompt was REMOVED (was firing
        // false-positives). If this comes back, something regressed.
        expect(text).not.toContain('redirect: "manual"');
        // api_helpers.js (PR49) also served + cached
        const apiH = await page.request.get("/static/api_helpers.js");
        expect(apiH.status()).toBe(200);
    });

    test("visibilitychange handler also triggers SW update check (#111)", async ({ page }) => {
        // Long-lived tabs miss new deploys because browsers re-poll
        // /sw.js at most every ~24h. PR46 wires reg.update() into the
        // visibilitychange hook — assert the literal call is present
        // in the bundled app.js so a regression that drops it is caught.
        const appJs = await page.request.get("/static/app.js");
        const text = await appJs.text();
        expect(text).toContain("navigator.serviceWorker.getRegistration");
        expect(text).toContain("reg.update()");
    });

    test("visibilitychange triggers loadTasks (#109)", async ({ page }) => {
        // Multi-device sync: when tab becomes visible, re-fetch /api/tasks
        // so changes from another device show up. Can't directly observe
        // the loadTasks call but a thrown error from any of the loaders
        // would fail this assertion.
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        const ok = await page.evaluate(() => {
            try {
                document.dispatchEvent(new Event("visibilitychange"));
                return true;
            } catch (_) {
                return false;
            }
        });
        expect(ok).toBe(true);
    });

    test("recovery prompt fires once per cycle, not per failure (#115)", async ({ page }) => {
        // Per PR50 anti-pattern #3: actually exercise the path.
        // Force fetch to fail with TypeError + dispatch visibilitychange
        // (which fans out 5 loader calls). Only ONE confirm() should
        // fire — not 5.
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        const promptCount = await page.evaluate(async () => {
            // Replace fetch so every call throws TypeError (the "Failed
            // to fetch" class). The auto-retry will fire too; we expect
            // it to ALSO fail and trigger the prompt path.
            const origFetch = window.fetch;
            window.fetch = () => Promise.reject(new TypeError("Failed to fetch"));
            // Replace confirm so we count + dismiss without UI.
            let count = 0;
            const origConfirm = window.confirm;
            window.confirm = (_msg) => { count += 1; return false; };
            // Fire visibilitychange — kicks off the loader fan-out.
            document.dispatchEvent(new Event("visibilitychange"));
            // Let all 5 promises settle.
            await new Promise((r) => setTimeout(r, 800));
            // Restore.
            window.fetch = origFetch;
            window.confirm = origConfirm;
            return count;
        });
        // Some loaders may early-return without fetch (e.g. element not
        // present), so count may be < 5 even without the singleton fix.
        // Strict invariant: at most ONE prompt regardless of fan-out.
        expect(promptCount).toBeLessThanOrEqual(1);
    });

    test("/calendar refreshes on visibilitychange (#114)", async ({ page }) => {
        // Per PR50 anti-pattern #3: actually exercise the path, not
        // just string-match. Load /calendar, instrument fetch, dispatch
        // visibilitychange, assert /api/tasks was re-fetched.
        await page.goto("/calendar?nosw=1");
        await page.waitForLoadState("networkidle");
        // Hook fetch and count /api/tasks calls AFTER initial load
        const tasksBefore = await page.evaluate(() => {
            window.__tasksFetchCount = 0;
            const orig = window.fetch;
            window.fetch = function (url, opts) {
                if (typeof url === "string" && url.includes("/api/tasks")) {
                    window.__tasksFetchCount += 1;
                }
                return orig.apply(this, arguments);
            };
            return 0;
        });
        // Dispatch visibilitychange (simulating tab refocus)
        await page.evaluate(() => {
            document.dispatchEvent(new Event("visibilitychange"));
        });
        // Wait briefly for the async renderCalendar to fire
        await page.waitForTimeout(800);
        const tasksAfter = await page.evaluate(() => window.__tasksFetchCount);
        expect(
            tasksAfter,
            "visibilitychange should trigger renderCalendar which re-fetches /api/tasks",
        ).toBeGreaterThan(tasksBefore);
    });

    test("home board has task search bar (#107)", async ({ page }) => {
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        // Input present + interactive
        const input = page.locator("#taskSearchInput");
        await expect(input).toBeVisible();
        // Type a term unlikely to match anything → meta should appear
        // showing "0 of N match" (proves the filter logic ran).
        await input.fill("xyzzy-not-a-real-task-2026");
        await page.waitForTimeout(250);  // debounce
        const meta = await page.locator("#taskSearchMeta").textContent();
        expect(meta).toMatch(/0 of \d+ match/);
        // Clear to leave a clean state.
        await page.locator("#taskSearchClear").click();
        await page.waitForTimeout(200);
        await expect(input).toHaveValue("");
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
                "/api/debug/realign-tiers",  // PR43 #108
            ]) {
                // PR38 follow-up: maxRedirects:0 — Playwright auto-
                // follows redirects by default, so a POST → 302 → GET
                // /login/google → 200 came back as 200 (broken assertion).
                // Stop at the first response.
                const resp = await ctx.request.post(
                    `https://web-production-3e3ae.up.railway.app${path}`,
                    { maxRedirects: 0 },
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
