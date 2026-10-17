/**
 * #499: pure helpers for the /settings "Siri voice review" card.
 *
 * Dual export (CLAUDE.md anti-pattern #3): window.voiceTokenHelpers in
 * the browser, module.exports under Jest.
 */
(function () {
    "use strict";

    var JTI_RE = /^[0-9a-f]{16}$/;
    var DAY_CHOICES = [30, 90, 180, 365];
    var DEFAULT_DAYS = 90;

    // What goes in the Shortcut's Authorization header.
    function headerValue(token) {
        return "Bearer " + String(token || "").trim();
    }

    // A token id as `voice_action_token.new_jti()` makes it. Spaces and
    // capitals from a pasted "jti=…" line are forgiven.
    function normalizeJti(value) {
        var s = String(value == null ? "" : value).trim().toLowerCase();
        if (s.indexOf("jti=") === 0) s = s.slice(4).trim();
        return s;
    }

    function isValidJti(value) {
        return JTI_RE.test(normalizeJti(value));
    }

    // Only the lifetimes the card offers; anything else is the default.
    function clampDays(value) {
        var n = parseInt(value, 10);
        return DAY_CHOICES.indexOf(n) === -1 ? DEFAULT_DAYS : n;
    }

    function formatDay(iso) {
        if (!iso) return "?";
        var d = new Date(iso);
        if (isNaN(d.getTime())) return "?";
        return d.toLocaleDateString(undefined, {
            year: "numeric", month: "short", day: "numeric",
        });
    }

    // One list row's words: "Made Oct 17, 2026 · expires Jan 15, 2027"
    // and its state.
    function tokenRowLabel(row, now) {
        var expires = row && row.expires ? new Date(row.expires) : null;
        var at = now instanceof Date ? now : new Date();
        var state;
        if (row && row.revoked) state = "Revoked";
        else if (expires && !isNaN(expires.getTime()) && expires < at) state = "Expired";
        else state = "Active";
        return {
            dates: "Made " + formatDay(row && row.minted) +
                " · expires " + formatDay(row && row.expires),
            state: state,
            canRevoke: state === "Active",
        };
    }

    // Copy `text`. Resolves "copied" (on the clipboard), "selected" (the
    // field's text is selected — the user taps Copy in the iOS menu) or
    // "failed". navigator.clipboard first; when it is missing or refused
    // (older iOS, no secure context), select the field and try
    // execCommand("copy"). `env` = {navigator, document} for tests.
    function copyText(text, field, env) {
        var nav = env && env.navigator;
        var doc = env && env.document;
        function selectField() {
            if (!field) return false;
            try {
                if (field.focus) field.focus();
                if (field.select) field.select();
                if (field.setSelectionRange) field.setSelectionRange(0, String(text).length);
                return true;
            } catch (e) {
                return false;
            }
        }
        function fallback() {
            var selected = selectField();
            try {
                if (doc && doc.execCommand && doc.execCommand("copy")) return "copied";
            } catch (e) { /* fall through */ }
            return selected ? "selected" : "failed";
        }
        if (nav && nav.clipboard && typeof nav.clipboard.writeText === "function") {
            return Promise.resolve()
                .then(function () { return nav.clipboard.writeText(text); })
                .then(function () { return "copied"; }, fallback);
        }
        return Promise.resolve(fallback());
    }

    var api = {
        copyText: copyText,
        headerValue: headerValue,
        normalizeJti: normalizeJti,
        isValidJti: isValidJti,
        clampDays: clampDays,
        tokenRowLabel: tokenRowLabel,
        DAY_CHOICES: DAY_CHOICES,
        DEFAULT_DAYS: DEFAULT_DAYS,
    };
    if (typeof window !== "undefined") window.voiceTokenHelpers = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
