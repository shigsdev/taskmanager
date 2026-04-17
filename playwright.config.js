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
