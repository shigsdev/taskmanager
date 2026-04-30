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

const PROD_BASE_URL =
    process.env.TASKMANAGER_PROD_URL ||
    "https://web-production-3e3ae.up.railway.app";

module.exports = defineConfig({
    timeout: 30000,
    retries: 0,
    workers: 1, // sequential
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
            use: {
                baseURL: "http://localhost:5111",
                headless: true,
                browserName: "chromium",
                actionTimeout: 10000,
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
            // PR40 #106: cold SW install + addAll (13 files) on Windows
            // with Defender on can take 30s+. Bump the per-test budget.
            timeout: 90_000,
            use: {
                baseURL: "http://localhost:5111",
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
