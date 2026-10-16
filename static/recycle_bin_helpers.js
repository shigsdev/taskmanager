/**
 * Pure helpers for the Recycle Bin page's Deleted tasks section (#428).
 *
 * Deleting a task only ever set `status = DELETED`; the row stays in the
 * database and nothing purges it, but no screen listed it, so it could not
 * come back. The page lists them (GET /api/tasks?status=deleted) and
 * restores one with PATCH {status: "active"}.
 *
 * Dual-export per CLAUDE.md anti-pattern #3:
 *   Browser: window.recycleBinHelpers
 *   Node (Jest): module.exports
 */
"use strict";

var _BIN_SECTION_LABELS = {
    inbox: "Inbox",
    today: "Today",
    tomorrow: "Tomorrow",
    this_week: "This Week",
    next_week: "Next Week",
    backlog: "Backlog",
    freezer: "Freezer",
};

/** The board's name for a tier value ("this_week" → "This Week"). */
function binSectionLabel(tier) {
    return _BIN_SECTION_LABELS[tier] || tier;
}

/**
 * When a task was deleted, as a Date. Nothing writes a deleted task, so its
 * `updated_at` is the delete. The server's isoformat may carry no zone; it
 * is UTC either way.
 *
 * @param {string|null} updatedAt
 * @returns {Date|null}
 */
function binDeletedDate(updatedAt) {
    if (!updatedAt) { return null; }
    var s = String(updatedAt);
    if (!/(Z|[+-]\d\d:?\d\d)$/.test(s)) { s += "Z"; }
    var d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
}

/**
 * The Deleted tasks list: newest delete first, the first `limit` rows
 * shown and the rest counted. A deleted subtask whose parent is deleted
 * too is flagged — restoring it alone leaves it under a hidden parent.
 * A task still in an undone import batch (`batch_id` set — an ordinary
 * delete clears it) is left out: it comes back with its batch.
 *
 * @param {Array<object>} tasks — GET /api/tasks?status=deleted rows.
 * @param {number} [limit] — rows to show; all when omitted.
 * @returns {{rows: Array<object>, hidden: number, total: number}}
 */
function binDeletedTasks(tasks, limit) {
    var all = Array.isArray(tasks) ? tasks : [];
    // #465: every deleted task counts as "in the bin" for a subtask's
    // parent — an undone import's tasks too, though they aren't listed.
    var deletedIds = {};
    all.forEach(function (t) { deletedIds[t.id] = true; });
    var list = all.filter(function (t) {
        return !t.batch_id;
    });
    // #433: an open subtask that went to the bin with its parent comes back
    // with that parent's Restore, so it's counted on the parent's row
    // instead of listed on its own. #465: one that went with an undone
    // import's task comes back with the batch's Restore — not listed either.
    var withParent = {};
    list = list.filter(function (t) {
        if (t.deleted_with_parent && t.parent_id && deletedIds[t.parent_id]) {
            withParent[t.parent_id] = (withParent[t.parent_id] || 0) + 1;
            return false;
        }
        return true;
    });
    list.sort(function (a, b) {
        var da = binDeletedDate(a.updated_at), db = binDeletedDate(b.updated_at);
        return (db ? db.getTime() : 0) - (da ? da.getTime() : 0);
    });
    var rows = list.map(function (t) {
        return {
            id: t.id,
            title: t.title,
            section: binSectionLabel(t.tier),
            deletedAt: binDeletedDate(t.updated_at),
            parentDeleted: Boolean(t.parent_id && deletedIds[t.parent_id]),
            subtaskCount: withParent[t.id] || 0,
        };
    });
    var shown = limit ? Math.min(limit, rows.length) : rows.length;
    return { rows: rows.slice(0, shown), hidden: rows.length - shown, total: rows.length };
}

// #478: projects count in the bin too. The server always sent
// project_count; the page added only tasks + goals, so a bin holding just
// an undone project import read "No undone imports." with Empty Bin off.
var _BIN_KINDS = ["task", "goal", "project"];

function _binCount(counts, kind, key) {
    if (!counts) return 0;
    var v = counts[key || (kind + "_count")];
    if (v == null) v = counts[kind + "_count"];   // e.g. no restore_* sent
    return Number(v) || 0;
}

/** binItemTotal - tasks + goals + projects in a summary or batch. */
function binItemTotal(counts) {
    return _BIN_KINDS.reduce(function (sum, kind) {
        return sum + _binCount(counts, kind);
    }, 0);
}

/**
 * binItemPhrase - "2 tasks, 1 goal and 3 projects", leaving out kinds
 * with none; "nothing" when every count is zero. `keys` names which field
 * to read per kind ({goal: "restore_goal_count", ...}); a missing one
 * falls back to the plain <kind>_count.
 */
function binItemPhrase(counts, keys) {
    var parts = [];
    _BIN_KINDS.forEach(function (kind) {
        var n = _binCount(counts, kind, keys && keys[kind]);
        if (n) parts.push(n + " " + kind + (n === 1 ? "" : "s"));
    });
    if (!parts.length) return "nothing";
    if (parts.length === 1) return parts[0];
    return parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1];
}

var _recycleBinApi = {
    binItemTotal: binItemTotal,
    binItemPhrase: binItemPhrase,
    binDeletedTasks: binDeletedTasks,
    binSectionLabel: binSectionLabel,
    binDeletedDate: binDeletedDate,
};

if (typeof module !== "undefined" && module.exports) {
    module.exports = _recycleBinApi;
} else if (typeof window !== "undefined") {
    window.recycleBinHelpers = _recycleBinApi;
}
