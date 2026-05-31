/**
 * Pure helpers for the /recurring per-template editor (#266).
 *
 * buildRecurringEditPayload shapes the PATCH body for
 * /api/recurring/<id> from the editor's raw field values. The
 * frequency branching + "clear the other frequency-specific fields"
 * behaviour is the non-trivial part (a frequency change must NOT carry
 * the previous shape's day_of_week / days_of_week / etc.), so it lives
 * here behind the dual-export pattern and is Jest-tested — per CLAUDE.md
 * anti-pattern #3 (don't ship branchy client logic without a real logic
 * test).
 *
 *   Browser: window.recurringHelpers
 *   Node (Jest): module.exports
 */
"use strict";

/**
 * @param {object} v  Raw editor values:
 *   {title, frequency, type, projectId, goalId, url, notes, endDate,
 *    dayOfWeek, daysOfWeek, dayOfMonth, weekOfMonth}
 * @returns {object} The PATCH payload. All four frequency-specific
 *   fields are always present (null unless relevant to `frequency`), so
 *   switching frequency clears the stale shape on the server.
 */
function buildRecurringEditPayload(v) {
    v = v || {};
    const payload = {
        title: (v.title || "").trim(),
        frequency: v.frequency,
        type: v.type,
        project_id: v.projectId || null,
        goal_id: v.goalId || null,
        url: (v.url || "").trim() || null,
        notes: (v.notes || "").trim() || null,
        end_date: v.endDate || null,
        // Always send all four as null, then set the one(s) the chosen
        // frequency needs — so a frequency change can't leave a stale
        // day_of_week / days_of_week / day_of_month / week_of_month behind.
        day_of_week: null,
        days_of_week: null,
        day_of_month: null,
        week_of_month: null,
    };
    if (v.frequency === "weekly") {
        payload.day_of_week = v.dayOfWeek;
    } else if (v.frequency === "multi_day_of_week") {
        payload.days_of_week = Array.isArray(v.daysOfWeek) ? v.daysOfWeek : [];
    } else if (v.frequency === "monthly_date") {
        payload.day_of_month = v.dayOfMonth;
    } else if (v.frequency === "monthly_nth_weekday") {
        payload.week_of_month = v.weekOfMonth;
        payload.day_of_week = v.dayOfWeek;
    }
    // daily / weekdays need none of the frequency-specific fields.
    return payload;
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = { buildRecurringEditPayload };
} else if (typeof window !== "undefined") {
    window.recurringHelpers = { buildRecurringEditPayload };
}
