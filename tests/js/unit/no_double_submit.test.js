/**
 * #429: duplicates from the network retry and from double taps.
 *
 * apiFetch retried ANY request once after a network TypeError. When the
 * server had already committed and only the response was lost (a phone
 * switching networks), a POST ran twice — a duplicate task or import, a
 * second paid analysis — and a retried restore / undo / confirm came back
 * 409 "failed" for something that worked. Only GET and HEAD are retried now.
 *
 * withInflight(el, fn) runs fn at most once at a time per element; a second
 * click / tap / Enter while the first is still running is ignored.
 */
"use strict";

const apiClient = require("../../../static/api_client");
const { apiFetch, withInflight, inflightSubmit, _resetRecoveryFlag } = apiClient;

beforeEach(() => {
    _resetRecoveryFlag();
    global.confirm = jest.fn(() => false);
});

describe("apiFetch retries only reads (#429)", () => {
    const flaky = () => {
        let n = 0;
        return jest.fn(async () => {
            n += 1;
            if (n === 1) throw new TypeError("Failed to fetch");
            return { status: 200, ok: true, json: async () => ({ ok: true }) };
        });
    };

    test.each(["GET", "HEAD", undefined])("%s is retried once", async (method) => {
        global.fetch = flaky();
        const opts = method ? { method } : {};
        await expect(apiFetch("/api/tasks", opts)).resolves.toEqual({ ok: true });
        expect(global.fetch).toHaveBeenCalledTimes(2);
    });

    test.each(["POST", "PATCH", "PUT", "DELETE", "post"])("%s is not retried", async (method) => {
        global.fetch = flaky();
        await expect(apiFetch("/api/tasks", { method, body: "{}" })).rejects.toThrow(TypeError);
        expect(global.fetch).toHaveBeenCalledTimes(1);
        // The user is still told the request failed and offered a reload.
        expect(global.confirm).toHaveBeenCalled();
    });
});

describe("withInflight (#429)", () => {
    const deferred = () => {
        let resolve, reject;
        const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
        return { promise, resolve, reject };
    };

    test("a second call while the first runs is ignored", async () => {
        const btn = { disabled: false, setAttribute: jest.fn(), removeAttribute: jest.fn() };
        const d = deferred();
        const fn = jest.fn(() => d.promise);
        const first = withInflight(btn, fn);
        const second = withInflight(btn, fn);
        expect(fn).toHaveBeenCalledTimes(1);
        await expect(second).resolves.toBeUndefined();
        d.resolve("done");
        await expect(first).resolves.toBe("done");
    });

    test("a button is disabled while running and re-enabled after", async () => {
        const btn = { disabled: false, setAttribute: jest.fn(), removeAttribute: jest.fn() };
        const d = deferred();
        const run = withInflight(btn, () => d.promise);
        expect(btn.disabled).toBe(true);
        expect(btn.setAttribute).toHaveBeenCalledWith("aria-busy", "true");
        d.resolve();
        await run;
        expect(btn.disabled).toBe(false);
        expect(btn.removeAttribute).toHaveBeenCalledWith("aria-busy");
    });

    test("re-enabled after a failure too, and the error still reaches the caller", async () => {
        const btn = { disabled: false, setAttribute() {}, removeAttribute() {} };
        await expect(withInflight(btn, async () => { throw new Error("boom"); }))
            .rejects.toThrow("boom");
        expect(btn.disabled).toBe(false);
        const fn = jest.fn(async () => "again");
        await expect(withInflight(btn, fn)).resolves.toBe("again");
    });

    test("a button that was already disabled stays disabled", async () => {
        const btn = { disabled: true, setAttribute() {}, removeAttribute() {} };
        await withInflight(btn, async () => {});
        expect(btn.disabled).toBe(true);
    });

    test("an element with no disabled property (a form) is guarded, not disabled", async () => {
        const form = { setAttribute() {}, removeAttribute() {} };
        const d = deferred();
        const fn = jest.fn(() => d.promise);
        withInflight(form, fn);
        await withInflight(form, fn);
        expect(fn).toHaveBeenCalledTimes(1);
        expect("disabled" in form).toBe(false);
        d.resolve();
    });

    test("different elements don't block each other", async () => {
        const a = { disabled: false, setAttribute() {}, removeAttribute() {} };
        const b = { disabled: false, setAttribute() {}, removeAttribute() {} };
        const d = deferred();
        const fn = jest.fn(() => d.promise);
        withInflight(a, fn);
        withInflight(b, fn);
        expect(fn).toHaveBeenCalledTimes(2);
        d.resolve();
    });

    test("a list of buttons is guarded together", async () => {
        // Voice memo / scan Add All + Add Selected, /review's four buttons.
        const all = { disabled: false, setAttribute() {}, removeAttribute() {} };
        const sel = { disabled: false, setAttribute() {}, removeAttribute() {} };
        const d = deferred();
        const fn = jest.fn(() => d.promise);
        const run = withInflight([all, sel], fn);
        expect([all.disabled, sel.disabled]).toEqual([true, true]);
        await expect(withInflight([sel, all], fn)).resolves.toBeUndefined();
        await expect(withInflight(sel, fn)).resolves.toBeUndefined();
        expect(fn).toHaveBeenCalledTimes(1);
        d.resolve();
        await run;
        expect([all.disabled, sel.disabled]).toEqual([false, false]);
    });

    test("no element: just runs", async () => {
        await expect(withInflight(null, async () => 7)).resolves.toBe(7);
    });
});

describe("inflightSubmit (#429)", () => {
    const fakeForm = (btn) => ({
        querySelector: (sel) => (sel === 'button[type="submit"]' ? btn : null),
    });

    test("Enter + click on Save run the save once", async () => {
        const btn = { disabled: false, setAttribute() {}, removeAttribute() {} };
        const form = fakeForm(btn);
        let release;
        const save = jest.fn(() => new Promise((r) => { release = r; }));
        const listener = inflightSubmit(save);
        const ev = () => ({ preventDefault: jest.fn(), currentTarget: form });
        const e1 = ev();
        const first = listener(e1);
        const e2 = ev();
        await listener(e2);
        expect(save).toHaveBeenCalledTimes(1);
        expect(save).toHaveBeenCalledWith(e1);
        expect(e2.preventDefault).toHaveBeenCalled();  // no native submit either
        expect(btn.disabled).toBe(true);
        release();
        await first;
        expect(btn.disabled).toBe(false);
    });

    test("a form without a submit button is still guarded", async () => {
        const form = { querySelector: () => null, setAttribute() {}, removeAttribute() {} };
        let release;
        const save = jest.fn(() => new Promise((r) => { release = r; }));
        const listener = inflightSubmit(save);
        listener({ preventDefault() {}, currentTarget: form });
        await listener({ preventDefault() {}, currentTarget: form });
        expect(save).toHaveBeenCalledTimes(1);
        release();
    });
});
