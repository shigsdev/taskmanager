/**
 * Filter + project-dropdown pure helpers, extracted from app.js so they
 * can be unit-tested from Jest (PR39 — closes audit C3 + C7).
 *
 * Same dual-export pattern as parse_capture.js: in the browser, the
 * functions are attached to the global window via `<script>` load; in
 * Node.js (Jest) they are require()-able via module.exports.
 *
 * What lives here vs. app.js:
 *   - Pure logic with no DOM dependency lives here (testable in Jest).
 *   - DOM mutation + state mutation stays in app.js (covered by Phase 6
 *     + local Playwright).
 *
 * The functions here all take their inputs as args and return their
 * results; they never read or write module-level state. That contract
 * is what makes them testable in isolation.
 */
"use strict";

// PR28 audit fix #5: validate UUID format on read so a tampered or
// stale localStorage value can't silently hide all tasks.
const FILTER_UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isValidUuid(s) {
    return typeof s === "string" && FILTER_UUID_RE.test(s);
}

/**
 * #97 (PR31): parse a comma-joined UUID string from localStorage into
 * a Set, dropping any entry that doesn't pass the UUID format check.
 * Returns a fresh Set (caller mutates it freely).
 */
function parseUuidCsv(raw) {
    if (!raw) return new Set();
    return new Set(
        String(raw).split(",").map((s) => s.trim()).filter(isValidUuid),
    );
}

/**
 * #97 inverse: serialize a Set<UUID> to comma-joined string for
 * localStorage. Empty Set → empty string (caller may choose to
 * removeItem instead).
 */
function serializeUuidSet(set) {
    if (!set || set.size === 0) return "";
    return Array.from(set).join(",");
}

/**
 * Sweep stale UUIDs from a filter Set after a fresh fetch (PR36 BUG-2).
 * Mutates `filterSet` in place; returns true if anything was removed.
 *
 * @param {Set<string>} filterSet — current selected UUIDs
 * @param {Array<{id: string}>} liveItems — fresh fetched list
 */
function sweepStaleIds(filterSet, liveItems) {
    if (!filterSet || filterSet.size === 0) return false;
    if (!liveItems || liveItems.length === 0) return false;
    const live = new Set(liveItems.map((it) => it.id));
    let dirty = false;
    for (const id of Array.from(filterSet)) {
        if (!live.has(id)) {
            filterSet.delete(id);
            dirty = true;
        }
    }
    return dirty;
}

/**
 * #98 (PR32): scope projects to the active type tab.
 * "all" → return everything; "work"/"personal" → matching type only.
 * Pure: always returns a new array, never mutates input.
 */
function filterProjectsByType(allProjects, currentView) {
    if (!Array.isArray(allProjects)) return [];
    if (currentView === "all" || currentView == null) return allProjects.slice();
    return allProjects.filter((p) => p.type === currentView);
}

/**
 * #92 (PR25) compose: AND across dimensions, OR within. Returns the
 * filtered task list per the project + goal Set semantics + the
 * single-select type tab.
 *
 * #107 (PR42): optional `searchQuery` adds a 4th dimension —
 * case-insensitive substring match against title + notes + url. Empty
 * string = no filter (don't accidentally hide everything on initial
 * empty input).
 */
function applyFilters(allTasks, currentView, projectFilter, goalFilter, searchQuery) {
    if (!Array.isArray(allTasks)) return [];
    let tasks = allTasks;
    if (currentView === "work") {
        tasks = tasks.filter((t) => t.type === "work");
    } else if (currentView === "personal") {
        tasks = tasks.filter((t) => t.type === "personal");
    }
    if (projectFilter && projectFilter.size) {
        tasks = tasks.filter((t) => projectFilter.has(t.project_id));
    }
    if (goalFilter && goalFilter.size) {
        tasks = tasks.filter((t) => goalFilter.has(t.goal_id));
    }
    const q = searchTerm(searchQuery);
    if (q) {
        tasks = tasks.filter((t) => taskMatchesSearch(t, q));
    }
    return tasks;
}

/**
 * #107 (PR42): normalise a search query — trim + lowercase + reject
 * empty. Returns "" for null/undefined/whitespace-only input. Caller
 * uses the truthy check to decide whether to filter.
 */
function searchTerm(raw) {
    if (raw == null) return "";
    return String(raw).trim().toLowerCase();
}

/**
 * #107 (PR42): does task match the (already-normalised) search term?
 * Searches title + notes + url. Cancellation_reason intentionally
 * NOT included — that's an admin field, not part of the user's
 * working knowledge of the task.
 */
function taskMatchesSearch(task, normalisedTerm) {
    if (!normalisedTerm) return true;
    if (!task) return false;
    const fields = [
        task.title || "",
        task.notes || "",
        task.url || "",
    ];
    return fields.some((f) => String(f).toLowerCase().includes(normalisedTerm));
}

// Browser: expose individual helpers on the global object so app.js
// can use them without a bundler. Node (Jest): export via module.exports.
if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        FILTER_UUID_RE,
        isValidUuid,
        parseUuidCsv,
        serializeUuidSet,
        sweepStaleIds,
        filterProjectsByType,
        applyFilters,
        searchTerm,
        taskMatchesSearch,
    };
} else if (typeof window !== "undefined") {
    window.filterHelpers = {
        FILTER_UUID_RE,
        isValidUuid,
        parseUuidCsv,
        serializeUuidSet,
        sweepStaleIds,
        filterProjectsByType,
        applyFilters,
        searchTerm,
        taskMatchesSearch,
    };
}
