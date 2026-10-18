/**
 * #504: Copy buttons on the Help page (the Siri setup steps).
 *
 * A button with data-copy-for="<id>" copies the value of the read-only
 * field with that id, through voiceTokenHelpers.copyText (#499: clipboard
 * first, else it selects the field so iOS shows its own Copy menu), and
 * says on the button what happened. Dual export: window.docsCopy in the
 * browser, module.exports for Jest (tests/js/unit/docs_copy.test.js).
 */
(function () {
    "use strict";

    var RESET_MS = 2000;

    function copyResultLabel(result) {
        if (result === "copied") return "Copied";
        if (result === "selected") return "Selected — tap Copy";
        return "Couldn't copy";
    }

    // Wire every [data-copy-for] button under `doc`. Returns how many were
    // wired; a button whose field is missing is left alone.
    function wireCopyButtons(doc, helpers, env) {
        if (!doc || !helpers || typeof helpers.copyText !== "function") return 0;
        var wired = 0;
        Array.prototype.forEach.call(doc.querySelectorAll("[data-copy-for]"), function (btn) {
            var field = doc.getElementById(btn.getAttribute("data-copy-for"));
            if (!field) return;
            btn.addEventListener("click", function () {
                Promise.resolve(helpers.copyText(field.value, field, env)).then(function (result) {
                    btn.textContent = copyResultLabel(result);
                    setTimeout(function () { btn.textContent = "Copy"; }, RESET_MS);
                });
            });
            wired += 1;
        });
        return wired;
    }

    var api = { copyResultLabel: copyResultLabel, wireCopyButtons: wireCopyButtons };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    if (typeof window !== "undefined") {
        window.docsCopy = api;
        wireCopyButtons(document, window.voiceTokenHelpers,
            { navigator: navigator, document: document });
    }
})();
