/**
 * #385: the local Playwright projects reach the dev-bypass server at
 * 127.0.0.1, never `localhost`.
 *
 * The bypass server listens on IPv4 only. Chromium on Windows tries ::1
 * first for `localhost` and falls back after ~300 ms on every new
 * connection — ~28 connections per page load — which made each test ~2x
 * slower (29 pages.spec.js tests: 2.2 min via localhost, 1.0 min via
 * 127.0.0.1). This guards against a well-meaning revert.
 */
const config = require("../../../playwright.config.js");

const LOCAL_PROJECTS = ["chromium", "chromium-sw", "chromium-mobile"];

function project(name) {
    const p = config.projects.find((x) => x.name === name);
    if (!p) throw new Error(`no Playwright project named ${name}`);
    return p;
}

describe("playwright.config.js base URLs (#385)", () => {
    test.each(LOCAL_PROJECTS)("%s targets 127.0.0.1:5111", (name) => {
        const url = new URL(project(name).use.baseURL);
        expect(url.hostname).toBe("127.0.0.1");
        expect(url.port).toBe("5111");
    });

    test("the prod project still targets the deployed URL", () => {
        const url = new URL(project("chromium-prod").use.baseURL);
        expect(url.hostname).not.toBe("127.0.0.1");
        expect(url.hostname).not.toBe("localhost");
        expect(url.protocol).toBe("https:");
    });
});
