/**
 * Pure helpers for filtering goals by task type (#142).
 *
 * Mirrors the project-side type-filter pattern (#98). Goal.category is
 * 5-valued (work, bau, health, relationships, personal_growth) but
 * Task.type is 2-valued (work, personal) — so we need a category→type
 * mapping. Backlog spec locked-in 2026-05-09: STRICT bipartition (A).
 *
 *   work + bau                                 → work-side
 *   health + relationships + personal_growth   → personal-side
 *
 * Dual-export per CLAUDE.md anti-pattern #3:
 *   Browser: window.goalFilterHelpers
 *   Node (Jest): module.exports
 */
"use strict";

// Locked 2026-05-09 per backlog #142 (option A — strict bipartition).
const _CATEGORY_TO_TYPE = Object.freeze({
    work: "work",
    bau: "work",
    health: "personal",
    relationships: "personal",
    personal_growth: "personal",
});

/**
 * Return the bucketed type for a goal category. Unknown categories
 * default to "personal" (safer — won't accidentally surface in a
 * Work view) AND we log a warning so a future enum addition that
 * wasn't taught to this map is visible.
 */
function typeForCategory(category) {
    if (typeof category !== "string") return "personal";
    const t = _CATEGORY_TO_TYPE[category];
    if (t === undefined) {
        // Visible in browser console + Jest test output.
        if (typeof console !== "undefined" && console.warn) {
            console.warn(
                "goal_filter_helpers: unknown category " + JSON.stringify(category)
                + " — defaulting to personal-side. Update _CATEGORY_TO_TYPE."
            );
        }
        return "personal";
    }
    return t;
}

/**
 * Filter a list of goals by task type. Returns the goals that
 * belong on the side of the requested type per the strict mapping.
 *
 * @param {Array<{category: string}>} goals  All available goals.
 * @param {string|null|undefined} filterType  "work" / "personal" /
 *     falsy. When falsy, returns all goals unfiltered (matches the
 *     existing project-side behavior).
 */
function filterGoalsByType(goals, filterType) {
    if (!filterType) return Array.isArray(goals) ? goals.slice() : [];
    if (!Array.isArray(goals)) return [];
    return goals.filter((g) => typeForCategory(g.category) === filterType);
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = { typeForCategory, filterGoalsByType };
} else if (typeof window !== "undefined") {
    window.goalFilterHelpers = { typeForCategory, filterGoalsByType };
}
