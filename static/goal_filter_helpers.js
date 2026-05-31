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

/**
 * The set of goals to render in the detail-panel goal dropdown (#272).
 *
 * Returns the type-scoped goals (the #142 strict bipartition for
 * discovery) UNION any goals whose id is in `keepIds` — used to ALWAYS
 * surface the selected project's linked goal and the task's current
 * goal, even when they sit on the OTHER side of the bipartition.
 *
 * Why: a project may legitimately link to a cross-side goal — e.g. the
 * *personal* project "AI Training" points at the *work*-category goal
 * "AI Upskilling". Under the strict type filter alone that goal is
 * invisible on a Personal task, so it neither appears in the dropdown
 * nor auto-fills via the project→goal cascade (the cascade checks the
 * rendered options and finds it absent). Keeping such linked/current
 * goals in the list fixes both symptoms without widening the scope for
 * the common case (the bulk of the list stays relevance-scoped).
 *
 * Order is stable: goals are returned in their original `goals` order,
 * naturally de-duped (a goal that's both in-scope and a keepId appears
 * once). When `filterType` is falsy every goal is in-scope, so keepIds
 * is a no-op and all goals are returned (matches filterGoalsByType).
 *
 * @param {Array<{id: string, category: string}>} goals  All goals.
 * @param {string|null|undefined} filterType  "work"/"personal"/falsy.
 * @param {Set<string>|Array<string>|null} keepIds  Goal ids to always
 *     include regardless of the type filter.
 */
function goalsForDropdown(goals, filterType, keepIds) {
    if (!Array.isArray(goals)) return [];
    const keep = keepIds instanceof Set
        ? keepIds
        : new Set(Array.isArray(keepIds) ? keepIds : []);
    const inScope = new Set(filterGoalsByType(goals, filterType).map((g) => g.id));
    return goals.filter(
        (g) => g && (inScope.has(g.id) || (g.id && keep.has(g.id))),
    );
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = { typeForCategory, filterGoalsByType, goalsForDropdown };
} else if (typeof window !== "undefined") {
    window.goalFilterHelpers = { typeForCategory, filterGoalsByType, goalsForDropdown };
}
