/**
 * #402: which local server a Playwright worker talks to.
 *
 * The gates start N throwaway dev-bypass servers on consecutive ports, each on
 * its own copy of the dev DB, and export PW_LANE_BASE_PORT (the first port).
 * Worker `parallelIndex` i — unique among the workers running at once — uses
 * port base + i, so two concurrent workers never share a server or a DB.
 * Spec: docs/design/402-parallel-playwright-lanes.md.
 *
 * Only a local http://127.0.0.1: URL is rewritten, and only when the lane env
 * is set: prod smoke and a plain `npx playwright test` are untouched.
 */

/**
 * @param {string|undefined} baseURL   the project's configured baseURL
 * @param {number} parallelIndex       testInfo.parallelIndex
 * @param {string|number|undefined} lanePort  PW_LANE_BASE_PORT
 * @returns {string|undefined}
 */
function laneBaseURL(baseURL, parallelIndex, lanePort) {
    const base = Number(lanePort);
    if (!baseURL || !lanePort || !Number.isInteger(base)) return baseURL;
    if (!baseURL.startsWith("http://127.0.0.1:")) return baseURL;
    return `http://127.0.0.1:${base + parallelIndex}`;
}

module.exports = { laneBaseURL };
