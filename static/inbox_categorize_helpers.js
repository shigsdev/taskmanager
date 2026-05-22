/**
 * Pure helpers for the Auto-categorize Inbox review modal — due-date
 * derivation + apply-payload policy.
 *
 * Bug this exists to fix (user-reported 2026-05-22, BACKLOG #208):
 * the app has a server-side "tier → due_date auto-fill" feature
 * (`_auto_fill_tier_due_date` in task_service.py) — a task landing in
 * TODAY/TOMORROW with no due_date gets one stamped automatically. But
 * that auto-fill is suppressed when the PATCH payload *mentions*
 * `due_date` at all (`if "due_date" in data: return`). The
 * auto-categorize Apply path always sent `due_date: null`, so every
 * auto-categorized TODAY task landed with NO due date — the "auto
 * date logic" never ran for this flow.
 *
 * These helpers let the modal (a) show the date the server WOULD fill
 * so the user sees it before applying, and (b) decide when to OMIT
 * `due_date` from the PATCH so the server auto-fill is allowed to run.
 *
 * Pure by construction: every function takes `todayISO` as a string
 * argument rather than calling `new Date()` — so Jest can pin a date
 * (anti-pattern #3: exercise the logic, don't string-match source).
 *
 * Dual-export per CLAUDE.md anti-pattern #3:
 *   Browser: window.inboxCategorizeHelpers
 *   Node (Jest): module.exports
 */
"use strict";

/**
 * Add `days` to an ISO "YYYY-MM-DD" date string, returning ISO.
 * Parsed as UTC so the arithmetic never drifts across a DST boundary.
 */
function addDaysIso(iso, days) {
    var parts = String(iso).split("-");
    var d = new Date(Date.UTC(
        Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]),
    ));
    d.setUTCDate(d.getUTCDate() + days);
    return (
        d.getUTCFullYear()
        + "-"
        + String(d.getUTCMonth() + 1).padStart(2, "0")
        + "-"
        + String(d.getUTCDate()).padStart(2, "0")
    );
}

/**
 * The due_date the server's tier→date auto-fill would produce for a
 * given tier. Mirrors `_auto_fill_tier_due_date` in task_service.py:
 * ONLY today and tomorrow auto-fill — every other tier returns null.
 *
 * @param {string} tier — a tier value ("today", "tomorrow", ...).
 * @param {string} todayISO — today as "YYYY-MM-DD".
 * @returns {string|null} ISO date string, or null when the tier has
 *   no auto-fill.
 */
function dueDateForTier(tier, todayISO) {
    if (tier === "today") { return todayISO; }
    if (tier === "tomorrow") { return addDaysIso(todayISO, 1); }
    return null;
}

/**
 * Decide what a row's due-date input should show, and whether that
 * value is an auto-derived placeholder.
 *
 * An explicit value (a date Claude suggested, or one the user typed)
 * always wins and is NOT auto. Otherwise the value is derived from
 * the tier and flagged auto so the apply path knows to omit it.
 *
 * @param {string|null} explicitValue — a non-derived date already on
 *   the row (Claude's suggestion or the user's typed value), or
 *   ""/null when there is none.
 * @param {string} tier — the row's current tier.
 * @param {string} todayISO — today as "YYYY-MM-DD".
 * @returns {{value: string, auto: boolean}}
 */
function resolveDueForTier(explicitValue, tier, todayISO) {
    if (explicitValue) {
        return { value: explicitValue, auto: false };
    }
    var derived = dueDateForTier(tier, todayISO);
    return { value: derived || "", auto: derived !== null };
}

/**
 * Apply-payload policy: send `due_date` in the PATCH ONLY when it is a
 * real explicit value. An empty field OR an auto-derived placeholder
 * is omitted — so the server's tier→date auto-fill runs and stamps
 * the authoritative date. Sending `due_date: null` would suppress it.
 *
 * @param {string} value — the due input's current value ("" if empty).
 * @param {boolean} auto — true when `value` is an auto-derived placeholder.
 * @returns {boolean} true → include due_date in the payload.
 */
function shouldSendDue(value, auto) {
    return Boolean(value) && !auto;
}

var _api = {
    addDaysIso: addDaysIso,
    dueDateForTier: dueDateForTier,
    resolveDueForTier: resolveDueForTier,
    shouldSendDue: shouldSendDue,
};

if (typeof module !== "undefined" && module.exports) {
    module.exports = _api;
} else if (typeof window !== "undefined") {
    window.inboxCategorizeHelpers = _api;
}
