/**
 * Playwright E2E test config.
 *
 * Tests run against the local bypass server (taskmanager-dev-bypass on
 * port 5111). The server must be started manually BEFORE running tests:
 *
 *   cp .env.dev-bypass.example .env.dev-bypass
 *   python scripts/run_dev_bypass.py
 *
 * Then:  npx playwright test
 */
// @ts-check
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
    testDir: "./tests/e2e",
    timeout: 30000,
    retries: 0,
    workers: 1, // sequential — single Flask server
    reporter: [["list"]],

    use: {
        baseURL: "http://localhost:5111",
        headless: true,
        // Disable SW in E2E tests to avoid cached-page issues, UNLESS
        // the test explicitly navigates without ?nosw=1
        actionTimeout: 10000,
    },

    projects: [
        {
            name: "chromium",
            use: { browserName: "chromium" },
        },
    ],
});
