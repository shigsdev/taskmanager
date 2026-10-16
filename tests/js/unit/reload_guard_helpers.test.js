/**
 * Jest tests for #473 — the reload guard the review screens publish to.
 *
 * base.html applies a new service worker (which reloads the page) unless
 * userIsBusy() objects. /scan, /import, /plan and /reflection show their
 * review as part of the page, not a panel, so they register a check here;
 * a paid request in flight is marked with during().
 */
const { createReloadGuard } = require("../../../static/reload_guard_helpers.js");

describe("createReloadGuard (#473)", () => {
    test("a fresh guard is not busy (the quiet case)", () => {
        expect(createReloadGuard().busy()).toBe(false);
    });

    test("busy while a registered check says so, and not after", () => {
        const g = createReloadGuard();
        let showing = true;
        g.add(() => showing);
        expect(g.busy()).toBe(true);
        showing = false;
        expect(g.busy()).toBe(false);
    });

    test("any one check is enough", () => {
        const g = createReloadGuard();
        g.add(() => false);
        g.add(() => true);
        expect(g.busy()).toBe(true);
    });

    test("a check that throws is skipped, never blocks", () => {
        const g = createReloadGuard();
        g.add(() => { throw new Error("gone"); });
        expect(g.busy()).toBe(false);
    });

    test("add ignores something that isn't a function", () => {
        const g = createReloadGuard();
        g.add(null);
        g.add("yes");
        expect(g.busy()).toBe(false);
    });

    test("busy while a request is in flight, idle once it answers", async () => {
        const g = createReloadGuard();
        let answer;
        const p = g.during(new Promise((r) => { answer = r; }));
        expect(g.busy()).toBe(true);
        answer({ ok: 1 });
        await expect(p).resolves.toEqual({ ok: 1 });
        expect(g.busy()).toBe(false);
    });

    test("a failed request also ends the busy spell, and still fails", async () => {
        const g = createReloadGuard();
        let fail;
        const p = g.during(new Promise((_, r) => { fail = r; }));
        expect(g.busy()).toBe(true);
        fail(new Error("500"));
        await expect(p).rejects.toThrow("500");
        expect(g.busy()).toBe(false);
    });

    test("two requests: busy until both have answered", async () => {
        const g = createReloadGuard();
        let a, b;
        const pa = g.during(new Promise((r) => { a = r; }));
        const pb = g.during(new Promise((r) => { b = r; }));
        a(1);
        await pa;
        expect(g.busy()).toBe(true);
        b(2);
        await pb;
        expect(g.busy()).toBe(false);
    });

    test("during passes a plain value straight through", async () => {
        const g = createReloadGuard();
        await expect(g.during(7)).resolves.toBe(7);
        expect(g.busy()).toBe(false);
    });
});
