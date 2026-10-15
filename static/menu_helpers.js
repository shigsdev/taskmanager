/**
 * #487: where a popup menu goes so it stays on screen.
 *
 *   placeMenu(anchor, menu, viewport, opts) → { left, top, maxHeight }
 *     anchor   — the opener's getBoundingClientRect() ({left, top, bottom})
 *     menu     — the menu's size ({width, height})
 *     viewport — {width, height} (window.innerWidth / innerHeight)
 *     opts     — {margin = 8, gap = 4}: distance kept from the screen edges,
 *                and between the opener and the menu
 *   Coordinates are the viewport's, for a `position: fixed` menu.
 *
 * Below the opener when the menu fits there; otherwise above when it fits
 * there; otherwise the side with more room, with maxHeight set to that room
 * so the menu scrolls instead of running off the screen (maxHeight is null
 * when the whole menu fits). Left starts at the opener's left and is kept
 * `margin` inside both edges.
 *
 * /projects' bulk menus always opened under their button, which sits in
 * the bottom toolbar, so they opened below the screen. This is the
 * placement half of the shared menu helper #457 asks for.
 *
 * Exports (dual pattern, like the other static helpers):
 *   Browser: window.menuHelpers
 *   Node:    module.exports  (tests/js/unit/menu_helpers.test.js)
 */
(function () {
    "use strict";

    function placeMenu(anchor, menu, viewport, opts) {
        var margin = opts && opts.margin != null ? opts.margin : 8;
        var gap = opts && opts.gap != null ? opts.gap : 4;

        var roomBelow = viewport.height - anchor.bottom - gap - margin;
        var roomAbove = anchor.top - gap - margin;
        var top;
        var maxHeight = null;
        if (menu.height <= roomBelow) {
            top = anchor.bottom + gap;
        } else if (menu.height <= roomAbove) {
            top = anchor.top - gap - menu.height;
        } else if (roomAbove > roomBelow) {
            maxHeight = Math.max(0, roomAbove);
            top = anchor.top - gap - maxHeight;
        } else {
            maxHeight = Math.max(0, roomBelow);
            top = anchor.bottom + gap;
        }

        var left = Math.min(anchor.left, viewport.width - menu.width - margin);
        if (left < margin) left = margin;

        return { left: left, top: top, maxHeight: maxHeight };
    }

    var api = { placeMenu: placeMenu };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    if (typeof window !== "undefined") window.menuHelpers = api;
})();
