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
    var list = (Array.isArray(tasks) ? tasks : []).filter(function (t) {
        return !t.batch_id;
    });
    var deletedIds = {};
    list.forEach(function (t) { deletedIds[t.id] = true; });
    // #433: an open subtask that went to the bin with its parent comes back
    // with that parent's Restore, so it's counted on the parent's row
    // instead of listed on its own.
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

var _recycleBinApi = {
    binDeletedTasks: binDeletedTasks,
    binSectionLabel: binSectionLabel,
    binDeletedDate: binDeletedDate,
};

if (typeof module !== "undefined" && module.exports) {
    module.exports = _recycleBinApi;
} else if (typeof window !== "undefined") {
    window.recycleBinHelpers = _recycleBinApi;
}
