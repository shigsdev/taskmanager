/**
 * reload_guard_helpers.js — #473: what a deploy reload would throw away.
 *
 * base.html polls for a new service worker and applies it (the page
 * reloads) unless userIsBusy() objects. #446 made every open panel and
 * pop-up count; the /scan, /import, /plan and /reflection reviews are part
 * of the page, not an overlay, and each cost a paid call. They register
 * here instead:
 *
 *   reloadGuard.add(fn)       fn() is true while something on screen
 *                             would be lost (a review not yet saved)
 *   reloadGuard.during(p)     busy until promise p settles, either way —
 *                             wrap a paid request in flight
 *   reloadGuard.busy()        any request in flight, or any check true
 *
 * A check that throws is skipped: a broken page must never stop updates
 * for good. The "Update available" bar still shows while busy.
 *
 * Loaded in base.html's head, before page scripts.
 *   Browser: window.reloadGuard (the page's one guard),
 *            window.reloadGuardHelpers.createReloadGuard
 *   Node:    module.exports (tests/js/unit/reload_guard_helpers.test.js)
 */
(function () {
    "use strict";

    function createReloadGuard() {
        var checks = [];
        var inFlight = 0;

        return {
            add: function (fn) {
                if (typeof fn === "function") checks.push(fn);
            },
            during: function (promise) {
                inFlight += 1;
                var done = function () { inFlight -= 1; };
                return Promise.resolve(promise).then(
                    function (v) { done(); return v; },
                    function (e) { done(); throw e; }
                );
            },
            busy: function () {
                if (inFlight > 0) return true;
                for (var i = 0; i < checks.length; i++) {
                    try {
                        if (checks[i]()) return true;
                    } catch (e) { /* skip a broken check */ }
                }
                return false;
            },
        };
    }

    var api = { createReloadGuard: createReloadGuard };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    if (typeof window !== "undefined") {
        window.reloadGuardHelpers = api;
        window.reloadGuard = createReloadGuard();
    }
})();
