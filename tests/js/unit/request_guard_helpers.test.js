/**
 * Jest tests for #418 — the request guard that keeps a closed ✨ Plan's
 * answer out of the next one.
 *
 * The board's ✨ Plan review is one shared dialog. Close it while the
 * planner is still working and open another, and the first answer used to
 * land in the second. The guard hands out a token per request; only the
 * newest one, and only while the dialog is open, may write.
 */
const { createRequestGuard } = require("../../../static/request_guard_helpers.js");

describe("createRequestGuard (#418)", () => {
    test("nothing is current before the first request", () => {
        const g = createRequestGuard();
        expect(g.isCurrent(0)).toBe(false);
        expect(g.isCurrent(1)).toBe(false);
    });

    test("a request's token is current until something replaces it", () => {
        const g = createRequestGuard();
        const a = g.begin();
        expect(g.isCurrent(a)).toBe(true);
    });

    test("a newer request supersedes the older one", () => {
        const g = createRequestGuard();
        const a = g.begin();
        const b = g.begin();
        expect(a).not.toBe(b);
        expect(g.isCurrent(a)).toBe(false);
        expect(g.isCurrent(b)).toBe(true);
    });

    test("cancel (closing the dialog) drops whatever is in flight", () => {
        const g = createRequestGuard();
        const a = g.begin();
        g.cancel();
        expect(g.isCurrent(a)).toBe(false);
    });

    test("close, reopen: only the reopened request may write", () => {
        const g = createRequestGuard();
        const a = g.begin();
        g.cancel();
        const b = g.begin();
        expect(g.isCurrent(a)).toBe(false);
        expect(g.isCurrent(b)).toBe(true);
        // A token handed out before a cancel never comes back to life.
        expect(b).not.toBe(a);
    });

    test("two guards don't share tokens", () => {
        const g1 = createRequestGuard();
        const g2 = createRequestGuard();
        const a = g1.begin();
        g2.begin();
        g2.cancel();
        expect(g1.isCurrent(a)).toBe(true);
    });

    test("the race this fixes: the older answer arriving last is dropped", async () => {
        const g = createRequestGuard();
        const shown = [];
        let releaseA;
        const answerA = new Promise((r) => { releaseA = r; });
        const answerB = Promise.resolve("B");
        async function run(answer) {
            const mine = g.begin();
            const v = await answer;
            if (g.isCurrent(mine)) shown.push(v);
        }
        const pa = run(answerA);
        g.cancel();                       // user closes A
        const pb = run(answerB);          // and opens B
        await pb;
        releaseA("A");                    // A's answer arrives last
        await pa;
        expect(shown).toEqual(["B"]);
    });
});
