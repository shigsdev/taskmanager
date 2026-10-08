/**
 * #385: the local Playwright projects reach the dev-bypass server at
 * 127.0.0.1, never `localhost`.
 *
 * The bypass server listens on IPv4 only. Chromium on Windows tries ::1
 * first for `localhost` and falls back after ~300 ms on every new
 * connection — ~28 connections per page load — which made each test ~2x
 * slower (29 pages.spec.js tests: 2.2 min via localhost, 1.0 min via
 * 127.0.0.1). This guards against a well-meaning revert.
 *
 * #394: desktop and mobile run side by side ONLY when run_all_gates.sh
 * provides a second local server (PW_WORKERS + PW_MOBILE_BASE_URL). With no
 * env — e.g. a manual `npx playwright test` — the config stays serial on
 * one server, exactly as before. Each local project is capped at one
 * worker, so tests within a project never overlap on one database.
 */
const CONFIG_PATH = "../../../playwright.config.js";
const LOCAL_PROJECTS = ["chromium", "chromium-sw", "chromium-mobile"];
const ENV_KEYS = ["PW_WORKERS", "PW_MOBILE_BASE_URL"];

function loadConfig(env = {}) {
    const saved = {};
    for (const k of ENV_KEYS) { saved[k] = process.env[k]; delete process.env[k]; }
    Object.assign(process.env, env);
    let config;
    try {
        jest.isolateModules(() => {
            // Playwright throws if @playwright/test is required twice, and
            // each isolated load would do that. The config only uses
            // defineConfig, which is an identity function.
            jest.doMock("@playwright/test", () => ({ defineConfig: (c) => c }));
            config = require(CONFIG_PATH);
        });
    } finally {
        for (const k of ENV_KEYS) {
            if (saved[k] === undefined) delete process.env[k];
            else process.env[k] = saved[k];
        }
    }
    return config;
}

function project(config, name) {
    const p = config.projects.find((x) => x.name === name);
    if (!p) throw new Error(`no Playwright project named ${name}`);
    return p;
}

describe("playwright.config.js base URLs (#385)", () => {
    const config = loadConfig();

    test.each(LOCAL_PROJECTS)("%s targets 127.0.0.1:5111 by default", (name) => {
        const url = new URL(project(config, name).use.baseURL);
        expect(url.hostname).toBe("127.0.0.1");
        expect(url.port).toBe("5111");
    });

    test("the prod project still targets the deployed URL", () => {
        const url = new URL(project(config, "chromium-prod").use.baseURL);
        expect(url.hostname).not.toBe("127.0.0.1");
        expect(url.hostname).not.toBe("localhost");
        expect(url.protocol).toBe("https:");
    });
});

describe("playwright.config.js workers (#394)", () => {
    test("with no env it stays serial on one server", () => {
        const config = loadConfig();
        expect(config.workers).toBe(1);
        expect(new URL(project(config, "chromium-mobile").use.baseURL).port).toBe("5111");
    });

    test("the gate script's env runs mobile on its own server, 2 workers", () => {
        const config = loadConfig({
            PW_WORKERS: "2",
            PW_MOBILE_BASE_URL: "http://127.0.0.1:5112",
        });
        expect(config.workers).toBe(2);
        const mobile = new URL(project(config, "chromium-mobile").use.baseURL);
        expect(mobile.hostname).toBe("127.0.0.1");
        expect(mobile.port).toBe("5112");
        // Desktop + SW stay on server A.
        for (const name of ["chromium", "chromium-sw"]) {
            expect(new URL(project(config, name).use.baseURL).port).toBe("5111");
        }
    });

    test.each(LOCAL_PROJECTS)("%s is capped at one worker", (name) => {
        const config = loadConfig({ PW_WORKERS: "2" });
        expect(project(config, name).workers).toBe(1);
    });
});
