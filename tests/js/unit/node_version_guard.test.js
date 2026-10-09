/**
 * #348: refuse a Node whose bundled libuv has the Windows loopback-connect
 * stack-cookie bug (libuv/libuv#5274). It killed Playwright workers with
 * 0xC0000409 mid-run. Fixed in Node 24.16.0+ and 26.1.0+.
 */
const { nodeLoopbackBugReason } = require("../../node_version_guard");

describe("nodeLoopbackBugReason (#348)", () => {
    test.each(["24.15.0", "24.0.0", "25.2.1", "26.0.3", "v24.15.0"])(
        "%s on Windows is refused, naming the version", (version) => {
            const reason = nodeLoopbackBugReason(version, "win32");
            expect(reason).toEqual(expect.stringContaining(version.replace(/^v/, "")));
        });

    test.each(["24.16.0", "24.20.0", "v24.21.0", "26.1.0", "26.11.1", "22.12.0", "20.18.0"])(
        "%s on Windows is allowed", (version) => {
            expect(nodeLoopbackBugReason(version, "win32")).toBeNull();
        });

    test.each(["linux", "darwin"])(
        "24.15.0 on %s is allowed — the bug is Windows-only", (platform) => {
            expect(nodeLoopbackBugReason("24.15.0", platform)).toBeNull();
        });

    test("an unparseable version is allowed rather than blocking every run", () => {
        expect(nodeLoopbackBugReason("not-a-version", "win32")).toBeNull();
    });
});
