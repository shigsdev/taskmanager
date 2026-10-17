/**
 * @jest-environment jsdom
 *
 * #419: the eight pop-up dialogs (#406 + #417) move focus in when they open
 * and back to what opened them when they close — what #377 / #454 gave the
 * side panels. One watcher (panelKeys.watchModals) sees every open and every
 * close path, whatever the dialog's own code does: display:none, the hidden
 * attribute, or the node being removed.
 */
"use strict";

const { watchModals } = require("../../../static/panel_keys");

const flush = () => new Promise((r) => setTimeout(r, 0));
const $ = (id) => document.getElementById(id);

const MODALS = [
    "modal-overlay", "reflection-focus-modal", "weekly-focus-plan-modal",
    "auto-categorize-modal", "voice-recur-overlay", "sf-modal-overlay",
    "sf-logform-overlay", "sf-print-overlay",
];

let w;
afterEach(() => { if (w) w.disconnect(); w = null; document.body.innerHTML = ""; });

function page(cls, attrs = 'style="display:none"') {
    document.body.innerHTML = `
        <button id="opener">Open</button>
        <input id="search" type="text">
        <div class="${cls}" id="m" ${attrs}>
            <div role="dialog">
                <input id="first" type="text">
                <button id="ok">OK</button>
                <button id="cancel" data-panel-close>Cancel</button>
            </div>
        </div>`;
    w = watchModals(document, window);
}

describe("watchModals (#419)", () => {
    test.each(MODALS)("%s: focus goes to its close control, then back to the opener", async (cls) => {
        page(cls);
        $("opener").focus();
        $("m").style.display = "block";
        await flush();
        expect(document.activeElement.id).toBe("cancel");
        $("m").style.display = "none";
        await flush();
        expect(document.activeElement.id).toBe("opener");
    });

    test("the hidden attribute works the same (Strength Forge)", async () => {
        page("sf-modal-overlay", "hidden");
        $("opener").focus();
        $("m").removeAttribute("hidden");
        await flush();
        expect(document.activeElement.id).toBe("cancel");
        $("m").setAttribute("hidden", "");
        await flush();
        expect(document.activeElement.id).toBe("opener");
    });

    test("a dialog built on open and removed on close (voice Make recurring)", async () => {
        document.body.innerHTML = `<button id="opener">Make recurring</button>`;
        w = watchModals(document, window);
        $("opener").focus();
        const m = document.createElement("div");
        m.className = "voice-recur-overlay";
        m.innerHTML = `<button id="x" data-panel-close>✕</button><select id="freq"></select>`;
        document.body.appendChild(m);
        await flush();
        expect(document.activeElement.id).toBe("x");
        m.remove();
        await flush();
        expect(document.activeElement.id).toBe("opener");
    });

    test("a dialog that focuses its own field keeps it, and still hands back", async () => {
        // The recycle confirm focuses its type-DELETE box itself.
        page("modal-overlay");
        $("opener").focus();
        $("m").style.display = "block";
        $("first").focus();
        await flush();
        expect(document.activeElement.id).toBe("first");
        $("m").style.display = "none";
        await flush();
        expect(document.activeElement.id).toBe("opener");
    });

    test("opened from a text field: nothing to hand back (no phone keyboard)", async () => {
        page("weekly-focus-plan-modal");
        $("search").focus();
        $("m").style.display = "block";
        await flush();
        expect(document.activeElement.id).toBe("cancel");
        $("m").style.display = "none";
        await flush();
        expect(document.activeElement.id).not.toBe("search");
    });

    test("opened with focus on the page (Safari doesn't focus a clicked button): nothing old is refocused", async () => {
        page("auto-categorize-modal");
        $("ok").focus();            // an old focus, long before the open
        $("opener").focus();
        $("opener").blur();         // focus on <body> now
        $("m").style.display = "block";
        await flush();
        $("m").style.display = "none";
        await flush();
        expect(document.activeElement).toBe(document.body);
    });

    test("an opener disabled while its request runs (#429) is still the opener", async () => {
        page("auto-categorize-modal");
        $("opener").focus();
        // withInflight disables it; Chrome then drops focus to the page,
        // sometimes before the watcher looks.
        $("opener").disabled = true;
        $("opener").setAttribute("aria-busy", "true");
        $("opener").blur();
        $("m").style.display = "block";
        await flush();
        expect(document.activeElement.id).toBe("cancel");
        $("opener").disabled = false;
        $("opener").removeAttribute("aria-busy");
        $("m").style.display = "none";
        await flush();
        expect(document.activeElement.id).toBe("opener");
    });

    test("never takes focus back from where the dialog's own close sent it", async () => {
        page("reflection-focus-modal");
        document.body.insertAdjacentHTML("beforeend", `<button id="elsewhere">x</button>`);
        $("opener").focus();
        $("m").style.display = "block";
        await flush();
        $("m").style.display = "none";
        $("elsewhere").focus();
        await flush();
        expect(document.activeElement.id).toBe("elsewhere");
    });

    test("a stacked dialog returns focus into the one under it", async () => {
        document.body.innerHTML = `
            <button id="opener">Log</button>
            <div class="sf-logform-overlay" id="a" hidden>
                <button id="aClose" data-panel-close>✕</button>
                <button id="help">ℹ️</button>
            </div>
            <div class="sf-modal-overlay" id="b" hidden>
                <button id="bClose" data-panel-close>✕</button>
            </div>`;
        w = watchModals(document, window);
        $("opener").focus();
        $("a").hidden = false;
        await flush();
        $("help").focus();
        $("b").hidden = false;
        await flush();
        expect(document.activeElement.id).toBe("bClose");
        $("b").hidden = true;
        await flush();
        expect(document.activeElement.id).toBe("help");
        $("a").hidden = true;
        await flush();
        expect(document.activeElement.id).toBe("opener");
    });

    test("the side panels are left to their own #377 / #454 code", async () => {
        page("detail-overlay");
        $("opener").focus();
        $("m").style.display = "block";
        await flush();
        expect(document.activeElement.id).toBe("opener");
    });

    test("a dialog already open when the page loads is left alone (the quiet case)", async () => {
        page("auto-categorize-modal", "");
        $("opener").focus();
        $("m").setAttribute("data-x", "1");
        await flush();
        expect(document.activeElement.id).toBe("opener");
    });
});
