/**
 * tier_helpers.js — pure date↔tier conversion utilities.
 *
 * Mirrors the server's task_service._tier_for_due_date (#74) so the
 * client-side detail-panel sync (#149) can preview the tier the
 * server WOULD pick for a given due_date — without round-tripping
 * to the API.
 *
 * Pulled out of app.js so Jest can exercise the boundary cases
 * (Mon-Sat boundaries, Sunday-today edge, today/tomorrow shortcuts)
 * without spinning up a DOM. Per CLAUDE.md anti-pattern #3:
 * non-trivial logic must be unit-testable; a Playwright assertion
 * on the rendered tier dropdown isn't substitute for the helper's
 * own boundary tests.
 *
 * Dual export pattern (matches filter_helpers / parse_capture):
 *   Browser: window.tierHelpers
 *   Node (Jest): module.exports
 */
"use strict";

const _MS_PER_DAY = 86400000;

/**
 * Strip time-of-day from a Date so date-equality comparisons work
 * regardless of when the input was constructed.
 */
function _atMidnight(d) {
    const out = new Date(d.getTime());
    out.setHours(0, 0, 0, 0);
    return out;
}

/**
 * Mon=0..Sun=6 — same convention as Python's date.weekday(). The
 * server uses this; we mirror exactly so the boundary math agrees.
 */
function _mondayWeekday(d) {
    return (d.getDay() + 6) % 7;
}

/**
 * Pick the natural tier for a given due_date relative to "today",
 * mirroring `task_service._tier_for_due_date`.
 *
 *   today               → "today"
 *   tomorrow            → "tomorrow"
 *   within this Mon-Sat → "this_week"
 *   within next Mon-Sat → "next_week"
 *   anything later      → "backlog"
 *
 * Sunday handling: a Sunday "today" maps THIS week to the just-
 * ended Mon-Sat (so a Sat date from "yesterday" still counts as
 * this_week). NEXT week is then the upcoming Mon-Sat.
 *
 * @param {Date|string} dueDate ISO string `YYYY-MM-DD` or Date
 * @param {Date} [todayOverride] for testing only
 * @returns {"today"|"tomorrow"|"this_week"|"next_week"|"backlog"|null}
 *          null when input can't be parsed.
 */
function tierForDueDate(dueDate, todayOverride) {
    if (!dueDate) return null;
    let due;
    if (dueDate instanceof Date) {
        due = _atMidnight(dueDate);
    } else if (typeof dueDate === "string") {
        // Build the date in LOCAL time (not UTC) — `new Date("2026-05-05")`
        // parses as UTC midnight which becomes "the day before" in
        // negative-offset zones, breaking equality with local "today".
        const m = dueDate.match(/^(\d{4})-(\d{2})-(\d{2})/);
        if (!m) return null;
        due = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 0, 0, 0, 0);
    } else {
        return null;
    }
    if (Number.isNaN(due.getTime())) return null;

    const today = todayOverride ? _atMidnight(todayOverride) : _atMidnight(new Date());
    const tomorrow = new Date(today.getTime() + _MS_PER_DAY);
    if (due.getTime() === today.getTime()) return "today";
    if (due.getTime() === tomorrow.getTime()) return "tomorrow";

    const daysSinceMonday = _mondayWeekday(today);
    const thisMonday = new Date(today.getTime() - daysSinceMonday * _MS_PER_DAY);
    const thisSaturday = new Date(thisMonday.getTime() + 5 * _MS_PER_DAY);
    const nextMonday = new Date(thisMonday.getTime() + 7 * _MS_PER_DAY);
    const nextSaturday = new Date(thisMonday.getTime() + 12 * _MS_PER_DAY);

    if (due.getTime() >= thisMonday.getTime() && due.getTime() <= thisSaturday.getTime()) {
        return "this_week";
    }
    if (due.getTime() >= nextMonday.getTime() && due.getTime() <= nextSaturday.getTime()) {
        return "next_week";
    }
    return "backlog";
}

/**
 * The inverse: pick a default `due_date` for tier=today/tomorrow.
 * Mirrors `task_service._auto_fill_tier_due_date` — only TODAY and
 * TOMORROW have a single canonical date. THIS_WEEK / NEXT_WEEK span
 * 6 days, FREEZER / BACKLOG / INBOX are date-agnostic.
 *
 * @param {string} tier
 * @param {Date} [todayOverride]
 * @returns {string|null} ISO YYYY-MM-DD, or null when the tier
 *          doesn't have a canonical date.
 */
function dueDateForTier(tier, todayOverride) {
    if (tier !== "today" && tier !== "tomorrow") return null;
    const today = todayOverride ? _atMidnight(todayOverride) : _atMidnight(new Date());
    const target = tier === "today" ? today : new Date(today.getTime() + _MS_PER_DAY);
    const yyyy = target.getFullYear();
    const mm = String(target.getMonth() + 1).padStart(2, "0");
    const dd = String(target.getDate()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd}`;
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        tierForDueDate: tierForDueDate,
        dueDateForTier: dueDateForTier,
    };
} else if (typeof window !== "undefined") {
    window.tierHelpers = {
        tierForDueDate: tierForDueDate,
        dueDateForTier: dueDateForTier,
    };
}
