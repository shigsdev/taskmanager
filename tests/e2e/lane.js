/**
 * #402: `test` / `expect` for the local e2e suites, with `baseURL` pointed at
 * this worker's own lane server (see tests/lane_base_url.js). Specs import
 * from here instead of "@playwright/test"; everything else is unchanged.
 */
const base = require("@playwright/test");
const { laneBaseURL } = require("../lane_base_url");

const test = base.test.extend({
    baseURL: async ({ baseURL }, use, testInfo) => {
        await use(laneBaseURL(baseURL, testInfo.parallelIndex,
                              process.env.PW_LANE_BASE_PORT));
    },
});

module.exports = { test, expect: base.expect };
