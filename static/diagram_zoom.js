/**
 * #405: the /architecture "Full screen" view for Mermaid diagrams on a phone.
 *
 * On narrow screens every diagram already draws at natural size and scrolls
 * sideways inside its box (CSS, style.css "#405"). This adds a "⤢ Full
 * screen" button above each diagram that opens it in a modal <dialog> —
 * natural size, pannable both ways, ✕ / Escape to close. The buttons are
 * hidden on desktop by CSS; desktop is unchanged.
 *
 * The drawn svg is MOVED into the dialog and moved back, never copied:
 * Mermaid scopes each diagram's styles with `#<svg id> …` rules and draws
 * arrowheads from `<marker id>`s, so a clone would duplicate those ids.
 *
 * A button rather than "tap the diagram": the diagram is a swipe area, and
 * a tap-to-open on a swipe area fires on half the swipes.
 *
 * Exports (dual pattern, like the other static helpers):
 *   Browser: window.diagramZoom
 *   Node:    module.exports  (tests/js/unit/diagram_zoom.test.js, jsdom)
 */
(function () {
    "use strict";

    var ZOOM_BUTTON_CLASS = "diagram-zoom-btn";
    // The phone layout these behaviours belong to (style.css "#405").
    var PHONE_QUERY = "(max-width: 700px)";
    // What counts as drawn content. Clusters (subgraph boxes) are left out:
    // they only draw a border, so one in view still looks like an empty box.
    var NODE_SELECTOR = "g.node, g[id^='entity-']";

    /**
     * Where a full-size diagram's box should start scrolled, so it never
     * opens on an empty first screen (#405, Phase 6: "What's running" starts
     * 947px down its left column; another top-down one centres its top nodes
     * ~400px to the right). If any node is inside the first screen at
     * scrollLeft 0, stay at the left edge — the start of most flows.
     * Otherwise centre the top-most node.
     *   nodes: [{ x, y, w }] in the scrolled content's coordinates
     *   view:  { viewW, viewH, maxScroll }
     */
    function initialScrollLeft(nodes, view) {
        if (!nodes.length || view.maxScroll <= 0) return 0;
        for (var i = 0; i < nodes.length; i++) {
            var n = nodes[i];
            if (n.x < view.viewW && n.x + n.w > 0 && n.y < view.viewH) return 0;
        }
        var top = nodes[0];
        for (var j = 1; j < nodes.length; j++) {
            if (nodes[j].y < top.y) top = nodes[j];
        }
        var target = Math.round(top.x + top.w / 2 - view.viewW / 2);
        return Math.max(0, Math.min(view.maxScroll, target));
    }

    /** Measure `svg`'s nodes inside the scrolling `box` and apply
     *  initialScrollLeft. `screenH` = the viewport height. */
    function alignDiagram(box, svg, screenH) {
        var maxScroll = box.scrollWidth - box.clientWidth;
        if (maxScroll <= 0) return;
        var origin = box.getBoundingClientRect();
        var found = svg.querySelectorAll(NODE_SELECTOR);
        var nodes = [];
        for (var i = 0; i < found.length; i++) {
            var r = found[i].getBoundingClientRect();
            nodes.push({
                x: r.left - origin.left + box.scrollLeft,
                y: r.top - origin.top,
                w: r.width,
            });
        }
        box.scrollLeft = initialScrollLeft(nodes, {
            viewW: box.clientWidth,
            viewH: Math.min(box.clientHeight, screenH),
            maxScroll: maxScroll,
        });
    }

    /**
     * Phone only: align each inline diagram once its finished svg is in
     * place (Mermaid swaps it in as the <pre>'s direct child last, #395), and
     * again when a <details> holding diagrams opens — a closed box has no
     * width to measure. Mermaid's own start-up is left alone.
     */
    function watchDiagrams(doc, win) {
        if (!win.matchMedia || !win.matchMedia(PHONE_QUERY).matches) return;
        function align(pre) {
            var svg = pre.querySelector(":scope > svg");
            if (svg && pre.clientWidth > 0) alignDiagram(pre, svg, win.innerHeight);
        }
        var pres = doc.querySelectorAll("pre.mermaid");
        for (var i = 0; i < pres.length; i++) {
            (function (pre) {
                if (pre.querySelector(":scope > svg")) { align(pre); return; }
                if (typeof win.MutationObserver !== "function") return;
                var obs = new win.MutationObserver(function () {
                    if (!pre.querySelector(":scope > svg")) return;
                    obs.disconnect();
                    align(pre);
                });
                obs.observe(pre, { childList: true });
            })(pres[i]);
        }
        doc.addEventListener("toggle", function (e) {
            var det = e.target;
            if (!det || det.tagName !== "DETAILS" || !det.open) return;
            var inner = det.querySelectorAll("pre.mermaid");
            for (var k = 0; k < inner.length; k++) align(inner[k]);
        }, true); // toggle doesn't bubble; capture sees every <details>
    }
    // On <html> while the view is open: style.css stops the page behind it
    // from scrolling.
    var ZOOM_OPEN_CLASS = "diagram-zoom-open";

    /**
     * Controller for one dialog. `parts` = { dialog, body, closeBtn, doc }.
     * open(pre, opener) → true if it opened; close() → true if it closed.
     */
    function createDiagramZoom(parts) {
        var dialog = parts.dialog;
        var body = parts.body;
        var doc = parts.doc;
        var state = null; // { pre, svg, next, opener } while open

        // Put the svg back and hand focus back. Runs exactly once per open:
        // from close(), or from the dialog's own `close` event (Escape).
        function restore() {
            if (!state) return false;
            var s = state;
            state = null;
            s.pre.insertBefore(s.svg, s.next); // next === null → append
            doc.documentElement.classList.remove(ZOOM_OPEN_CLASS);
            if (s.opener && typeof s.opener.focus === "function") s.opener.focus();
            return true;
        }

        dialog.addEventListener("close", restore);

        function open(pre, opener) {
            if (state) return false;
            var svg = pre && pre.querySelector(":scope > svg");
            if (!svg) return false; // Mermaid hasn't drawn this one yet
            state = { pre: pre, svg: svg, next: svg.nextSibling, opener: opener || null };
            body.appendChild(svg);
            doc.documentElement.classList.add(ZOOM_OPEN_CLASS);
            if (typeof dialog.showModal === "function") {
                dialog.showModal();
            } else {
                dialog.setAttribute("open", "");
            }
            body.scrollTop = 0;
            body.scrollLeft = 0;
            var win = doc.defaultView;
            alignDiagram(body, svg, win ? win.innerHeight : body.clientHeight);
            if (parts.closeBtn) parts.closeBtn.focus();
            return true;
        }

        function close() {
            if (!state) return false;
            if (typeof dialog.close === "function" && dialog.hasAttribute("open")) {
                // Fires `close`, which runs restore().
                dialog.close();
            } else {
                dialog.removeAttribute("open");
            }
            restore();
            return true;
        }

        return {
            open: open,
            close: close,
            isOpen: function () { return state !== null; },
        };
    }

    /**
     * Add a Full-screen button before every `pre.mermaid` on the page and
     * wire it, the Close button and the dialog together. Expects the page to
     * hold #diagramZoom > #diagramZoomClose + #diagramZoomBody. Returns the
     * controller, or null if the page has no dialog. Safe to call twice.
     */
    function attachDiagramZoom(doc) {
        var dialog = doc.getElementById("diagramZoom");
        var body = doc.getElementById("diagramZoomBody");
        var closeBtn = doc.getElementById("diagramZoomClose");
        if (!dialog || !body) return null;
        if (dialog.__diagramZoom) return dialog.__diagramZoom;

        var zoom = createDiagramZoom({ dialog: dialog, body: body, closeBtn: closeBtn, doc: doc });
        dialog.__diagramZoom = zoom;
        if (closeBtn) closeBtn.addEventListener("click", function () { zoom.close(); });

        var pres = doc.querySelectorAll("pre.mermaid");
        for (var i = 0; i < pres.length; i++) {
            var pre = pres[i];
            var prev = pre.previousElementSibling;
            if (prev && prev.classList.contains(ZOOM_BUTTON_CLASS)) continue;
            var btn = doc.createElement("button");
            btn.type = "button";
            btn.className = ZOOM_BUTTON_CLASS;
            btn.setAttribute("aria-label", "Show this diagram full screen");
            btn.textContent = "⤢ Full screen";
            btn.addEventListener("click", (function (target, opener) {
                return function () { zoom.open(target, opener); };
            })(pre, btn));
            pre.parentNode.insertBefore(btn, pre);
        }
        if (doc.defaultView) watchDiagrams(doc, doc.defaultView);
        return zoom;
    }

    var api = {
        createDiagramZoom: createDiagramZoom,
        attachDiagramZoom: attachDiagramZoom,
        initialScrollLeft: initialScrollLeft,
        alignDiagram: alignDiagram,
        watchDiagrams: watchDiagrams,
        ZOOM_BUTTON_CLASS: ZOOM_BUTTON_CLASS,
        ZOOM_OPEN_CLASS: ZOOM_OPEN_CLASS,
    };

    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    }
    if (typeof window !== "undefined") {
        window.diagramZoom = api;
    }
})();
