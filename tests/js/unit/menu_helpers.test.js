/**
 * Jest tests for #487: where a popup menu goes so it stays on screen.
 * /projects' bulk menus always opened under their button, which sits in the
 * bottom toolbar, so they opened below the screen.
 */
const { placeMenu } = require("../../../static/menu_helpers.js");

const vp = { width: 375, height: 812 };
// An anchor rect like getBoundingClientRect's.
const at = (left, top, height = 44, width = 60) =>
    ({ left, top, bottom: top + height, right: left + width });

describe("placeMenu (#487)", () => {
    test("opens below when it fits there", () => {
        const p = placeMenu(at(20, 100), { width: 180, height: 120 }, vp);
        expect(p).toEqual({ left: 20, top: 148, maxHeight: null });
    });

    test("opens above when the space below is too short (bottom toolbar)", () => {
        // Status menu, measured: button 691-735, menu 122px tall.
        const p = placeMenu(at(180, 691), { width: 180, height: 122 }, vp);
        expect(p.top).toBe(691 - 4 - 122);
        expect(p.maxHeight).toBeNull();
    });

    test("too tall for either side: the bigger side, capped so it scrolls", () => {
        // Goal menu, measured: button 743-787, menu 300px — and a short screen.
        const p = placeMenu(at(19, 300), { width: 293, height: 500 },
            { width: 375, height: 600 });
        // 300 - 4 - 8 = 288 above vs 600 - 344 - 4 - 8 = 244 below.
        expect(p.maxHeight).toBe(288);
        expect(p.top).toBe(8);
        // Below wins when it has more room.
        const q = placeMenu(at(19, 200), { width: 293, height: 500 },
            { width: 375, height: 600 });
        expect(q.top).toBe(248);
        expect(q.maxHeight).toBe(600 - 248 - 8);
    });

    test("never runs past the right edge", () => {
        const p = placeMenu(at(300, 100), { width: 180, height: 50 }, vp);
        expect(p.left).toBe(375 - 180 - 8);
    });

    test("never starts left of the left margin", () => {
        const p = placeMenu(at(2, 100), { width: 180, height: 50 }, vp);
        expect(p.left).toBe(8);
    });

    test("a menu wider than the screen keeps the left margin", () => {
        const p = placeMenu(at(100, 100), { width: 500, height: 50 }, vp);
        expect(p.left).toBe(8);
    });

    test("margin and gap are adjustable", () => {
        const p = placeMenu(at(0, 100), { width: 100, height: 50 }, vp,
            { margin: 16, gap: 0 });
        expect(p).toEqual({ left: 16, top: 144, maxHeight: null });
    });
});
