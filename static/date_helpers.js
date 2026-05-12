/**
 * Pure date helpers — the LOCAL "YYYY-MM-DD" version of a Date.
 *
 * Bug class this exists to prevent (user-reported 2026-05-11): code
 * that wants today's date as a string keeps reaching for
 * ``new Date().toISOString().slice(0, 10)``, which is UTC, not local.
 * In late-evening negative-offset zones (e.g. 8 PM EDT = 00:18 UTC
 * next day), the UTC slice rolls a day early and comparisons like
 * ``task.due_date < today`` trip on tasks due today locally.
 *
 * The fix: always compute from the Date's local component getters
 * (getFullYear / getMonth / getDate), padded to 2 digits.
 *
 * Dual-export per CLAUDE.md anti-pattern #3:
 *   Browser: window.dateHelpers
 *   Node (Jest): module.exports
 */
"use strict";

/**
 * Return the local "YYYY-MM-DD" representation of a Date instance.
 *
 * @param {Date} [d] — defaults to `new Date()` (now).
 * @returns {string} e.g. "2026-05-11"
 */
function localIsoDate(d) {
    const date = d instanceof Date ? d : new Date();
    return (
        date.getFullYear()
        + "-"
        + String(date.getMonth() + 1).padStart(2, "0")
        + "-"
        + String(date.getDate()).padStart(2, "0")
    );
}

/**
 * Compare two ISO date strings ("YYYY-MM-DD") as dates. Returns
 * -1 / 0 / 1. Pure string compare works because the format is
 * left-padded — but wrap it so callers' intent is clear and so the
 * helper is easy to grep.
 */
function compareIsoDates(a, b) {
    if (typeof a !== "string" || typeof b !== "string") {
        throw new Error("compareIsoDates requires two ISO strings");
    }
    if (a < b) return -1;
    if (a > b) return 1;
    return 0;
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = { localIsoDate, compareIsoDates };
} else if (typeof window !== "undefined") {
    window.dateHelpers = { localIsoDate, compareIsoDates };
}
