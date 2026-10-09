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
 * #402 (replaces #394's "mobile on server B"): the gates run N workers,
 * each on its own lane server (tests/e2e/lane.js maps parallelIndex to a
 * port), so desktop and mobile spread across workers (fullyParallel) without
 * ever sharing a database. With no env — a manual `npx playwright test` — it
 * stays one worker on one server, exactly as before. The SW project stays
 * capped at one worker.
 */
const CONFIG_PATH = "../../../playwright.config.js";
const LOCAL_PROJECTS = ["chromium", "chromium-sw", "chromium-mobile"];
const ENV_KEYS = ["PW_WORKERS", "PW_MOBILE_BASE_URL", "PW_LANE_BASE_PORT"];

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

describe("playwright.config.js workers (#402 lanes)", () => {
    test("with no env it stays one worker on one server", () => {
        const config = loadConfig();
        expect(config.workers).toBe(1);
        for (const name of LOCAL_PROJECTS) {
            expect(new URL(project(config, name).use.baseURL).port).toBe("5111");
        }
    });

    test("the gate's PW_WORKERS sets the total worker count", () => {
        expect(loadConfig({ PW_WORKERS: "6" }).workers).toBe(6);
    });

    test.each(["chromium", "chromium-mobile"])(
        "%s is spread across lanes: fully parallel, no per-project cap", (name) => {
            const p = project(loadConfig({ PW_WORKERS: "6" }), name);
            expect(p.fullyParallel).toBe(true);
            expect(p.workers).toBeUndefined();
        });

    test("the SW project stays on one worker", () => {
        expect(project(loadConfig({ PW_WORKERS: "6" }), "chromium-sw").workers).toBe(1);
    });

    test("server B is retired: mobile ignores PW_MOBILE_BASE_URL (lanes pick the port)", () => {
        const config = loadConfig({ PW_WORKERS: "2", PW_MOBILE_BASE_URL: "http://127.0.0.1:5112" });
        expect(new URL(project(config, "chromium-mobile").use.baseURL).port).toBe("5111");
    });
});
