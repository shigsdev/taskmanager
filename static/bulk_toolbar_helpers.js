/**
 * #365 — the fixed bulk toolbar must never cover the last row.
 *
 * `.bulk-toolbar` is `position: fixed; bottom: 16px` (style.css), so while
 * it shows, the bottom of the page sits under it and nothing could scroll
 * the last row clear: a click meant for that card hit the toolbar instead.
 * While a toolbar is visible this gives <body> bottom padding of the
 * toolbar's height + its offset + a small gap; when it hides, the padding
 * goes. Spec: docs/design/365-bulk-toolbar-covers-last-row.md.
 *
 * A ResizeObserver does the watching: showing / hiding a toolbar
 * (display:none measures 0 high) and its buttons wrapping onto another
 * line on a phone both change its size. So the pages' own show/hide code
 * (app.js updateBulkToolbar, projects.js projectsSetupBulk) needs no hook.
 *
 * Same dual-export shape as diagram_zoom.js: an IIFE, so nothing lands in
 * the global lexical scope every static/*.js classic script shares (#359).
 *   Browser: window.bulkToolbarHelpers, wired on load.
 *   Node:    module.exports (tests/js/unit/bulk_toolbar_helpers.test.js).
 */
(function () {
    "use strict";

    // Space between the last row and the toolbar's top edge, px.
    var GAP_PX = 12;

    /**
     * Bottom room the page needs: the tallest visible toolbar's height +
     * its distance from the viewport bottom + GAP_PX, rounded up; 0 when
     * none is visible. `toolbars` is [{height, bottom}] in px; a hidden
     * toolbar has height 0, and a non-numeric bottom ("auto") counts as 0.
     */
    function bulkToolbarClearance(toolbars) {
        if (!Array.isArray(toolbars)) return 0;
        var need = 0;
        toolbars.forEach(function (t) {
            var height = t ? Number(t.height) : 0;
            if (!(height > 0)) return;
            var bottom = Number(t.bottom);
            var room = height + (bottom > 0 ? bottom : 0) + GAP_PX;
            if (room > need) need = room;
        });
        return Math.ceil(need);
    }

    /**
     * Keep <body>'s bottom padding in step with every `.bulk-toolbar` on
     * the page. Returns {update, disconnect}, or null when there is nothing
     * to watch (no toolbar on this page, or no ResizeObserver).
     */
    function watchBulkToolbars(doc, win) {
        if (!doc || !win || typeof win.ResizeObserver !== "function") return null;
        var bars = Array.prototype.slice.call(doc.querySelectorAll(".bulk-toolbar"));
        if (bars.length === 0 || !doc.body) return null;

        function update() {
            var need = bulkToolbarClearance(bars.map(function (el) {
                return {
                    height: el.getBoundingClientRect().height,
                    bottom: parseFloat(win.getComputedStyle(el).bottom),
                };
            }));
            doc.body.style.paddingBottom = need > 0 ? need + "px" : "";
        }

        // Apply on the next frame, never inside the observer callback: the
        // new padding can bring in a scrollbar, which narrows the toolbar and
        // resizes it again in the same frame. The browser reports that as a
        // "ResizeObserver loop" error event, which base.html's client error
        // reporter would ship to the logs. One frame later it is just a
        // fresh observation.
        var raf = typeof win.requestAnimationFrame === "function"
            ? win.requestAnimationFrame.bind(win)
            : function (cb) { return win.setTimeout(cb, 0); };
        var pending = false;
        function schedule() {
            if (pending) return;
            pending = true;
            raf(function () { pending = false; update(); });
        }

        var obs = new win.ResizeObserver(schedule);
        bars.forEach(function (el) { obs.observe(el); });
        update();
        return { update: update, disconnect: function () { obs.disconnect(); } };
    }

    var api = {
        bulkToolbarClearance: bulkToolbarClearance,
        watchBulkToolbars: watchBulkToolbars,
        GAP_PX: GAP_PX,
    };

    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    } else if (typeof window !== "undefined") {
        window.bulkToolbarHelpers = api;
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", function () {
                watchBulkToolbars(document, window);
            });
        } else {
            watchBulkToolbars(document, window);
        }
    }
})();
