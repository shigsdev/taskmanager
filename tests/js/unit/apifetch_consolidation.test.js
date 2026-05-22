/**
 * #191 / #192 (PR 11) — apiFetch consolidation drift guard.
 *
 * static/api_client.js is the ONE shared apiFetch (stale-tab retry +
 * recovery prompt + 401 handling — the #112/#113/#115 fixes). app.js
 * and review.js used to carry their own verbatim copies; two copies
 * inevitably drift when a fix lands in one and not the other.
 *
 * These are STRUCTURAL drift assertions, not behaviour tests — you
 * cannot behaviourally test "there is no second definition". They
 * fail loudly if a future edit re-introduces a local apiFetch. The
 * real behaviour of apiFetch is covered by api_client.test.js.
 */
const fs = require("fs");
const path = require("path");

function readStatic(name) {
    return fs.readFileSync(
        path.join(__dirname, "../../../static", name), "utf-8",
    );
}

describe("#191 — app.js has no local apiFetch / recovery helpers", () => {
    const src = readStatic("app.js");

    test("app.js does not DEFINE its own apiFetch", () => {
        // A local definition would be `function apiFetch` or
        // `async function apiFetch` or `apiFetch = function`/`= async`.
        expect(src).not.toMatch(/\basync\s+function\s+apiFetch\b/);
        expect(src).not.toMatch(/\bfunction\s+apiFetch\b/);
        expect(src).not.toMatch(/\bapiFetch\s*=\s*(async\s*)?\(/);
    });

    test("app.js does not DEFINE _hardRecover / _maybePromptRecovery", () => {
        // Those live in api_client.js now — app.js must not re-declare them.
        expect(src).not.toMatch(/function\s+_hardRecover\b/);
        expect(src).not.toMatch(/function\s+_maybePromptRecovery\b/);
    });

    test("app.js aliases the shared window.apiFetch", () => {
        expect(src).toMatch(/const\s+apiFetch\s*=\s*window\.apiFetch/);
    });
});

describe("#192 — review.js uses the shared apiFetch", () => {
    const src = readStatic("review.js");

    test("review.js does not DEFINE its own apiFetch", () => {
        expect(src).not.toMatch(/\basync\s+function\s+apiFetch\b/);
        expect(src).not.toMatch(/\bfunction\s+apiFetch\b/);
    });

    test("review.js aliases the shared window.apiFetch", () => {
        expect(src).toMatch(/const\s+apiFetch\s*=\s*window\.apiFetch/);
    });
});

describe("#192 — projects.js has no raw fetch( bypassing apiFetch", () => {
    const src = readStatic("projects.js");

    test("projects.js makes no bare fetch() call", () => {
        // Every network call in projects.js must route through apiFetch
        // (inherited from app.js's global). A bare `fetch(` (not
        // `apiFetch(`, not `.fetch(`) bypasses the shared retry/recovery
        // wrapper — the #192 reorder bug. Strip `//` line comments
        // first so prose mentioning "fetch()" doesn't false-positive.
        const code = src.replace(/\/\/.*$/gm, "");
        const bareFetch = code.match(/(?<![.A-Za-z])fetch\s*\(/g) || [];
        expect(bareFetch).toEqual([]);
    });
});
