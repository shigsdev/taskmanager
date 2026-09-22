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

/**
 * blankRecurringDraft — field values for a brand-new template (#323).
 *
 * The same editor panel serves edit and create, so "new" needs an
 * explicit blank shape rather than whatever the last-opened template
 * left behind. Frequency-specific defaults follow the capture-bar hint
 * convention already documented on /docs: a fresh template matches
 * TODAY's weekday / day-of-month, so picking "Weekly" without touching
 * the day picker gives you "weekly on today's weekday".
 *
 * `today` is injected so this is deterministic under test; production
 * callers pass nothing and get the real clock.
 *
 * NOTE the weekday conversion: JS `getDay()` is 0=Sunday, but this app
 * stores 0=Monday (Python's `weekday()` convention — see the
 * recurring_service module docstring). Off-by-one here would silently
 * schedule every new weekly template one day early.
 */
function blankRecurringDraft(today) {
    const d = today instanceof Date ? today : new Date();
    return {
        title: "",
        frequency: "daily",
        type: "work",
        projectId: "",
        goalId: "",
        url: "",
        notes: "",
        endDate: "",
        dayOfWeek: (d.getDay() + 6) % 7,  // Sun=0 -> Mon=0
        daysOfWeek: [],
        dayOfMonth: d.getDate(),
        weekOfMonth: 1,
    };
}

/**
 * recurringSubmitTarget — where the editor form posts (#323).
 *
 * One form, two verbs: a template being edited PATCHes its own URL, a
 * new one POSTs the collection. Keeping the branch here (rather than
 * inline in the submit handler) means the create/edit split is covered
 * by a real logic test instead of a string-match — CLAUDE.md
 * anti-pattern #3. A blank/missing id is always "create"; anything
 * else edits that id.
 */
function recurringSubmitTarget(editId) {
    const id = typeof editId === "string" ? editId.trim() : editId;
    if (!id) return { method: "POST", url: "/api/recurring" };
    return { method: "PATCH", url: "/api/recurring/" + id };
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        buildRecurringEditPayload,
        blankRecurringDraft,
        recurringSubmitTarget,
    };
} else if (typeof window !== "undefined") {
    window.recurringHelpers = {
        buildRecurringEditPayload,
        blankRecurringDraft,
        recurringSubmitTarget,
    };
}
