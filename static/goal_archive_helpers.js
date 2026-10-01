/**
 * goal_archive_helpers.js — pure logic for #349: archiving a goal,
 * bringing it back, and the guarded permanent delete.
 *
 * Dual-export helper (CLAUDE.md anti-pattern #3): the branchy part lives
 * here so Jest can assert its OUTPUTS. `goals.js` keeps the DOM wiring.
 *
 * The bug this closes. `delete_goal` has always been a SOFT delete —
 * it sets `is_active = false` — but the button said **Delete**,
 * `goalsRender` hard-filtered to active goals with no filter control,
 * and there was no unarchive anywhere. Pressing it made a goal
 * permanently invisible and unrecoverable from the UI while the row
 * lived on in the database, and because `delete_goal` also clears
 * `batch_id` on purpose, even the recycle-bin restore would not bring
 * it back. A Delete that silently archives is the worst of both
 * readings: whoever wanted it gone believes it is gone, and whoever
 * wants it back has no route.
 *
 * TWO STEPS TO DESTROY, NOT ONE CONFIRM. The permanent delete is gated
 * on state, not on a scary dialog. A goal must be archived first, and
 * nothing may still point at it. The server is the authority
 * (`goal_service.hard_delete_goal`); this module decides what the
 * BUTTON says, so the reason is visible before the click rather than
 * arriving as an error after it.
 *
 * WHY A GUARD AND NOT A CASCADE. Four models carry a `goal_id` —
 * Project, Task, RecurringTask and WeeklyFocus — and only `Task.goal_id`
 * lacks `ondelete="SET NULL"`. So an unguarded delete would hard-fail on
 * tasks and SILENTLY null the other three. Silently nulling a project's
 * goal because its goal was removed is the same class of invisible data
 * change #350 and #351 exist to stop.
 */
"use strict";

var _GOAL_FILTER_MODES = ["active", "archived", "all"];

/**
 * Which goals the board should show.
 *
 * `mode` is "active" (the default), "archived" or "all". An unknown
 * mode falls back to "active": the board hiding archived rows is the
 * safe failure, the board silently showing them is not.
 */
function goalArchiveFilter(goals, mode) {
    if (!goals || !goals.length) return [];
    var m = _GOAL_FILTER_MODES.indexOf(mode) === -1 ? "active" : mode;
    if (m === "all") return goals.slice();
    var wantActive = m === "active";
    return goals.filter(function (g) {
        // A goal with no `is_active` field is a partial payload, not an
        // archived row — treat it as active rather than hiding it.
        return (g && g.is_active !== false) === wantActive;
    });
}

/** What the archive toggle should say for this goal. */
function goalArchiveToggleLabel(goal) {
    return goal && goal.is_active === false ? "Unarchive" : "Archive";
}

function _gaCount(n, one, many) {
    return n + " " + (n === 1 ? one : many);
}

/**
 * Turn the server's reference counts into a sentence.
 *
 * Returns "" when nothing points at the goal. Order is fixed rather
 * than count-sorted so the sentence reads the same way every time.
 */
function goalReferenceSummary(references) {
    var refs = references || {};
    var parts = [];
    var spec = [
        ["tasks", "task", "tasks"],
        ["projects", "project", "projects"],
        ["recurring", "repeating task", "repeating tasks"],
        ["weekly_focus", "weekly focus", "weekly focuses"],
    ];
    for (var i = 0; i < spec.length; i++) {
        var n = refs[spec[i][0]] || 0;
        if (n > 0) parts.push(_gaCount(n, spec[i][1], spec[i][2]));
    }
    if (!parts.length) return "";
    if (parts.length === 1) return parts[0];
    return parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1];
}

/**
 * Should the permanent-delete button be live, and if not, why?
 *
 * Returns `{ enabled, reason, hint }` where `reason` is "ok",
 * "no-goal", "active" or "referenced". `hint` is shown next to a
 * disabled button — a dead control with no explanation is its own
 * usability bug, and this screen already shipped one of those.
 *
 * `references` may be null, meaning "not counted yet"; the button stays
 * disabled, because defaulting to enabled would offer a destructive
 * action on unknown state.
 */
function goalHardDeleteState(goal, references) {
    if (!goal || !goal.id) {
        return { enabled: false, reason: "no-goal", hint: "" };
    }
    if (goal.is_active !== false) {
        return {
            enabled: false,
            reason: "active",
            hint: "Archive this goal first. Deleting permanently is a "
                + "separate, final step.",
        };
    }
    if (!references) {
        return { enabled: false, reason: "referenced", hint: "Checking…" };
    }
    var summary = goalReferenceSummary(references);
    if (summary) {
        // Agreement follows the TOTAL number of referencing rows, not
        // the number of kinds: "1 task still points … clear it" but
        // "1 task and 1 project still point … clear them". Phase 6
        // caught this reading as "1 task still point"; the Jest cases
        // had only ever asserted the noun phrase.
        var total = 0;
        for (var k in references) {
            if (Object.prototype.hasOwnProperty.call(references, k)) {
                total += references[k] || 0;
            }
        }
        var one = total === 1;
        return {
            enabled: false,
            reason: "referenced",
            hint: summary + " still " + (one ? "points" : "point")
                + " at this goal. Move or clear " + (one ? "it" : "them")
                + " first — deleting would leave "
                + (one ? "it" : "them") + " pointing at nothing.",
        };
    }
    return {
        enabled: true,
        reason: "ok",
        hint: "Nothing points at this goal, so it can be removed for good.",
    };
}

/** The confirm text for the permanent delete. Under test, like #351's. */
function goalHardDeleteConfirm(goal) {
    var title = (goal && goal.title) || "this goal";
    return 'Permanently delete "' + title + '"?\n\n'
        + "The goal is removed from the database. This cannot be undone "
        + "and the recycle bin will not bring it back.";
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        goalArchiveFilter, goalArchiveToggleLabel, goalReferenceSummary,
        goalHardDeleteState, goalHardDeleteConfirm,
    };
} else if (typeof window !== "undefined") {
    window.goalArchiveHelpers = {
        goalArchiveFilter: goalArchiveFilter,
        goalArchiveToggleLabel: goalArchiveToggleLabel,
        goalReferenceSummary: goalReferenceSummary,
        goalHardDeleteState: goalHardDeleteState,
        goalHardDeleteConfirm: goalHardDeleteConfirm,
    };
}
