/**
 * #381 — keyboard for the side panels: Escape closes the top-most open
 * panel, and Tab / Shift+Tab stay inside it.
 *
 * Covers every `.detail-overlay`: the task panel (board, /tier, /completed,
 * /calendar, /goals, /projects), the goal panel, the project panel and the
 * /recurring editor. They all share z-index 200, so when two are open (#372:
 * the task panel stacked on a goal / project panel) the later one in the DOM
 * is on top. Escape clicks that panel's `[data-panel-close]` ✕, so it runs the
 * panel's own close path, #377's focus return included, and discards unsaved
 * edits exactly as ✕ and a backdrop click do.
 * Spec: docs/design/381-panel-escape-and-focus-trap.md.
 *
 * Same dual-export shape as bulk_toolbar_helpers.js: an IIFE, so nothing
 * lands in the global lexical scope every static/*.js classic script shares
 * (#359). Loaded once from base.html; a no-op on pages with no panel open.
 *   Browser: window.panelKeys, listener attached on load.
 *   Node:    module.exports (tests/js/unit/panel_keys.test.js, jsdom).
 */
(function () {
    "use strict";

    var OVERLAY_SELECTOR = ".detail-overlay";
    var CLOSE_SELECTOR = "[data-panel-close]";
    var FOCUSABLE = [
        "a[href]",
        "button:not([disabled])",
        "input:not([disabled]):not([type=\"hidden\"])",
        "select:not([disabled])",
        "textarea:not([disabled])",
        "[tabindex]:not([tabindex=\"-1\"])",
    ].join(", ");

    /**
     * The panel on top: the last open one in DOM order (they share a
     * z-index, so later paints over earlier). `overlays` is
     * [{el, open}] in DOM order. Null when none is open.
     */
    function topOverlay(overlays) {
        if (!Array.isArray(overlays)) return null;
        var top = null;
        overlays.forEach(function (o) {
            if (o && o.open) top = o.el;
        });
        return top;
    }

    /**
     * Where Tab (shift=false) or Shift+Tab (shift=true) must send focus to
     * keep it inside the panel, or null to let the browser move it (a step
     * that stays inside the list anyway).
     *  - focus outside the panel → first (Tab) / last (Shift+Tab);
     *  - Tab on the last → first; Shift+Tab on the first → last.
     */
    function trapTarget(focusables, current, shift) {
        if (!Array.isArray(focusables) || focusables.length === 0) return null;
        var first = focusables[0];
        var last = focusables[focusables.length - 1];
        var i = focusables.indexOf(current);
        if (i === -1) return shift ? last : first;
        if (!shift && i === focusables.length - 1) return first;
        if (shift && i === 0) return last;
        return null;
    }

    function isShown(el, stop, win) {
        for (var n = el; n && n !== stop.parentElement; n = n.parentElement) {
            var cs = win.getComputedStyle(n);
            if (cs.display === "none" || cs.visibility === "hidden") return false;
        }
        return true;
    }

    /** Controls Tab can reach inside `overlay`: enabled, and not hidden. */
    function focusablesIn(overlay, win) {
        return Array.prototype.slice.call(overlay.querySelectorAll(FOCUSABLE))
            .filter(function (el) { return isShown(el, overlay, win); });
    }

    function openOverlays(doc, win) {
        return Array.prototype.slice.call(doc.querySelectorAll(OVERLAY_SELECTOR))
            .map(function (el) {
                return { el: el, open: win.getComputedStyle(el).display !== "none" };
            });
    }

    /** The document keydown handler. Returns what it did, for tests. */
    function handleKey(e, doc, win) {
        if (!e || e.defaultPrevented || e.isComposing) return "ignored";
        if (e.key !== "Escape" && e.key !== "Tab") return "ignored";
        if (e.altKey || e.ctrlKey || e.metaKey) return "ignored";
        var top = topOverlay(openOverlays(doc, win));
        if (!top) return "ignored";

        if (e.key === "Escape") {
            var close = top.querySelector(CLOSE_SELECTOR);
            if (!close) return "ignored";
            e.preventDefault();
            close.click();
            return "closed";
        }

        var target = trapTarget(focusablesIn(top, win), doc.activeElement, e.shiftKey);
        if (!target) return "browser";
        e.preventDefault();
        target.focus();
        return "trapped";
    }

    function attachPanelKeys(doc, win) {
        if (!doc || !win) return null;
        function onKey(e) { handleKey(e, doc, win); }
        doc.addEventListener("keydown", onKey);
        return { detach: function () { doc.removeEventListener("keydown", onKey); } };
    }

    var api = {
        topOverlay: topOverlay,
        trapTarget: trapTarget,
        focusablesIn: focusablesIn,
        handleKey: handleKey,
        attachPanelKeys: attachPanelKeys,
    };

    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    } else if (typeof window !== "undefined") {
        window.panelKeys = api;
        attachPanelKeys(document, window);
    }
})();
