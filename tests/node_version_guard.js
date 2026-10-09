/**
 * #348: which Node versions must not run the local Playwright suite.
 *
 * The libuv bundled with Node 24.x before 24.16.0 (and 25.x, 26.0.x) has a
 * Windows-only bug: a loopback TCP connect writes 8 bytes past a stack buffer,
 * over the /GS cookie, and the process fail-fasts with 0xC0000409
 * (libuv/libuv#5274). Every Playwright `request.*` to localhost takes that
 * path, so workers died ~6 minutes into a gate run on a random test, reported
 * as "worker process exited unexpectedly (code=3221226505)". Caught in a dump
 * on 2026-10-08 (docs/design/348-playwright-worker-crash.md). Fixed in Node
 * 24.16.0+ and 26.1.0+.
 *
 * 22.x is said to lack the fix but there is no evidence it has the bug, so it
 * is not refused. Unparseable versions are allowed rather than blocking every
 * run on a format surprise.
 */

/**
 * @param {string} version  e.g. "24.15.0" or process.version ("v24.15.0")
 * @param {string} platform e.g. process.platform
 * @returns {string|null} why this Node is refused, or null when it is fine
 */
function nodeLoopbackBugReason(version, platform) {
    if (platform !== "win32") return null;
    const m = String(version).match(/^v?(\d+)\.(\d+)\.(\d+)/);
    if (!m) return null;
    const major = Number(m[1]);
    const minor = Number(m[2]);
    const affected =
        (major === 24 && minor < 16) || major === 25 || (major === 26 && minor < 1);
    if (!affected) return null;
    return `Node ${m[1]}.${m[2]}.${m[3]} on Windows has the libuv loopback-connect `
        + "stack-cookie bug (libuv#5274) that kills Playwright workers with "
        + "0xC0000409 (#348). Upgrade to Node 24.16+ or 26.1+: "
        + "winget upgrade OpenJS.NodeJS.LTS";
}

module.exports = { nodeLoopbackBugReason };
