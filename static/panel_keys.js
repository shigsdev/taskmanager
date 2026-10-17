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
 * #406: also the five modals that use other markup — the /recycle-bin
 * confirm, /reflection's focus picker, the board's ✨ Plan and 💡
 * Auto-categorize reviews, and the voice memo's Make-recurring dialog. Each
 * one's own Cancel / ✕ carries [data-panel-close], so Escape does exactly
 * what that control does. Spec: docs/design/406-modal-escape-and-focus-trap.md.
 *
 * Same dual-export shape as bulk_toolbar_helpers.js: an IIFE, so nothing
 * lands in the global lexical scope every static/*.js classic script shares
 * (#359). Loaded once from base.html; a no-op on pages with no panel open.
 *   Browser: window.panelKeys, listener attached on load.
 *   Node:    module.exports (tests/js/unit/panel_keys.test.js, jsdom).
 */
(function () {
    "use strict";

    var OVERLAY_SELECTOR = [
        ".detail-overlay",
        ".modal-overlay",              // #406: /recycle-bin confirm
        ".reflection-focus-modal",     // #406: /reflection focus picker
        ".weekly-focus-plan-modal",    // #406: board ✨ Plan review
        ".auto-categorize-modal",      // #406: board 💡 Auto-categorize
        ".voice-recur-overlay",        // #406: voice memo Make recurring
        ".sf-modal-overlay",           // #417: Strength Forge how-to
        ".sf-logform-overlay",         // #417: Strength Forge log form
        ".sf-print-overlay",           // #417: Strength Forge print sheet
    ].join(", ");
    var CLOSE_SELECTOR = "[data-panel-close]";
    var FOCUSABLE = [
        "a[href]",
        "button:not([disabled])",
        "input:not([disabled]):not([type=\"hidden\"])",
        "select:not([disabled])",
        "textarea:not([disabled])",
        "[tabindex]:not([tabindex=\"-1\"])",
        // #456: a <details>' summary is a Tab stop (the project / goal
        // panel's "Completed (N)"); unlisted, Tab from it counted as "focus
        // outside the panel" and jumped to ✕, past the rows and Save.
        "summary",
        "[contenteditable]:not([contenteditable=\"false\"])",
    ].join(", ");

    /**
     * The overlay on top: the open one with the highest z-index, and on a
     * tie the last in DOM order (later paints over earlier). The side
     * panels share z-index 200; #406's modals run 200-1000, so DOM order
     * alone could hand Escape to a panel underneath a modal. `overlays` is
     * [{el, open, z}] in DOM order; a missing z counts as 0. Null when none
     * is open.
     */
    function topOverlay(overlays) {
        if (!Array.isArray(overlays)) return null;
        var top = null, topZ = -Infinity;
        overlays.forEach(function (o) {
            if (!o || !o.open) return;
            var z = typeof o.z === "number" && !isNaN(o.z) ? o.z : 0;
            if (z >= topZ) { top = o.el; topZ = z; }
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
            // #456: inside a CLOSED <details>, only its own summary shows —
            // the collapsed rows aren't rendered, so Tab can't land on them.
            if (n !== el && n.tagName === "DETAILS" && !n.open) {
                var summary = n.querySelector(":scope > summary");
                if (!summary || !summary.contains(el)) return false;
            }
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
                var cs = win.getComputedStyle(el);
                return { el: el, open: cs.display !== "none", z: parseInt(cs.zIndex, 10) };
            });
    }

    /**
     * #446: is any listed overlay open? base.html's userIsBusy() asks this
     * before the service worker's auto-reload, so an open goal panel, ✨ Plan
     * review or modal shows the "Update available" banner instead of being
     * reloaded away. Same list and same open test as Escape uses.
     */
    function anyOpen(doc, win) {
        if (!doc || !win) return false;
        return openOverlays(doc, win).some(function (o) { return o.open; });
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

    /**
     * #454: a card, row or line that opens a panel on click becomes a button
     * for the keyboard too: a Tab stop, announced as a button named `label`,
     * opened by Enter or Space aimed at it (not at a checkbox or link inside
     * it). The rules #372's projectTaskLineAffordance set, shared.
     */
    function makeOpener(el, label, onOpen) {
        el.tabIndex = 0;
        el.setAttribute("role", "button");
        el.setAttribute("aria-label", label);
        el.addEventListener("keydown", function (e) {
            if (e.target !== el) return;
            if (e.key !== "Enter" && e.key !== " ") return;
            e.preventDefault();
            e.stopPropagation();
            onOpen();
        });
    }

    /*
     * #454: focus into a panel and back, for the panels #377 didn't cover
     * (goal, project, /recurring editor) — the task panel's rules:
     *   opened(doc, overlay, closeBtn, keyAttr) — before showing the panel's
     *     content, remember what had focus (never a text field: refocusing
     *     one pops the phone keyboard), then focus the ✕. A script-moved
     *     focus only shows a ring after a keyboard open (:focus-visible).
     *   closed(doc, overlay) — hand focus back to that element.
     *   afterRender(doc) — a save re-renders the list and replaces the card
     *     that was focused; find it again by `keyAttr` (e.g. data-goal-id),
     *     only when focus fell to the page, never stealing it.
     * One memory per overlay id.
     */
    var _openers = {};

    function opened(doc, overlay, closeBtn, keyAttr) {
        var key = overlay.id;
        var el = doc.activeElement;
        // Already open (a re-open from inside it): keep the first opener.
        if (!_openers[key] || !_openers[key].open) {
            _openers[key] = null;
            if (el && el !== doc.body && !overlay.contains(el) &&
                    !el.matches("input, textarea, select, [contenteditable]")) {
                _openers[key] = {
                    el: el, attr: keyAttr || null,
                    value: keyAttr ? el.getAttribute(keyAttr) : null,
                    open: true, pending: false,
                };
            }
        }
        if (closeBtn) closeBtn.focus();
    }

    function _twin(doc, memo) {
        if (memo.el && memo.el.isConnected) return memo.el;
        if (!memo.attr || !memo.value) return null;
        var v = String(memo.value).replace(/["\\]/g, "\\$&");
        return doc.querySelector("[" + memo.attr + "=\"" + v + "\"]");
    }

    function closed(doc, overlay) {
        var memo = _openers[overlay.id];
        if (!memo || !memo.open) return;
        memo.open = false;
        var target = _twin(doc, memo);
        if (target) target.focus();
        memo.pending = true;
    }

    function afterRender(doc) {
        Object.keys(_openers).forEach(function (key) {
            var memo = _openers[key];
            if (!memo || !memo.pending) return;
            var active = doc.activeElement;
            _openers[key] = null;
            // Focus is somewhere live (the card survived the render, or the
            // user moved on): leave it.
            if (active && active !== doc.body && active.isConnected) return;
            var target = _twin(doc, memo);
            if (target) target.focus();
        });
    }

    /*
     * #419: focus into the eight pop-up dialogs and back — what #377 / #454
     * gave the side panels. Rather than wire each dialog's open and every
     * close path (✕, Cancel, Escape, backdrop, Apply, Save…), one watcher
     * notices the open state change, however the dialog shows and hides:
     * display, the hidden attribute, or the node added and removed.
     *   open  — remember the opener (what had focus just before, never a
     *           text field: refocusing one pops the phone keyboard), then
     *           focus the dialog's close control unless its own code already
     *           put focus inside (the recycle confirm's type-DELETE box).
     *   close — hand focus back to the opener, unless the dialog's own close
     *           sent it somewhere live outside.
     * Side panels (.detail-overlay) keep their own code. A dialog already
     * open when watching starts is left alone. A script-moved focus shows a
     * ring only after a keyboard open (:focus-visible), as in #377.
     */
    var MODAL_SELECTOR = OVERLAY_SELECTOR.split(", ").filter(function (s) {
        return s !== ".detail-overlay";
    }).join(", ");
    var TEXT_FIELD = "input, textarea, select, [contenteditable]";

    function watchModals(doc, win) {
        if (!doc || !win || typeof win.MutationObserver !== "function") return null;
        var recent = [];          // the last few focused elements, newest last
        var lastBlur = null;      // { el, t }: the last focus lost to nothing
        var state = new Map();    // open dialog -> { opener }

        function onFocusIn(e) {
            recent.push(e.target);
            if (recent.length > 8) recent.shift();
        }

        function onFocusOut(e) {
            if (!e.relatedTarget) lastBlur = { el: e.target, t: Date.now() };
        }

        // A button that opens a dialog and is disabled while its request runs
        // (#429's withInflight: 💡 Auto-categorize, ✨ Plan) drops focus to the
        // page when disabled — before or after this watcher looks, depending
        // on timing. It's still the opener.
        function justDisabled() {
            if (!lastBlur || Date.now() - lastBlur.t > 1000) return null;
            var el = lastBlur.el;
            var busy = el.disabled === true || el.getAttribute("aria-busy") === "true";
            return busy ? okOpener(el) : null;
        }

        function isOpen(el) {
            if (!el.isConnected) return false;
            var cs = win.getComputedStyle(el);
            return cs.display !== "none" && cs.visibility !== "hidden";
        }

        function okOpener(c) {
            return c && c !== doc.body && c.isConnected && !c.matches(TEXT_FIELD) ? c : null;
        }

        function openerFor(el) {
            var active = doc.activeElement;
            // Focus is still where the open came from (or on the page body:
            // Safari doesn't focus a clicked button — then there's nothing to
            // hand back, rather than an old element the page would scroll to).
            if (!active || active === doc.body) return justDisabled();
            if (!el.contains(active)) return okOpener(active);
            // The dialog's own code already focused inside it: the opener is
            // what had focus just before. Newest first.
            for (var i = recent.length - 1; i >= 0; i--) {
                var c = recent[i];
                if (!c || !c.isConnected || el.contains(c)) continue;
                if (c === doc.body || c.matches(TEXT_FIELD)) return null;
                return c;
            }
            return null;
        }

        function onOpen(el) {
            state.set(el, { opener: openerFor(el) });
            if (el.contains(doc.activeElement)) return;
            var close = el.querySelector(CLOSE_SELECTOR);
            var target = close && isShown(close, el, win) ? close
                : focusablesIn(el, win)[0];
            if (target) target.focus();
        }

        function onClose(el, memo) {
            state.delete(el);
            var active = doc.activeElement;
            if (active && active !== doc.body && active.isConnected &&
                    !el.contains(active)) return;
            if (memo.opener && memo.opener.isConnected) memo.opener.focus();
            // Nothing to hand back (or it can't take focus): don't leave
            // focus on a hidden control.
            if (doc.activeElement && el.contains(doc.activeElement)) doc.activeElement.blur();
        }

        function sync() {
            var seen = new Set();
            Array.prototype.forEach.call(doc.querySelectorAll(MODAL_SELECTOR), function (el) {
                seen.add(el);
                var open = isOpen(el);
                if (open && !state.has(el)) onOpen(el);
                else if (!open && state.has(el)) onClose(el, state.get(el));
            });
            state.forEach(function (memo, el) {   // removed from the page
                if (!seen.has(el)) onClose(el, memo);
            });
        }

        doc.addEventListener("focusin", onFocusIn, true);
        doc.addEventListener("focusout", onFocusOut, true);
        // Dialogs open at the start are not "opened" by anyone: no focus move.
        Array.prototype.forEach.call(doc.querySelectorAll(MODAL_SELECTOR), function (el) {
            if (isOpen(el)) state.set(el, { opener: null });
        });
        var mo = new win.MutationObserver(sync);
        mo.observe(doc.documentElement, {
            subtree: true, childList: true, attributes: true,
            attributeFilter: ["style", "class", "hidden"],
        });
        return {
            sync: sync,
            disconnect: function () {
                mo.disconnect();
                doc.removeEventListener("focusin", onFocusIn, true);
                doc.removeEventListener("focusout", onFocusOut, true);
            },
        };
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
        anyOpen: anyOpen,
        makeOpener: makeOpener,     // #454
        opened: opened,             // #454
        closed: closed,             // #454
        afterRender: afterRender,   // #454
        watchModals: watchModals,   // #419
    };

    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    } else if (typeof window !== "undefined") {
        window.panelKeys = api;
        attachPanelKeys(document, window);
        watchModals(document, window);   // #419
    }
})();
