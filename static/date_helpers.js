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

/**
 * Convert a server timestamp string to its LOCAL "YYYY-MM-DD".
 *
 * The backend serializes naive UTC timestamps (created_at / updated_at)
 * via isoformat() with NO timezone suffix (e.g. "2026-06-22T00:23:30").
 * Naively slicing the first 10 chars compares a UTC date against a local
 * "today" — the #181/#240 drift class (near the UTC/local boundary the
 * UTC date is already tomorrow). So: treat a suffix-less value as UTC
 * (append "Z"), parse, then read the LOCAL calendar date.
 *
 * @param {string} s — ISO timestamp; an explicit "Z"/"+hh:mm" suffix is
 *   respected, otherwise the value is assumed UTC.
 * @returns {string|null} local "YYYY-MM-DD", or null if unparseable.
 */
function utcIsoToLocalDate(s) {
    const d = parseServerTimestamp(s);
    return d ? localIsoDate(d) : null;
}

/**
 * #444: a server timestamp as a Date. Zone-less values are UTC (see
 * utcIsoToLocalDate); `new Date(s)` alone reads them as LOCAL time, which
 * put the task panel's "Created / Updated" a day off near midnight.
 *
 * @param {string} s — ISO timestamp, with or without a zone suffix.
 * @returns {Date|null} null if empty or unparseable.
 */
function parseServerTimestamp(s) {
    if (typeof s !== "string" || !s) return null;
    const hasTz = /[zZ]$|[+-]\d\d:?\d\d$/.test(s);
    const d = new Date(hasTz ? s : s + "Z");
    return isNaN(d.getTime()) ? null : d;
}

/**
 * #424: the local date N calendar days after `d` (N may be negative), at
 * local midnight. Never add N × 86400000 ms instead: across a daylight-
 * saving change a day is 23 or 25 hours, so on 2026-11-01 midnight + 24 h
 * is 23:00 the SAME date. Building from (year, month, day + n) lets the
 * Date do the calendar arithmetic (the #345 calendar.js fix).
 *
 * @param {Date} d
 * @param {number} n
 * @returns {Date} a new Date; `d` is not modified.
 */
function addDays(d, n) {
    return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = { localIsoDate, compareIsoDates, utcIsoToLocalDate, addDays, parseServerTimestamp };
} else if (typeof window !== "undefined") {
    window.dateHelpers = { localIsoDate, compareIsoDates, utcIsoToLocalDate, addDays, parseServerTimestamp };
}
