/**
 * @jest-environment jsdom
 *
 * Jest tests for #405 — the /architecture "Full screen" diagram view.
 *
 * The view MOVES the drawn Mermaid svg into a modal <dialog> and back
 * (never a copy: Mermaid's svg uses ids for its scoped styles and arrowhead
 * markers, a clone would duplicate them). What must hold, and is asserted
 * on the real DOM here: the same element goes in and comes back to the same
 * place; focus goes to Close and back to the opener; the browser closing
 * the dialog on Escape restores it too; nothing happens before Mermaid has
 * drawn the svg or while the view is already open.
 *
 * jsdom has no HTMLDialogElement.showModal/close, so `fakeDialog` gives the
 * element the browser's observable behaviour: showModal sets `open`, close
 * clears it and fires a `close` event (which is also what Escape does).
 */
"use strict";

const {
    createDiagramZoom,
    attachDiagramZoom,
    initialScrollLeft,
    alignDiagram,
    ZOOM_BUTTON_CLASS,
    ZOOM_OPEN_CLASS,
} = require("../../../static/diagram_zoom");

// Node boxes are { x, y, w } in the scrolled content's coordinates.
describe("initialScrollLeft (#405: never open on an empty first screen)", () => {
    const view = { viewW: 300, viewH: 800, maxScroll: 1600 };

    test("stays at the left edge when the first screen already shows a node", () => {
        const nodes = [{ x: 24, y: 128, w: 120 }, { x: 900, y: 20, w: 200 }];
        expect(initialScrollLeft(nodes, view)).toBe(0);
    });

    test("a node only partly inside the first screen still counts", () => {
        const nodes = [{ x: 280, y: 790, w: 100 }];
        expect(initialScrollLeft(nodes, view)).toBe(0);
    });

    test("#2's shape: start 947px down the left column → centre the top-most node", () => {
        const nodes = [
            { x: 24, y: 966, w: 40 },    // You
            { x: 114, y: 947, w: 257 },  // Browser
            { x: 783, y: 24, w: 247 },   // APScheduler (top-most)
            { x: 1267, y: 42, w: 126 },
        ];
        // centre of APScheduler (906.5) − half the view (150) = 756.5
        expect(initialScrollLeft(nodes, view)).toBe(757);
    });

    test("never scrolls past either end", () => {
        expect(initialScrollLeft([{ x: 1900, y: 0, w: 100 }], view)).toBe(1600);
        expect(initialScrollLeft([{ x: 320, y: 2000, w: 10 }, { x: 310, y: 900, w: 10 }], view))
            .toBe(165);
    });

    test("no nodes, or a box that doesn't scroll → 0", () => {
        expect(initialScrollLeft([], view)).toBe(0);
        expect(initialScrollLeft([{ x: 900, y: 900, w: 10 }], { ...view, maxScroll: 0 })).toBe(0);
    });
});

describe("alignDiagram", () => {
    function box(scrollW, clientW, clientH) {
        const pre = document.createElement("pre");
        Object.defineProperty(pre, "scrollWidth", { value: scrollW });
        Object.defineProperty(pre, "clientWidth", { value: clientW });
        Object.defineProperty(pre, "clientHeight", { value: clientH });
        let scrollLeft = 0;
        Object.defineProperty(pre, "scrollLeft", {
            get: () => scrollLeft,
            set: (v) => { scrollLeft = v; },
        });
        pre.getBoundingClientRect = () => ({ left: 10, top: 100 });
        return pre;
    }
    function node(svg, x, y, w) {
        const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
        g.setAttribute("class", "node");
        g.getBoundingClientRect = () => ({ left: 10 + x, top: 100 + y, width: w });
        svg.appendChild(g);
    }

    test("scrolls an empty-first-screen box to its top-most node", () => {
        const pre = box(1909, 300, 1200);
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        pre.appendChild(svg);
        node(svg, 114, 947, 257);
        node(svg, 783, 24, 247);
        alignDiagram(pre, svg, 812);
        expect(pre.scrollLeft).toBe(757);
    });

    test("leaves a box alone when its first screen shows a node", () => {
        const pre = box(900, 300, 500);
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        pre.appendChild(svg);
        node(svg, 20, 30, 100);
        node(svg, 600, 10, 100);
        alignDiagram(pre, svg, 812);
        expect(pre.scrollLeft).toBe(0);
    });

    test("cluster boxes don't count as content (they only draw a border)", () => {
        const pre = box(1909, 300, 1200);
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        pre.appendChild(svg);
        const cluster = document.createElementNS("http://www.w3.org/2000/svg", "g");
        cluster.setAttribute("class", "cluster");
        cluster.getBoundingClientRect = () => ({ left: 10, top: 100, width: 1500 });
        svg.appendChild(cluster);
        node(svg, 783, 24, 247);
        alignDiagram(pre, svg, 812);
        expect(pre.scrollLeft).toBe(757);
    });
});

function fakeDialog(dialog) {
    dialog.showModal = function () { this.setAttribute("open", ""); };
    dialog.close = function () {
        if (!this.hasAttribute("open")) return;
        this.removeAttribute("open");
        this.dispatchEvent(new Event("close"));
    };
    return dialog;
}

function page() {
    document.body.innerHTML = `
        <h3>Flow A</h3>
        <pre class="mermaid" id="a"><svg id="svgA" viewBox="0 0 900 400"></svg><span id="afterA"></span></pre>
        <pre class="mermaid" id="b"><svg id="svgB" viewBox="0 0 700 300"></svg></pre>
        <pre class="mermaid" id="pending">flowchart LR; A-->B</pre>
        <dialog id="diagramZoom">
            <button type="button" id="diagramZoomClose">Close</button>
            <div id="diagramZoomBody"></div>
        </dialog>`;
    const dialog = fakeDialog(document.getElementById("diagramZoom"));
    return {
        dialog,
        body: document.getElementById("diagramZoomBody"),
        closeBtn: document.getElementById("diagramZoomClose"),
    };
}

describe("createDiagramZoom", () => {
    let parts;
    let zoom;
    let opener;

    beforeEach(() => {
        parts = page();
        zoom = createDiagramZoom({ ...parts, doc: document });
        opener = document.createElement("button");
        document.body.prepend(opener);
        opener.focus();
    });

    test("open moves the SAME svg into the dialog and shows it", () => {
        const svg = document.getElementById("svgA");
        expect(zoom.open(document.getElementById("a"), opener)).toBe(true);
        expect(parts.body.firstElementChild).toBe(svg);
        expect(document.getElementById("a").querySelector("svg")).toBeNull();
        expect(parts.dialog.hasAttribute("open")).toBe(true);
        expect(zoom.isOpen()).toBe(true);
        expect(document.documentElement.classList.contains(ZOOM_OPEN_CLASS)).toBe(true);
    });

    test("focus goes to Close on open and back to the opener on close", () => {
        zoom.open(document.getElementById("a"), opener);
        expect(document.activeElement).toBe(parts.closeBtn);
        zoom.close();
        expect(document.activeElement).toBe(opener);
    });

    test("close puts the svg back exactly where it was", () => {
        const pre = document.getElementById("a");
        const svg = document.getElementById("svgA");
        zoom.open(pre, opener);
        expect(zoom.close()).toBe(true);
        expect(pre.firstElementChild).toBe(svg);
        expect(svg.nextElementSibling).toBe(document.getElementById("afterA"));
        expect(parts.body.children).toHaveLength(0);
        expect(parts.dialog.hasAttribute("open")).toBe(false);
        expect(zoom.isOpen()).toBe(false);
        expect(document.documentElement.classList.contains(ZOOM_OPEN_CLASS)).toBe(false);
    });

    test("the browser closing the dialog (Escape) restores it the same way", () => {
        const pre = document.getElementById("b");
        const svg = document.getElementById("svgB");
        zoom.open(pre, opener);
        parts.dialog.close(); // what Escape does: dialog closes, `close` fires
        expect(pre.firstElementChild).toBe(svg);
        expect(zoom.isOpen()).toBe(false);
        expect(document.activeElement).toBe(opener);
    });

    test("opening while open is a no-op and keeps the first diagram", () => {
        zoom.open(document.getElementById("a"), opener);
        expect(zoom.open(document.getElementById("b"), opener)).toBe(false);
        expect(parts.body.firstElementChild.id).toBe("svgA");
        expect(document.getElementById("b").querySelector("svg").id).toBe("svgB");
    });

    test("a diagram Mermaid hasn't drawn yet does nothing", () => {
        expect(zoom.open(document.getElementById("pending"), opener)).toBe(false);
        expect(parts.dialog.hasAttribute("open")).toBe(false);
        expect(zoom.isOpen()).toBe(false);
    });

    test("close when nothing is open is a no-op", () => {
        expect(zoom.close()).toBe(false);
    });

    test("without showModal it falls back to the open attribute", () => {
        delete parts.dialog.showModal;
        parts.dialog.close = undefined;
        zoom.open(document.getElementById("a"), opener);
        expect(parts.dialog.hasAttribute("open")).toBe(true);
        zoom.close();
        expect(parts.dialog.hasAttribute("open")).toBe(false);
        expect(document.getElementById("a").querySelector("svg").id).toBe("svgA");
    });
});

describe("watchDiagrams", () => {
    const { watchDiagrams } = require("../../../static/diagram_zoom");

    function measurableBox(pre) {
        Object.defineProperty(pre, "scrollWidth", { value: 1909, configurable: true });
        Object.defineProperty(pre, "clientWidth", { value: 300, configurable: true });
        Object.defineProperty(pre, "clientHeight", { value: 1200, configurable: true });
        let sl = 0;
        Object.defineProperty(pre, "scrollLeft", { get: () => sl, set: (v) => { sl = v; }, configurable: true });
        pre.getBoundingClientRect = () => ({ left: 10, top: 100 });
    }
    // Like a real layout box, the node's on-screen position moves with the
    // box's scrollLeft — which is what makes aligning twice harmless.
    function drawnSvg() {
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
        g.setAttribute("class", "node");
        g.getBoundingClientRect = () => {
            const box = svg.parentNode;
            return { left: 10 + 783 - (box ? box.scrollLeft : 0), top: 100 + 24, width: 247 };
        };
        svg.appendChild(g);
        return svg;
    }
    const phone = (matches) => ({
        matchMedia: () => ({ matches }),
        innerHeight: 812,
        MutationObserver: window.MutationObserver,
    });

    test("aligns a diagram when Mermaid swaps its finished svg in", async () => {
        document.body.innerHTML = '<pre class="mermaid">flowchart LR; A-->B</pre>';
        const pre = document.querySelector("pre");
        measurableBox(pre);
        watchDiagrams(document, phone(true));
        pre.textContent = "";
        pre.appendChild(drawnSvg());
        await Promise.resolve(); // MutationObserver callbacks are microtasks
        expect(pre.scrollLeft).toBe(757);
    });

    test("aligns diagrams inside a <details> when it opens", () => {
        document.body.innerHTML = '<details><summary>x</summary><pre class="mermaid"></pre></details>';
        const pre = document.querySelector("pre");
        pre.appendChild(drawnSvg());
        Object.defineProperty(pre, "clientWidth", { value: 0, configurable: true });
        watchDiagrams(document, phone(true)); // closed: nothing to measure yet
        measurableBox(pre);
        const det = document.querySelector("details");
        det.open = true;
        det.dispatchEvent(new Event("toggle"));
        expect(pre.scrollLeft).toBe(757);
        det.dispatchEvent(new Event("toggle")); // a second toggle: same answer
        expect(pre.scrollLeft).toBe(757);
    });

    test("does nothing on desktop", async () => {
        document.body.innerHTML = '<pre class="mermaid"></pre>';
        const pre = document.querySelector("pre");
        measurableBox(pre);
        pre.appendChild(drawnSvg());
        watchDiagrams(document, phone(false));
        expect(pre.scrollLeft).toBe(0);
    });
});

describe("attachDiagramZoom", () => {
    test("adds one Full screen button before each diagram, wired to open it", () => {
        const parts = page();
        const zoom = attachDiagramZoom(document);
        const buttons = [...document.querySelectorAll(`.${ZOOM_BUTTON_CLASS}`)];
        expect(buttons).toHaveLength(3);
        buttons.forEach((btn) => {
            expect(btn.tagName).toBe("BUTTON");
            expect(btn.type).toBe("button");
            expect(btn.nextElementSibling.matches("pre.mermaid")).toBe(true);
            expect(btn.getAttribute("aria-label")).toMatch(/full screen/i);
        });

        buttons[1].click();
        expect(parts.body.firstElementChild.id).toBe("svgB");
        expect(zoom.isOpen()).toBe(true);

        parts.closeBtn.click();
        expect(document.getElementById("b").firstElementChild.id).toBe("svgB");
        expect(document.activeElement).toBe(buttons[1]);
    });

    test("is idempotent: a second attach adds no duplicate buttons", () => {
        page();
        attachDiagramZoom(document);
        attachDiagramZoom(document);
        expect(document.querySelectorAll(`.${ZOOM_BUTTON_CLASS}`)).toHaveLength(3);
    });

    test("does nothing on a page without the dialog", () => {
        document.body.innerHTML = '<pre class="mermaid"><svg></svg></pre>';
        expect(attachDiagramZoom(document)).toBeNull();
        expect(document.querySelectorAll(`.${ZOOM_BUTTON_CLASS}`)).toHaveLength(0);
    });
});
