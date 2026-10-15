/**
 * @jest-environment jsdom
 */
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

// #457: dropdown menus had no Escape, no focus movement, no menu roles.
describe("menuKeyTarget (#457)", () => {
    const { menuKeyTarget } = require("../../../static/menu_helpers.js");
    test("down / up move one and wrap", () => {
        expect(menuKeyTarget(3, 0, "ArrowDown")).toBe(1);
        expect(menuKeyTarget(3, 2, "ArrowDown")).toBe(0);
        expect(menuKeyTarget(3, 0, "ArrowUp")).toBe(2);
        expect(menuKeyTarget(3, 2, "ArrowUp")).toBe(1);
    });
    test("from nowhere: down is the first, up the last", () => {
        expect(menuKeyTarget(3, -1, "ArrowDown")).toBe(0);
        expect(menuKeyTarget(3, -1, "ArrowUp")).toBe(2);
    });
    test("Home / End", () => {
        expect(menuKeyTarget(4, 2, "Home")).toBe(0);
        expect(menuKeyTarget(4, 1, "End")).toBe(3);
    });
    test("other keys and empty menus → null", () => {
        expect(menuKeyTarget(3, 0, "a")).toBeNull();
        expect(menuKeyTarget(0, -1, "ArrowDown")).toBeNull();
    });
});

describe("attachMenu (#457)", () => {
    const { attachMenu } = require("../../../static/menu_helpers.js");
    const key = (el, k) => {
        const e = new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true });
        el.dispatchEvent(e);
        return e;
    };
    const setup = () => {
        document.body.innerHTML = `<button id="open">Status ▾</button>
            <div id="m"><button>Mark complete</button><button>Mark cancelled</button><button>Mark active</button></div>`;
        return { open: document.getElementById("open"), menu: document.getElementById("m") };
    };
    const items = () => [...document.querySelectorAll("#m button")];

    test("roles, expanded state, focus on the first item", () => {
        const { open, menu } = setup();
        open.focus();
        attachMenu(open, menu);
        expect(open.getAttribute("aria-haspopup")).toBe("menu");
        expect(open.getAttribute("aria-expanded")).toBe("true");
        expect(menu.getAttribute("role")).toBe("menu");
        expect(items().map((b) => b.getAttribute("role"))).toEqual(["menuitem", "menuitem", "menuitem"]);
        expect(document.activeElement).toBe(items()[0]);
    });

    test("arrows move between items, wrapping", () => {
        const { open, menu } = setup();
        attachMenu(open, menu);
        key(document.activeElement, "ArrowDown");
        expect(document.activeElement).toBe(items()[1]);
        key(document.activeElement, "End");
        expect(document.activeElement).toBe(items()[2]);
        key(document.activeElement, "ArrowDown");
        expect(document.activeElement).toBe(items()[0]);
    });

    test("Escape closes it, hands focus back, and is consumed", () => {
        const { open, menu } = setup();
        attachMenu(open, menu);
        const e = key(document.activeElement, "Escape");
        expect(e.defaultPrevented).toBe(true);
        expect(menu.isConnected).toBe(false);
        expect(document.activeElement).toBe(open);
        expect(open.getAttribute("aria-expanded")).toBe("false");
    });

    test("Tab closes it without taking focus back", () => {
        const { open, menu } = setup();
        attachMenu(open, menu);
        const e = key(document.activeElement, "Tab");
        expect(e.defaultPrevented).toBe(false);
        expect(menu.isConnected).toBe(false);
    });

    test("a dialog popup: Escape closes, arrows do nothing, focus untouched", () => {
        document.body.innerHTML = `<button id="open">Due date ▾</button>
            <div id="m"><input id="d" type="date"><button>Apply</button></div>`;
        const open = document.getElementById("open"), menu = document.getElementById("m");
        document.getElementById("d").focus();
        attachMenu(open, menu, { kind: "dialog" });
        expect(open.getAttribute("aria-haspopup")).toBe("dialog");
        expect(document.activeElement.id).toBe("d");
        expect(key(document.activeElement, "ArrowDown").defaultPrevented).toBe(false);
        key(document.activeElement, "Escape");
        expect(menu.isConnected).toBe(false);
        expect(document.activeElement).toBe(open);
    });
});
