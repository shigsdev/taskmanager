/**
 * buildTaskDetailPayload — pure builder for the PATCH /api/tasks/<id> body.
 *
 * Extracted from app.js taskDetailSave so it can be unit-tested without a
 * DOM. The save handler reads form values into a plain object and passes
 * it here; this function returns the exact JSON body sent to the API.
 *
 * Bug #57 (2026-04-25): a stale `type === "work"` conditional here used to
 * force `project_id: null` for any non-work task, silently dropping the
 * dropdown selection on personal tasks. Fixed: project_id is now always
 * passed through. Personal projects exist (#48 era) and personal tasks
 * must be able to reference them.
 *
 * Bug #148 (2026-05-05): when the user opens an archived (completed) /
 * cancelled task in the detail panel, changes a field, and clicks Save,
 * the save sent only the changed fields — never `status` — so the
 * server kept the task ARCHIVED. Result: the task vanished from the
 * active board (filtered to status=active) AND stayed under Completed
 * (cached `allCompleted` not refreshed). Fix: when an `originalTask`
 * snapshot is passed AND its status is archived/cancelled AND the form
 * differs from the snapshot in any tracked field, augment the payload
 * with `status: "active"` + `cancellation_reason: null`. Server's
 * update_task already honors explicit status, so the round-trip works
 * end-to-end. The save handler also calls loadCompletedTasks +
 * loadCancelledTasks after save to refresh those caches.
 *
 * detailFormDiffersFromSnapshot — exposed for testing and for the save
 * handler that wants to know "did anything change?" without rebuilding
 * the whole payload comparison.
 */
"use strict";

const _DETAIL_TRACKED_FIELDS = [
    "title", "tier", "type",
    "project_id", "due_date", "goal_id",
    "url", "notes",
];

function _normalize(v) {
    // Treat null / undefined / empty-string / missing as the same null
    // for diff purposes — the form yields "" where the API yields null
    // for the same "no value" state.
    if (v === undefined || v === null) return null;
    if (typeof v === "string" && v === "") return null;
    return v;
}

function _equal(a, b) {
    return JSON.stringify(_normalize(a)) === JSON.stringify(_normalize(b));
}

function detailFormDiffersFromSnapshot(form, original) {
    if (!original) return false;
    for (const f of _DETAIL_TRACKED_FIELDS) {
        if (!_equal(form[f], original[f])) return true;
    }
    if (!_equal(form.checklist || [], original.checklist || [])) return true;
    if (!_equal(form.repeat, original.repeat)) return true;
    return false;
}

function buildTaskDetailPayload(form, originalTask) {
    const payload = {
        title: form.title,
        tier: form.tier,
        type: form.type,
        project_id: form.project_id || null,
        due_date: form.due_date || null,
        goal_id: form.goal_id || null,
        url: form.url || null,
        notes: form.notes || "",
        checklist: form.checklist || [],
        repeat: form.repeat || null,
    };
    // #148: augment with status:active + clear cancellation_reason
    // when the user is bringing a completed/cancelled task back to
    // life by editing a field. No-op saves on completed tasks (no
    // field changes) leave status alone — preserves the case where
    // a user just opens a completed task and clicks Save absent-
    // mindedly.
    if (
        originalTask
        && (originalTask.status === "archived" || originalTask.status === "cancelled")
        && detailFormDiffersFromSnapshot(form, originalTask)
    ) {
        payload.status = "active";
        payload.cancellation_reason = null;
    }
    return payload;
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        buildTaskDetailPayload: buildTaskDetailPayload,
        detailFormDiffersFromSnapshot: detailFormDiffersFromSnapshot,
        _DETAIL_TRACKED_FIELDS: _DETAIL_TRACKED_FIELDS,
    };
}
