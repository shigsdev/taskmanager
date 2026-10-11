/**
 * #418: tie an async answer to the request that asked for it.
 *
 * A pop-up that is reused for every request (the board's ✨ Plan review is
 * one shared dialog) can be closed and reopened while a request is still in
 * flight. Without a check, the older answer lands in the newer dialog.
 *
 * Usage:
 *   var guard = createRequestGuard();
 *   var mine = guard.begin();          // on open: supersedes any older one
 *   var result = await fetchSomething();
 *   if (!guard.isCurrent(mine)) return; // closed or replaced meanwhile
 *   guard.cancel();                    // on close: drop whatever is in flight
 *
 * Exports (dual pattern, like the other static helpers):
 *   Browser: window.requestGuardHelpers
 *   Node:    module.exports  (tests/js/unit/request_guard_helpers.test.js)
 */
(function () {
    "use strict";

    function createRequestGuard() {
        var latest = 0;   // last token handed out
        var live = 0;     // the one current token; 0 = none

        return {
            begin: function () {
                latest += 1;
                live = latest;
                return live;
            },
            isCurrent: function (token) {
                return live !== 0 && token === live;
            },
            cancel: function () {
                live = 0;
            },
        };
    }

    var api = { createRequestGuard: createRequestGuard };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    if (typeof window !== "undefined") window.requestGuardHelpers = api;
})();
