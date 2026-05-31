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

// macOS no-IPv6 workaround — must be required before @playwright/test so
// the patched dns.lookup is in place by the time the happy-eyeballs agent
// resolves a hostname. See tests/playwright-globalSetup.js for the
// full explanation.
require("../playwright-globalSetup.js");

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

    test("capture bar 'open full task window' enters create mode (#269)", async ({ page }) => {
        // Behavioral (not string-match): clicking #captureFull must open
        // the detail panel in CREATE mode — header "New Task" + the
        // existing-task-only controls (Complete/Delete) hidden. Read-only
        // (no save), so it never mutates prod data. Guards the #269 wiring
        // under prod CSP/SW, which the dev-bypass Phase 6 can't.
        const errors = [];
        page.on("pageerror", (err) => errors.push(err.message));
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");

        await page.fill("#captureInput", "Prod smoke draft");
        await page.click("#captureFull");

        const panel = page.locator("#detailOverlay");
        await expect(panel).toBeVisible();
        await expect(page.locator("#detailHeaderTitle")).toHaveText("New Task");
        await expect(page.locator("#detailTitle")).toHaveValue("Prod smoke draft");
        // create-mode hides the existing-task controls
        await expect(page.locator("#detailComplete")).toBeHidden();
        await expect(page.locator("#detailDelete")).toBeHidden();
        expect(errors).toEqual([]);
    });

    test("capture bar action icons are grouped on the right (#268)", async ({ page }) => {
        // The scan 📷 used to sit LEFT of the capture bar; #268 moved it
        // to the right cluster. Assert #topUploadBtn now sits to the RIGHT
        // of the capture bar (its left edge >= the bar's right edge).
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        const barRight = await page.locator("#captureBar").evaluate(
            (el) => el.getBoundingClientRect().right);
        const scanLeft = await page.locator("#topUploadBtn").evaluate(
            (el) => el.getBoundingClientRect().left);
        expect(scanLeft).toBeGreaterThanOrEqual(barRight - 8);
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
     *
     * RCA #235 (2026-05-25): the original test used `?nosw=1` which
     * BYPASSED the Service Worker, so it never exercised the SW path
     * the user's iPhone takes by default. The SW's fetch handler
     * intercepted the cross-origin Mermaid CDN request and returned
     * a 503 from its `.catch` block on certain failure modes (or
     * served a stale cached opaque response). The user got raw
     * `flowchart LR ...` text instead of SVG. The companion test
     * below (`renders Mermaid diagrams WITH the Service Worker
     * active`) is the regression guard that closes this loop.
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

    /**
     * #235 (2026-05-25) regression guard: the user reported broken
     * Mermaid diagrams on /architecture while the per-deploy
     * "renders Mermaid diagrams" check above kept passing. Root
     * cause: the existing test used `?nosw=1` to bypass the Service
     * Worker, but the user's iPhone (and every real user) navigates
     * normally — the SW is active and intercepts the cross-origin
     * Mermaid CDN fetch. The SW's `fetch.catch` 503-fallback or
     * stale-opaque-cache combination broke the ES module import.
     *
     * This test runs the SAME page WITHOUT `?nosw=1` so the live SW
     * intercept-path is exercised end-to-end. After the v167 SW
     * skips cross-origin requests entirely (browser handles
     * natively), this should match the no-SW behavior. If the SW
     * ever regresses to intercepting CDN URLs, this test fails
     * within the same deploy-validate window the original check
     * runs in — closing the gap that let #235 ship silently.
     */
    test("architecture page renders Mermaid diagrams WITH the Service Worker active", async ({ page }) => {
        const errors = [];
        page.on("pageerror", (err) => errors.push(err.message));

        // Step 1: navigate to / first so the SW registers + activates.
        await page.goto("/");
        await page.waitForLoadState("networkidle");
        // Wait for SW to be the active controller (or skip silently if
        // the browser doesn't support SW — Playwright chromium does).
        await page.evaluate(async () => {
            if (!("serviceWorker" in navigator)) return;
            await navigator.serviceWorker.ready;
        });

        // Step 2: navigate to /architecture WITHOUT nosw=1. The SW
        // intercepts every static asset + cross-origin request.
        await page.goto("/architecture");
        await page.waitForLoadState("networkidle");

        // Same assertions as the nosw=1 test — Mermaid must render
        // through the SW path too. Without #235's SW cross-origin
        // skip, this would time out waiting for the SVG.
        await expect(
            page.locator("pre.mermaid svg").first(),
        ).toBeVisible({ timeout: 10_000 });

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
        { path: "/reflection?nosw=1", anchor: "#reflectionContainer" },  // #165
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

    test("/utilities project→goal cleanup card renders + populates from live data (#273)", async ({ page }) => {
        // Behavioral check (not a string-match): the card fetches
        // /api/projects + /api/goals, runs auditProjectGoalLinks, and
        // renders a ".pg-summary" line ("N cross-side · M unlinked").
        // Asserting that summary appears proves goal_filter_helpers.js
        // loaded on /utilities, both fetches succeeded under prod CSP
        // (the #55 dev-bypass-masks-CSP gap), and the audit ran — none
        // of which the dev-bypass Phase 6 can guarantee for prod.
        const errors = [];
        page.on("pageerror", (err) => errors.push(err.message));
        await page.goto("/utilities?nosw=1");
        await page.waitForLoadState("networkidle");
        const card = page.locator('.utility-card[data-utility="project-goal-cleanup"]');
        await expect(card).toBeVisible();
        const summary = card.locator(".pg-summary");
        await expect(summary).toBeVisible({ timeout: 10_000 });
        await expect(summary).toContainText("cross-side");
        // Refresh button is the manual re-audit affordance.
        await expect(card.locator("[data-pg-refresh]")).toBeVisible();
        expect(errors).toEqual([]);
    });

    test("/calendar renders day cells + Unscheduled side panel (#94)", async ({ page }) => {
        await page.goto("/calendar?nosw=1");
        await page.waitForLoadState("networkidle");
        // #218 (2026-05-24): 14 cells (Mon–Sun × 2 weeks). Was 12 (Mon-Sat
        // per #72) — old design hid Sunday on the calendar and orphaned
        // Sunday-dated tasks to BACKLOG. Test asserted the buggy state
        // with toBe(12), which made fixing the bug require updating
        // the test alongside the code. Now: full 7-day week ISO layout.
        await expect(page.locator(".calendar-cell").first()).toBeVisible({ timeout: 5_000 });
        const cellCount = await page.locator(".calendar-cell").count();
        expect(cellCount).toBe(14);
        await expect(page.locator("#calendarUnscheduled")).toBeVisible();
    });

    test("/calendar opens the detail panel in place, not on the board (#270)", async ({ page }) => {
        await page.goto("/calendar?nosw=1");
        await page.waitForLoadState("networkidle");
        // #270: the shared detail panel is embedded on /calendar so tasks
        // open here instead of navigating to /?task=<id>. Assert it's in
        // the DOM (hidden until opened).
        await expect(page.locator("#detailOverlay")).toHaveCount(1);

        // Empty day cells render a "click to add" placeholder; clicking it
        // opens the CREATE panel pre-dated to that day WITHOUT leaving
        // /calendar. (Targets the day-cell placeholder specifically, not the
        // Unscheduled empty-state <li>.)
        const emptyCell = page.locator(".calendar-cell .calendar-cell-empty").first();
        if (await emptyCell.count()) {
            await emptyCell.click();
            await expect(page.locator("#detailOverlay")).toBeVisible({ timeout: 5_000 });
            await expect(page.locator("#detailHeaderTitle")).toHaveText("New Task");
            expect(new URL(page.url()).pathname).toBe("/calendar");
            // The clicked cell's date seeds the due-date field.
            expect(await page.locator("#detailDueDate").inputValue())
                .toMatch(/^\d{4}-\d{2}-\d{2}$/);
            await page.locator("#detailClose").click();
            await expect(page.locator("#detailOverlay")).toBeHidden();
        }

        // If any task is listed (in a cell or the Unscheduled list), clicking
        // it opens the panel in EDIT mode in place — still no navigation.
        const taskLink = page.locator(".calendar-task-link").first();
        if (await taskLink.count()) {
            await taskLink.click();
            await expect(page.locator("#detailOverlay")).toBeVisible({ timeout: 5_000 });
            await expect(page.locator("#detailHeaderTitle")).toHaveText("Task Detail");
            expect(new URL(page.url()).pathname).toBe("/calendar");
        }
    });

    test("/calendar does not horizontally overflow at desktop 1280×800 (#138 D-B1)", async ({ page }) => {
        // Regression for #138 Phase B audit defect D-B1: long task titles
        // in day cells were pushing the 240px Unscheduled aside off-screen
        // because `.calendar-layout` used `1fr 240px` instead of
        // `minmax(0, 1fr) 240px` — the 1fr column wouldn't shrink below
        // its content min-width. Asserts no horizontal scroll appears at
        // the desktop preset.
        await page.setViewportSize({ width: 1280, height: 800 });
        await page.goto("/calendar?nosw=1");
        await page.waitForLoadState("networkidle");
        await expect(page.locator("#calendarUnscheduled")).toBeVisible();
        // Re-assert viewport in case async loads triggered any device-emulation
        // resets between goto and assertion.
        await page.setViewportSize({ width: 1280, height: 800 });
        const overflow = await page.evaluate(() => {
            const wide = [];
            for (const el of document.querySelectorAll("*")) {
                const r = el.getBoundingClientRect();
                if (r.right > 1281 && r.width > 50) {
                    wide.push({
                        tag: el.tagName,
                        cls: (el.className + "").slice(0, 50),
                        id: el.id,
                        w: Math.round(r.width),
                        right: Math.round(r.right),
                    });
                    if (wide.length >= 5) break;
                }
            }
            return {
                scrollWidth: document.documentElement.scrollWidth,
                innerWidth: window.innerWidth,
                wide,
            };
        });
        if (overflow.scrollWidth > overflow.innerWidth) {
            // Surface the offending elements in the failure message.
            throw new Error(
                `/calendar overflowed: scrollWidth=${overflow.scrollWidth} > ` +
                `innerWidth=${overflow.innerWidth}. Wide: ${JSON.stringify(overflow.wide)}`,
            );
        }
    });

    test("/ tasks board does not horizontally overflow at mobile 375×812 (#216 / #138 D-B1)", async ({ page }) => {
        // Regression for #216: same #138 D-B1 class on the home board.
        // `.tier-board` used implicit grid columns (no `grid-template-
        // columns`) at <900px, so the single mobile track sized to
        // MAX-CONTENT. `.task-card .task-quick-actions` is `flex-shrink:0`
        // and holds 5+ tier buttons (Today / Tomorrow / This Week /
        // Next Week / Backlog), pushing the tier card ~190px past the
        // 375px viewport. Fix: `grid-template-columns: minmax(0, 1fr)`
        // at the default selector + `minmax(0,1fr) minmax(0,1fr)` at
        // the `(min-width: 900px)` media query.
        await page.setViewportSize({ width: 375, height: 812 });
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        await expect(page.locator(".tier-board")).toBeVisible();
        // Re-assert viewport in case async loads reset device emulation.
        await page.setViewportSize({ width: 375, height: 812 });
        const overflow = await page.evaluate(() => {
            const wide = [];
            for (const el of document.querySelectorAll("*")) {
                const r = el.getBoundingClientRect();
                if (r.right > 376 && r.width > 50) {
                    wide.push({
                        tag: el.tagName,
                        cls: (el.className + "").slice(0, 50),
                        id: el.id,
                        w: Math.round(r.width),
                        right: Math.round(r.right),
                    });
                    if (wide.length >= 5) break;
                }
            }
            return {
                scrollWidth: document.documentElement.scrollWidth,
                innerWidth: window.innerWidth,
                wide,
            };
        });
        if (overflow.scrollWidth > overflow.innerWidth) {
            throw new Error(
                `/ board overflowed at mobile: scrollWidth=` +
                `${overflow.scrollWidth} > innerWidth=` +
                `${overflow.innerWidth}. Wide: ${JSON.stringify(overflow.wide)}`,
            );
        }
    });

    test("touch targets meet 44px floor at mobile 375×812 (#140)", async ({ page }) => {
        // Regression for #140: nav-tab + per-card tier-action buttons +
        // project-filter chips were 31px / 36px tall on mobile, below the
        // Apple HIG / Material Design 44px touch-target floor. Bumped via
        // mobile-only @media (max-width:700px) min-height bumps in
        // static/style.css. This test asserts the live computed heights.
        await page.setViewportSize({ width: 375, height: 812 });
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        await expect(page.locator(".nav-tab").first()).toBeVisible();
        await expect(page.locator(".task-card").first()).toBeVisible();
        const heights = await page.evaluate(() => {
            const h = (sel) => {
                const e = document.querySelector(sel);
                return e ? Math.round(e.getBoundingClientRect().height) : null;
            };
            return {
                navTab: h(".nav-tab"),
                quickBtn: h(".task-quick-actions button"),
                projFilter: h("#projectFilterBar button"),
            };
        });
        expect(heights.navTab).toBeGreaterThanOrEqual(44);
        expect(heights.quickBtn).toBeGreaterThanOrEqual(44);
        expect(heights.projFilter).toBeGreaterThanOrEqual(44);
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
        // and routed recovery through _hardRecover() which unregisters
        // the SW first.
        //
        // #191 (PR 11, 2026-05-22): the recovery wiring moved OUT of
        // app.js — app.js used to carry a verbatim copy of apiFetch, it
        // now aliases the single shared window.apiFetch from
        // api_client.js. So the recovery tokens are asserted against
        // api_client.js (where the logic lives) and app.js is checked
        // to confirm it no longer carries a duplicate. Real behavioural
        // coverage is the Jest suite api_client.test.js.
        const apiClient = await page.request.get("/static/api_client.js");
        expect(apiClient.status()).toBe(200);
        const clientText = await apiClient.text();
        // recovery path uses _hardRecover (SW-unregister-then-reload)
        expect(clientText).toContain("_hardRecover");
        // auto-retry-once flag still present
        expect(clientText).toContain("_retried");
        // PR49 invariant: the opaqueredirect prompt stays removed.
        expect(clientText).not.toContain('redirect: "manual"');
        // #191: app.js must NOT carry its own copy anymore.
        const appJs = await page.request.get("/static/app.js");
        const appText = await appJs.text();
        expect(appText).toContain("const apiFetch = window.apiFetch");
        expect(appText).not.toMatch(/function\s+_hardRecover\b/);
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

    test("detail panel: voice button on subtask + parent picker (#120)", async ({ page }) => {
        // Wiring check — both inputs have a sibling .voice-btn pointing
        // at the right target id.
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        const result = await page.evaluate(() => {
            const targets = ["subtaskInput", "parentPickerInput", "detailCancellationReason"];
            return targets.map((id) => {
                const target = document.getElementById(id);
                const btn = document.querySelector(`.voice-btn[data-voice-target="${id}"]`);
                return { id, targetExists: !!target, btnExists: !!btn };
            });
        });
        for (const r of result) {
            expect(r.targetExists, `${r.id} not in DOM`).toBe(true);
            expect(r.btnExists, `voice button for ${r.id} not in DOM`).toBe(true);
        }
    });

    test("detail panel: dynamically-added checklist row gets a voice button (#120)", async ({ page }) => {
        // Behavioral: call taskDetailAddChecklistRow + assert the new
        // row contains a .voice-btn that wired up cleanly.
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        const result = await page.evaluate(() => {
            const before = document.querySelectorAll("#checklistItems .checklist-item").length;
            taskDetailAddChecklistRow("test item", false);
            const rows = document.querySelectorAll("#checklistItems .checklist-item");
            const newRow = rows[rows.length - 1];
            return {
                rowsBefore: before,
                rowsAfter: rows.length,
                newRowHasVoiceBtn: !!newRow.querySelector(".voice-btn"),
                newRowHasInput: !!newRow.querySelector('input[type="text"]'),
            };
        });
        expect(result.rowsAfter).toBe(result.rowsBefore + 1);
        expect(result.newRowHasInput).toBe(true);
        expect(result.newRowHasVoiceBtn).toBe(true);
    });

    test("detail panel: voice button wired to text fields (#116)", async ({ page }) => {
        // Per PR50 anti-pattern #3: behavioral. Load home, find voice
        // buttons in the detail panel markup, assert they exist + each
        // has data-voice-target pointing at a real element.
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        const result = await page.evaluate(() => {
            const buttons = Array.from(document.querySelectorAll(".voice-btn[data-voice-target]"));
            return buttons.map((b) => {
                const targetId = b.dataset.voiceTarget;
                const target = document.getElementById(targetId);
                return {
                    targetId,
                    targetExists: !!target,
                    targetTag: target ? target.tagName.toLowerCase() : null,
                };
            });
        });
        expect(result.length).toBeGreaterThanOrEqual(2);  // at minimum: title + notes
        // Every button's data-voice-target must point at a real INPUT/TEXTAREA.
        for (const b of result) {
            expect(b.targetExists, `voice-btn target #${b.targetId} not found`).toBe(true);
            expect(["input", "textarea"]).toContain(b.targetTag);
        }
        // voice_input.js itself is served + 200.
        const r = await page.request.get("/static/voice_input.js");
        expect(r.status()).toBe(200);
    });

    test("detail panel: project picker has the cascade handler wired (#117)", async ({ page }) => {
        // PR56: the prior version tried to inject `window.allProjects = [...]`
        // but app.js's allProjects is a closure-scoped `let`, not a window
        // property — the function couldn't see the injection and the test
        // failed. Real logic test now lives in the Jest unit
        // (filter_helpers.test.js > projectCascadeGoalId). This prod-smoke
        // just confirms the wiring: the <select> has the onchange handler
        // pointing at taskDetailProjectChanged, and the function is
        // defined globally so the inline onchange resolves.
        await page.goto("/?nosw=1");
        await page.waitForLoadState("networkidle");
        const result = await page.evaluate(() => {
            const sel = document.getElementById("detailProject");
            if (!sel) return { error: "no #detailProject" };
            return {
                hasOnchange: !!sel.getAttribute("onchange"),
                onchangeRefersToHandler: (sel.getAttribute("onchange") || "")
                    .includes("taskDetailProjectChanged"),
                handlerExists: typeof window.taskDetailProjectChanged === "function",
            };
        });
        expect(result.hasOnchange).toBe(true);
        expect(result.onchangeRefersToHandler).toBe(true);
        expect(result.handlerExists).toBe(true);
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

    test("/reflection input mode tabs toggle + helpers load (#165)", async ({ page }) => {
        const errors = [];
        page.on("pageerror", (err) => errors.push(err.message));
        await page.goto("/reflection?nosw=1");
        await page.waitForLoadState("networkidle");
        // Pure-logic helper module loaded (anti-pattern #3 contract).
        const helperType = await page.evaluate(
            () => typeof window.reflectionHelpers
        );
        expect(helperType).toBe("object");
        // Typed sub-state is the default; clicking Record toggles it.
        await expect(page.locator("#reflTyped")).toBeVisible();
        await page.locator("#reflTabVoice").click();
        await expect(page.locator("#reflVoice")).toBeVisible();
        await expect(page.locator("#reflTyped")).toBeHidden();
        await page.locator("#reflTabType").click();
        await expect(page.locator("#reflText")).toBeVisible();
        // Nav tab is wired on every page.
        await expect(
            page.locator('.nav-tab[href*="reflection"]')
        ).toHaveCount(1);
        expect(errors).toEqual([]);
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
