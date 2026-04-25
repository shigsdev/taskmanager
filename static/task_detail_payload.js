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
 */
"use strict";

function buildTaskDetailPayload(form) {
    return {
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
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = { buildTaskDetailPayload: buildTaskDetailPayload };
}
