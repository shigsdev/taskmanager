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

    /**
     * #457: where ↑ / ↓ / Home / End move focus in a menu of `count` items
     * from index `current` (-1 = none yet). Wraps at both ends. Null for any
     * other key.
     */
    function menuKeyTarget(count, current, key) {
        if (!count) return null;
        if (key === "Home") return 0;
        if (key === "End") return count - 1;
        if (key === "ArrowDown") return current < 0 ? 0 : (current + 1) % count;
        if (key === "ArrowUp") return current < 0 ? count - 1 : (current - 1 + count) % count;
        return null;
    }

    /**
     * #457: keyboard and screen-reader behaviour for a popup the page has
     * just put on screen. The opener gets aria-haspopup + aria-expanded.
     *   kind "menu" (a list of choices): role=menu / menuitem, focus goes
     *     to the first item, ↑ ↓ Home End move between items.
     *   kind "dialog" (a small form, e.g. Pick a date…): focus is the
     *     caller's business; no arrow keys.
     * Both: Escape closes it and puts focus back on the opener; Tab out of
     * it closes it. The page's own outside-click close still applies — it
     * should call the returned close() (or just remove the element; a
     * removed popup cleans up on its next key).
     * Returns { close }. Escape is consumed, so panel_keys' document
     * handler (#381) doesn't also close the panel underneath.
     */
    function attachMenu(anchor, menu, opts) {
        var kind = (opts && opts.kind) || "menu";
        var items = function () {
            return Array.prototype.slice.call(menu.querySelectorAll("button:not([disabled])"));
        };
        if (anchor) {
            anchor.setAttribute("aria-haspopup", kind === "menu" ? "menu" : "dialog");
            anchor.setAttribute("aria-expanded", "true");
        }
        if (kind === "menu") {
            menu.setAttribute("role", "menu");
            items().forEach(function (b) {
                b.setAttribute("role", "menuitem");
                b.tabIndex = -1;
            });
        } else {
            menu.setAttribute("role", "dialog");
        }

        var closedAlready = false;
        function close(returnFocus) {
            if (closedAlready) return;
            closedAlready = true;
            menu.removeEventListener("keydown", onKey);
            if (menu.isConnected) menu.remove();
            if (anchor) {
                anchor.setAttribute("aria-expanded", "false");
                if (returnFocus && anchor.isConnected) anchor.focus();
            }
        }
        function onKey(e) {
            if (e.key === "Escape") {
                e.preventDefault();
                e.stopPropagation();
                close(true);
                return;
            }
            if (e.key === "Tab") {
                // Let focus move on, but don't leave an open menu behind.
                close(false);
                return;
            }
            if (kind !== "menu") return;
            var list = items();
            var next = menuKeyTarget(list.length, list.indexOf(e.target), e.key);
            if (next === null) return;
            e.preventDefault();
            list[next].focus();
        }
        menu.addEventListener("keydown", onKey);
        if (kind === "menu") {
            var first = items()[0];
            if (first) first.focus();
        }
        return { close: close };
    }

    /**
     * #458: the key rule for a typeahead list under a text box (the task
     * panel's parent picker). With the list open and not empty: ↓ / ↑ move
     * the highlight (wrapping, as menuKeyTarget), Enter picks the highlighted
     * match ({pick}), Escape closes the list ({close}). Anything else — and
     * every key while the list is closed — is null, so typing reaches the box
     * and Escape reaches the panel underneath.
     */
    function comboKey(count, current, key, open) {
        if (!open || !count) return null;
        if (key === "Escape") return { close: true };
        if (key === "Enter") return current >= 0 && current < count ? { pick: current } : null;
        if (key === "ArrowDown" || key === "ArrowUp") {
            return { move: menuKeyTarget(count, current, key) };
        }
        return null;
    }

    var api = {
        placeMenu: placeMenu, menuKeyTarget: menuKeyTarget, attachMenu: attachMenu,
        comboKey: comboKey,
    };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    if (typeof window !== "undefined") window.menuHelpers = api;
})();
