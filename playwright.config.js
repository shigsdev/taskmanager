/**
 * Playwright E2E test config.
 *
 * Two projects:
 *
 *   "chromium"       — local E2E against the bypass server on port 5111
 *                      (tests in tests/e2e/). This is the default target
 *                      and runs as part of the standard quality gates.
 *
 *   "chromium-prod"  — post-deploy smoke tests against the deployed
 *                      Railway URL (tests in tests/e2e-prod/). Requires
 *                      TASKMANAGER_SESSION_COOKIE env var set to a valid
 *                      Flask session cookie. Run with:
 *                        npm run test:e2e:prod
 *                      See README for cookie setup.
 *
 * Local setup:
 *   cp .env.dev-bypass.example .env.dev-bypass
 *   python scripts/run_dev_bypass.py
 *   npx playwright test --project=chromium
 */
// @ts-check
const { defineConfig } = require("@playwright/test");

// #331: headless Chromium needs an explicit fake capture device to
// run MediaRecorder, and the auto-accept flag to skip the mic
// permission prompt no test can click.
const FAKE_MEDIA_ARGS = [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
];

// #385: the local projects reach the dev-bypass server at 127.0.0.1, NOT
// `localhost`. The server listens on IPv4 only; Chromium on Windows tries
// ::1 first for `localhost` and falls back after ~300 ms on EVERY new
// connection (~28 per page load). Measured 2026-10-07: page load 1552 ->
// 294 ms, 29 pages.spec.js tests 2.2 -> 1.0 min. Don't "tidy" this back —
// tests/js/unit/playwright_config.test.js guards it.
const LOCAL_BASE_URL = "http://127.0.0.1:5111";

// #394: run_all_gates.sh runs desktop and mobile SIDE BY SIDE, each on its
// own throwaway LOCAL server (mobile on :5112 with a copy of the dev DB) —
// nothing on Railway. It opts in by exporting PW_WORKERS=2 and
// PW_MOBILE_BASE_URL. Without them (a manual `npx playwright test`) this
// stays serial on one server, exactly as before. Each local project is
// capped at one worker, so tests within a project never overlap on one DB.
// Probe 2026-10-07: 17.1 -> ~9.3 min. PLAYWRIGHT_WORKERS=1 on the gate
// script turns it off when RAM is tight.
const LOCAL_WORKERS = Number(process.env.PW_WORKERS || 1);
const MOBILE_BASE_URL = process.env.PW_MOBILE_BASE_URL || LOCAL_BASE_URL;

const PROD_BASE_URL =
    process.env.TASKMANAGER_PROD_URL ||
    "https://web-production-3e3ae.up.railway.app";

module.exports = defineConfig({
    timeout: 30000,
    retries: 0,
    workers: LOCAL_WORKERS, // #394 — 1 unless the gate script provides server B
    reporter: [["list"]],

    // Workaround for Playwright apiRequestContext hanging on macOS when
    // the host has no IPv6 routing. macOS's resolver synthesizes
    // IPv4-mapped IPv6 addresses (`::ffff:1.2.3.4`) when asked for AAAA
    // records — even when the upstream domain has no real AAAA record
    // and the network can't route IPv6 anywhere. Playwright's Happy
    // Eyeballs implementation (node_modules/playwright-core/lib/server/
    // utils/happyEyeballs.js) interleaves v6 results before v4 results,
    // tries the synthesized v6 address first, and hangs to the action
    // timeout. Symptom: any `page.request.get(...)` or `request.get(...)`
    // call against a Railway / Fastly / Cloudflare URL times out at 15s
    // even though `curl` and plain Node `https.get` to the same URL
    // return in <1s.
    //
    // Fix: monkey-patch `dns.promises.lookup` BEFORE Playwright loads
    // its happy-eyeballs agent, so the v6-family lookups return empty
    // arrays instead of mapped addresses. Plain v4 lookups are
    // untouched, so production browser navigation still works normally.
    globalSetup: "./tests/playwright-globalSetup.js",

    projects: [
        {
            name: "chromium",
            testDir: "./tests/e2e",
            workers: 1, // #394: serial within the project
            use: {
                baseURL: LOCAL_BASE_URL,
                headless: true,
                browserName: "chromium",
                actionTimeout: 10000,
                // #331: a fake mic + auto-accepted permission prompt so
                // the recording path can actually be driven in a test.
                // The bug that made this necessary (a service-worker
                // auto-reload killing a live recording) is unprovable
                // without a real MediaRecorder running. No effect on
                // tests that never call getUserMedia.
                launchOptions: { args: FAKE_MEDIA_ARGS },
            },
        },
        {
            // PR39 (audit E2) + PR40 (#106): SW-active suite. Every test
            // in tests/e2e/ uses ?nosw=1 to dodge SW reload loops. That
            // left the entire service-worker code path only smoked on
            // prod via the 22-test suite. A bug in sw.js that breaks
            // startup would pass every local gate. This project runs
            // WITHOUT ?nosw=1.
            name: "chromium-sw",
            testDir: "./tests/e2e-sw",
            workers: 1, // #394: serial within the project; shares server A

            // PR40 #106: cold SW install + addAll (13 files) on Windows
            // with Defender on can take 30s+. Bump the per-test budget.
            timeout: 90_000,
            use: {
                baseURL: LOCAL_BASE_URL,
                headless: true,
                browserName: "chromium",
                actionTimeout: 30_000,  // SW install + first paint takes longer
                // PR40 #106 — explicit SW allow on the context. Default IS
                // 'allow' but being explicit makes the intent obvious to
                // future readers + future Playwright defaults.
                serviceWorkers: "allow",
            },
        },
        {
            // #141 — re-run the local e2e suite at mobile viewport
            // (375×812) to mechanically catch viewport-specific bugs
            // (overflow, off-screen elements, missing affordances) at
            // gate time. Same testDir as `chromium`; only the viewport
            // differs. Per-spec mobile-only opt-outs use the
            // `test.skip(viewport.width < 700, "desktop-only")` idiom.
            //
            // #274 (2026-05-31): skip describe blocks tagged `@noviewport`
            // here. The mobile re-run exists to catch LAYOUT regressions;
            // tests that assert pure DB/JS state through programmatic
            // interaction (DataTransfer drags, page.evaluate races, SW
            // lifecycle) or only console-error-free page loads gain nothing
            // from a second viewport — `ui_audit.spec.js` already audits
            // EVERY route for console errors + horizontal overflow + the
            // 44px touch-target floor at 375px, which is the real mobile
            // safety net. Opt-OUT model (default still runs at mobile) so a
            // new test is covered by default; only certified
            // viewport-independent groups carry the tag. Cut the mobile run
            // ~4.2m → ~1.9m. Real-interaction tests (capture bar, filter
            // chips, detail-panel clicks) stay — they exercise 375px
            // reachability.
            name: "chromium-mobile",
            testDir: "./tests/e2e",
            grepInvert: /@noviewport/,
            workers: 1, // #394: serial within the project
            use: {
                baseURL: MOBILE_BASE_URL, // #394: server B when the gates run

                headless: true,
                browserName: "chromium",
                actionTimeout: 10000,
                viewport: { width: 375, height: 812 },
                launchOptions: { args: FAKE_MEDIA_ARGS },  // #331
            },
        },
        {
            name: "chromium-prod",
            testDir: "./tests/e2e-prod",
            // Prod smoke tests MUST be run explicitly, never as part of the
            // default test run. They hit a live server and need a cookie.
            testIgnore: process.env.TASKMANAGER_SESSION_COOKIE
                ? undefined
                : /.*/,
            use: {
                baseURL: PROD_BASE_URL,
                headless: true,
                browserName: "chromium",
                actionTimeout: 15000, // prod has real network latency
                // Retain HAR + trace for prod runs so failures are debuggable
                // even when we can't reproduce locally.
                trace: "retain-on-failure",
            },
        },
    ],
});
