/**
 * @jest-environment jsdom
 *
 * Jest tests for #365 — while a bulk toolbar shows, the page gets enough
 * bottom room for its last row to scroll clear of the fixed toolbar.
 *
 * Per CLAUDE.md anti-pattern #3 these assert OUTPUTS: the clearance number,
 * and the body padding the watcher sets on show / clears on hide. jsdom has
 * no layout and no ResizeObserver, so `fakeWindow` supplies both: each
 * toolbar's height comes from a map the test controls, and the observer is
 * fired by hand the way the browser fires it on a size change. Its
 * requestAnimationFrame queues callbacks until `fire()` flushes them (or a
 * test flushes by hand), since the watcher applies padding a frame later.
 */
"use strict";

const {
    bulkToolbarClearance,
    watchBulkToolbars,
    GAP_PX,
} = require("../../../static/bulk_toolbar_helpers");

describe("bulkToolbarClearance", () => {
    test("no visible toolbar → 0 (no extra room while nothing is selected)", () => {
        expect(bulkToolbarClearance([])).toBe(0);
        expect(bulkToolbarClearance([{ height: 0, bottom: 16 }])).toBe(0);
    });

    test("one visible toolbar → its height + its offset + the gap", () => {
        expect(GAP_PX).toBe(12);
        expect(bulkToolbarClearance([{ height: 81, bottom: 16 }])).toBe(81 + 16 + 12);
    });

    test("a wrapped (taller) phone toolbar needs more room", () => {
        expect(bulkToolbarClearance([{ height: 158, bottom: 16 }])).toBe(158 + 16 + 12);
    });

    test("several toolbars → room for the tallest visible one", () => {
        expect(bulkToolbarClearance([
            { height: 0, bottom: 16 },
            { height: 114, bottom: 16 },
            { height: 81, bottom: 16 },
        ])).toBe(114 + 16 + 12);
    });

    test("fractional heights round up, so the row is never a pixel short", () => {
        expect(bulkToolbarClearance([{ height: 80.4, bottom: 16 }])).toBe(109);
    });

    test("a non-numeric or negative bottom counts as 0", () => {
        expect(bulkToolbarClearance([{ height: 81, bottom: NaN }])).toBe(81 + 12);
        expect(bulkToolbarClearance([{ height: 81, bottom: -4 }])).toBe(81 + 12);
    });

    test("bad input → 0, never NaN padding", () => {
        expect(bulkToolbarClearance(undefined)).toBe(0);
        expect(bulkToolbarClearance(null)).toBe(0);
        expect(bulkToolbarClearance([null, {}, { height: "x" }])).toBe(0);
    });
});

describe("watchBulkToolbars", () => {
    let heights;

    function fakeWindow() {
        const observers = [];
        const frames = [];
        class FakeResizeObserver {
            constructor(cb) { this.cb = cb; this.targets = []; observers.push(this); }
            observe(el) { this.targets.push(el); }
            disconnect() { this.targets = []; }
        }
        const win = {
            ResizeObserver: FakeResizeObserver,
            getComputedStyle: () => ({ bottom: "16px" }),
            requestAnimationFrame: (cb) => { frames.push(cb); return frames.length; },
            // Deliver a size change, without running the next frame.
            observe() { observers.forEach((o) => o.targets.length && o.cb([])); },
            flush() { frames.splice(0).forEach((cb) => cb()); },
            // A size change, then the next frame.
            fire() { win.observe(); win.flush(); },
            observers,
            frames,
        };
        return win;
    }

    function page(ids) {
        document.body.innerHTML = ids
            .map((id) => `<div class="bulk-toolbar" id="${id}"></div>`).join("");
        document.body.style.paddingBottom = "";
        for (const id of ids) {
            document.getElementById(id).getBoundingClientRect = () => ({ height: heights[id] || 0 });
        }
    }

    beforeEach(() => { heights = {}; });

    test("hidden toolbar on load → no padding", () => {
        page(["bulkToolbar"]);
        const win = fakeWindow();
        expect(watchBulkToolbars(document, win)).not.toBeNull();
        expect(document.body.style.paddingBottom).toBe("");
    });

    test("toolbar shows → padding; hides again → padding removed", () => {
        page(["bulkToolbar"]);
        const win = fakeWindow();
        watchBulkToolbars(document, win);

        heights.bulkToolbar = 85;
        win.fire();
        expect(document.body.style.paddingBottom).toBe(`${85 + 16 + 12}px`);

        heights.bulkToolbar = 0;
        win.fire();
        expect(document.body.style.paddingBottom).toBe("");
    });

    test("the toolbar wrapping onto another line grows the padding", () => {
        page(["projectsBulkToolbar"]);
        const win = fakeWindow();
        heights.projectsBulkToolbar = 114;
        watchBulkToolbars(document, win);
        expect(document.body.style.paddingBottom).toBe(`${114 + 16 + 12}px`);

        heights.projectsBulkToolbar = 158;
        win.fire();
        expect(document.body.style.paddingBottom).toBe(`${158 + 16 + 12}px`);
    });

    test("padding lands on the next frame, not inside the observer callback", () => {
        // Changing layout inside the callback is what makes the browser
        // raise "ResizeObserver loop…" — which base.html would report.
        page(["bulkToolbar"]);
        const win = fakeWindow();
        watchBulkToolbars(document, win);
        heights.bulkToolbar = 85;
        win.observe();
        expect(document.body.style.paddingBottom).toBe("");
        expect(win.frames).toHaveLength(1);
        win.flush();
        expect(document.body.style.paddingBottom).toBe(`${85 + 16 + 12}px`);
    });

    test("several size changes before a frame → one update", () => {
        page(["bulkToolbar"]);
        const win = fakeWindow();
        watchBulkToolbars(document, win);
        heights.bulkToolbar = 85;
        win.observe();
        win.observe();
        win.observe();
        expect(win.frames).toHaveLength(1);
        win.flush();
        expect(document.body.style.paddingBottom).toBe(`${85 + 16 + 12}px`);
    });

    test("no requestAnimationFrame → falls back to a 0ms timer", () => {
        jest.useFakeTimers();
        try {
            page(["bulkToolbar"]);
            const win = fakeWindow();
            delete win.requestAnimationFrame;
            win.setTimeout = (cb, ms) => setTimeout(cb, ms);
            watchBulkToolbars(document, win);
            heights.bulkToolbar = 85;
            win.observe();
            expect(document.body.style.paddingBottom).toBe("");
            jest.runAllTimers();
            expect(document.body.style.paddingBottom).toBe(`${85 + 16 + 12}px`);
        } finally {
            jest.useRealTimers();
        }
    });

    test("observes every toolbar on the page", () => {
        page(["a", "b"]);
        const win = fakeWindow();
        watchBulkToolbars(document, win);
        expect(win.observers).toHaveLength(1);
        expect(win.observers[0].targets.map((el) => el.id)).toEqual(["a", "b"]);
    });

    test("disconnect stops watching", () => {
        page(["bulkToolbar"]);
        const win = fakeWindow();
        const w = watchBulkToolbars(document, win);
        w.disconnect();
        heights.bulkToolbar = 85;
        win.fire();
        expect(document.body.style.paddingBottom).toBe("");
    });

    test("no toolbar on the page → null, body untouched", () => {
        document.body.innerHTML = "<main></main>";
        document.body.style.paddingBottom = "";
        expect(watchBulkToolbars(document, fakeWindow())).toBeNull();
        expect(document.body.style.paddingBottom).toBe("");
    });

    test("no ResizeObserver (old browser) → null, nothing breaks", () => {
        page(["bulkToolbar"]);
        expect(watchBulkToolbars(document, { getComputedStyle: () => ({}) })).toBeNull();
        expect(watchBulkToolbars(null, fakeWindow())).toBeNull();
    });
});
