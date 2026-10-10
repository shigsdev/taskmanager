/**
 * @jest-environment jsdom
 *
 * Jest tests for #381: Escape closes the top-most side panel, and Tab /
 * Shift+Tab stay inside it.
 *
 * Per CLAUDE.md anti-pattern #3 these assert OUTPUTS: which panel the
 * pure helpers pick, where focus is sent, and on the real DOM which ✕ gets
 * clicked and where focus lands. jsdom has no layout. Visibility comes from
 * computed `display` / `visibility`, which jsdom does compute from inline
 * styles and the `hidden` attribute.
 */
"use strict";

const {
    topOverlay,
    trapTarget,
    focusablesIn,
    handleKey,
    attachPanelKeys,
} = require("../../../static/panel_keys");

describe("topOverlay", () => {
    const a = { id: "a" }, b = { id: "b" };

    test("nothing open → null", () => {
        expect(topOverlay([])).toBeNull();
        expect(topOverlay([{ el: a, open: false }])).toBeNull();
        expect(topOverlay(undefined)).toBeNull();
    });

    test("one open → that one", () => {
        expect(topOverlay([{ el: a, open: true }, { el: b, open: false }])).toBe(a);
    });

    test("two open (#372 stack) → the later one in the DOM", () => {
        expect(topOverlay([{ el: a, open: true }, { el: b, open: true }])).toBe(b);
    });
});

describe("trapTarget", () => {
    const [x, y, z] = ["x", "y", "z"];
    const list = [x, y, z];

    test("Tab on the last wraps to the first", () => {
        expect(trapTarget(list, z, false)).toBe(x);
    });

    test("Shift+Tab on the first wraps to the last", () => {
        expect(trapTarget(list, x, true)).toBe(z);
    });

    test("a step inside the list is left to the browser", () => {
        expect(trapTarget(list, x, false)).toBeNull();
        expect(trapTarget(list, y, false)).toBeNull();
        expect(trapTarget(list, y, true)).toBeNull();
        expect(trapTarget(list, z, true)).toBeNull();
    });

    test("focus outside the panel → first (Tab) / last (Shift+Tab)", () => {
        expect(trapTarget(list, "elsewhere", false)).toBe(x);
        expect(trapTarget(list, null, true)).toBe(z);
    });

    test("one control: Tab and Shift+Tab both stay on it", () => {
        expect(trapTarget([x], x, false)).toBe(x);
        expect(trapTarget([x], x, true)).toBe(x);
    });

    test("no controls or bad input → null", () => {
        expect(trapTarget([], x, false)).toBeNull();
        expect(trapTarget(undefined, x, false)).toBeNull();
    });
});

describe("on the page", () => {
    let closed, detach;

    // Two side panels in DOM order, like /goals: the goal panel, then the
    // task panel (_task_detail_panel.html is included after it).
    // (An open panel has no style attribute: jsdom can't later set
    // display:none on an element that started as style="display:".)
    const shut = (open) => (open ? "" : ' style="display:none"');

    function page({ goalOpen = true, taskOpen = true } = {}) {
        document.body.innerHTML = `
            <button id="behind">card behind</button>
            <div class="detail-overlay" id="goalDetailOverlay"${shut(goalOpen)}>
                <div class="detail-panel">
                    <button id="goalDetailClose" data-panel-close>✕</button>
                    <input id="goalTitle">
                    <button id="goalSave">Save</button>
                </div>
            </div>
            <div class="detail-overlay" id="detailOverlay"${shut(taskOpen)}>
                <div class="detail-panel">
                    <button id="detailClose" data-panel-close>✕</button>
                    <input id="detailTitle">
                    <input type="hidden" id="detailId">
                    <div id="repeatDays" style="display:none"><select id="repeatDay"></select></div>
                    <p hidden><button id="hiddenBtn">x</button></p>
                    <button id="disabledBtn" disabled>Nope</button>
                    <span id="notFocusable">text</span>
                    <button id="detailSave">Save</button>
                </div>
            </div>`;
        closed = [];
        for (const id of ["goalDetailClose", "detailClose"]) {
            const btn = document.getElementById(id);
            btn.addEventListener("click", () => {
                closed.push(id);
                btn.closest(".detail-overlay").style.display = "none";
            });
        }
    }

    function press(key, opts = {}) {
        const e = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...opts });
        (document.activeElement || document.body).dispatchEvent(e);
        return e;
    }

    const $ = (id) => document.getElementById(id);

    beforeEach(() => { detach = attachPanelKeys(document, window).detach; });
    afterEach(() => detach());

    test("focusablesIn skips hidden-type inputs, hidden sections and disabled buttons", () => {
        page();
        expect(focusablesIn($("detailOverlay"), window).map((el) => el.id))
            .toEqual(["detailClose", "detailTitle", "detailSave"]);
    });

    test("Escape closes only the top panel; a second Escape closes the one under it", () => {
        page();
        $("detailTitle").focus();
        const e = press("Escape");
        expect(closed).toEqual(["detailClose"]);
        expect(e.defaultPrevented).toBe(true);
        expect($("goalDetailOverlay").style.display).toBe("");

        press("Escape");
        expect(closed).toEqual(["detailClose", "goalDetailClose"]);
    });

    test("Escape with no panel open does nothing", () => {
        page({ goalOpen: false, taskOpen: false });
        const e = press("Escape");
        expect(closed).toEqual([]);
        expect(e.defaultPrevented).toBe(false);
    });

    test("Escape already handled elsewhere, or mid-composition, is left alone", () => {
        page();
        const handled = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
        handled.preventDefault();
        expect(handleKey(handled, document, window)).toBe("ignored");
        expect(handleKey({ key: "Escape", isComposing: true }, document, window)).toBe("ignored");
        expect(closed).toEqual([]);
    });

    test("an open panel without a [data-panel-close] ✕ is not closed", () => {
        page({ goalOpen: false });
        $("detailClose").removeAttribute("data-panel-close");
        expect(press("Escape").defaultPrevented).toBe(false);
        expect(closed).toEqual([]);
    });

    test("other keys and modified Tab are ignored", () => {
        page();
        expect(handleKey({ key: "Enter" }, document, window)).toBe("ignored");
        $("detailSave").focus();
        expect(press("Tab", { ctrlKey: true }).defaultPrevented).toBe(false);
        expect(document.activeElement.id).toBe("detailSave");
    });

    test("Tab on the top panel's last control wraps to its ✕", () => {
        page();
        $("detailSave").focus();
        const e = press("Tab");
        expect(e.defaultPrevented).toBe(true);
        expect(document.activeElement.id).toBe("detailClose");
    });

    test("Shift+Tab on the ✕ wraps to the last control, skipping hidden and disabled ones", () => {
        page();
        $("detailClose").focus();
        press("Tab", { shiftKey: true });
        expect(document.activeElement.id).toBe("detailSave");
    });

    test("Tab in the middle is left to the browser", () => {
        page();
        $("detailClose").focus();
        const e = press("Tab");
        expect(e.defaultPrevented).toBe(false);
        expect(document.activeElement.id).toBe("detailClose");
    });

    test("focus still behind the panel: Tab pulls it into the top panel", () => {
        page({ taskOpen: false });
        $("behind").focus();
        press("Tab");
        expect(document.activeElement.id).toBe("goalDetailClose");
        $("behind").focus();
        press("Tab", { shiftKey: true });
        expect(document.activeElement.id).toBe("goalSave");
    });

    test("the trap follows the top panel: the goal panel's controls are out of reach under the task panel", () => {
        page();
        $("goalSave").focus();
        press("Tab");
        expect(document.activeElement.id).toBe("detailClose");
    });

    test("no panel open: Tab is never touched", () => {
        page({ goalOpen: false, taskOpen: false });
        $("behind").focus();
        expect(press("Tab").defaultPrevented).toBe(false);
    });
});
