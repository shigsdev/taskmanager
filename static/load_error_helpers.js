/**
 * #440: one way to say "this didn't load" — with a Retry — instead of a
 * blank page, "Loading…" forever, or an empty state that reads like
 * real data ("All caught up", "0").
 *
 *   loadErrorText(what, err) → "Couldn't load your goals." (+ the
 *       server's reason when apiFetch hasn't already told the user)
 *   showLoadError(container, what, err, onRetry) → replaces the
 *       container's contents with the message and a Retry button that
 *       calls onRetry (if given). Returns the element it added.
 *   clearLoadError(container) → removes a message added above.
 *
 * Exports (dual pattern, like the other static helpers):
 *   Browser: window.loadErrorHelpers
 *   Node:    module.exports  (tests/js/unit/load_error_helpers.test.js)
 */
(function () {
    "use strict";

    function loadErrorText(what, err) {
        var text = "Couldn't load " + (what || "this") + ".";
        // apiFetch has already asked the user to reload (network failure,
        // signed out) — don't repeat its words, just say what's missing.
        if (err && !err.userNotified && err.message) {
            text += " " + String(err.message).replace(/\.$/, "") + ".";
        }
        return text;
    }

    function showLoadError(container, what, err, onRetry) {
        if (!container) return null;
        var box = document.createElement("div");
        box.className = "load-error";
        box.setAttribute("role", "alert");
        var p = document.createElement("p");
        p.className = "load-error-text";
        p.textContent = loadErrorText(what, err);
        box.appendChild(p);
        if (typeof onRetry === "function") {
            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "btn btn-sm load-error-retry";
            btn.textContent = "Retry";
            btn.addEventListener("click", function () {
                btn.disabled = true;
                btn.textContent = "Retrying…";
                onRetry();
            });
            box.appendChild(btn);
        }
        container.innerHTML = "";
        container.appendChild(box);
        return box;
    }

    function clearLoadError(container) {
        if (!container) return;
        var box = container.querySelector(":scope > .load-error");
        if (box) box.remove();
    }

    var api = {
        loadErrorText: loadErrorText,
        showLoadError: showLoadError,
        clearLoadError: clearLoadError,
    };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    if (typeof window !== "undefined") window.loadErrorHelpers = api;
})();
