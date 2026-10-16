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

/**
 * recurringPausedLabel — the PAUSED marker on a /recurring row (#363).
 *
 * "" for an active template. A template an archive paused names which
 * archive, so the user can tell it apart from one they paused themselves
 * (unarchiving brings only the archive-paused ones back).
 */
function recurringPausedLabel(rt) {
    if (!rt || rt.is_active) return "";
    const proj = !!rt.paused_by_project_archive;
    const goal = !!rt.paused_by_goal_archive;
    if (proj && goal) return "PAUSED — project and goal archived";
    if (proj) return "PAUSED — project archived";
    if (goal) return "PAUSED — goal archived";
    return "PAUSED";
}

/**
 * #460: the one human label for a repeat rule — the board card badge, the
 * recurring previews, the /recurring list and a voice memo row all use it
 * (each had its own map and showed raw values or nothing for some
 * frequencies). Names follow the Repeat dropdown.
 *
 * @param {object} repeat  {frequency, day_of_week (0 = Mon), days_of_week,
 *   day_of_month, week_of_month (1-4)}; previews carry only frequency.
 * @param {object} [opts]  {short: true} → just the kind ("Weekly",
 *   "Monthly"), for a badge.
 * @returns {string} e.g. "Weekly on Mon", "Monthly on the 2nd Tue";
 *   "Repeats" for an unknown frequency.
 */
const _REPEAT_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function _repeatOrdinal(n) {
    const tens = n % 100;
    if (tens >= 11 && tens <= 13) return n + "th";
    return n + ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th");
}

function repeatLabel(repeat, opts) {
    const r = repeat || {};
    const short = !!(opts && opts.short);
    const day = (i) => (Number.isInteger(i) ? _REPEAT_DAYS[i] : undefined);
    switch (r.frequency) {
        case "daily": return "Daily";
        case "weekdays": return "Weekdays";
        case "weekly":
        case "day_of_week": {
            const d = day(r.day_of_week);
            return !short && d ? "Weekly on " + d : "Weekly";
        }
        case "multi_day_of_week": {
            const ds = (r.days_of_week || []).map(day).filter(Boolean);
            return !short && ds.length ? "Weekly on " + ds.join(", ") : "Specific weekdays";
        }
        case "monthly_date": {
            if (short) return "Monthly";
            const n = r.day_of_month;
            return Number.isInteger(n) && n >= 1 && n <= 31
                ? "Monthly on the " + _repeatOrdinal(n) : "Monthly (same date)";
        }
        case "monthly_nth_weekday": {
            if (short) return "Monthly";
            const w = r.week_of_month;
            const d = day(r.day_of_week);
            return Number.isInteger(w) && w >= 1 && w <= 4 && d
                ? "Monthly on the " + _repeatOrdinal(w) + " " + d : "Monthly (nth weekday)";
        }
        default: return "Repeats";
    }
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        buildRecurringEditPayload,
        blankRecurringDraft,
        recurringSubmitTarget,
        recurringPausedLabel,
        repeatLabel,
    };
} else if (typeof window !== "undefined") {
    window.recurringHelpers = {
        buildRecurringEditPayload,
        blankRecurringDraft,
        recurringSubmitTarget,
        recurringPausedLabel,
        repeatLabel,
    };
}
