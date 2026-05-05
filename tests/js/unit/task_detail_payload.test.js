/**
 * Jest tests for buildTaskDetailPayload — guards bug #57.
 *
 * Bug #57 (2026-04-25): a stale `type === "work"` conditional in app.js
 * forced project_id: null on every non-work task save, silently dropping
 * the dropdown selection. The bug never raised an error — the API
 * accepted what it received. The only way to catch this class is a
 * payload assertion. These tests are exactly that.
 */
"use strict";

const {
    buildTaskDetailPayload,
    detailFormDiffersFromSnapshot,
} = require("../../../static/task_detail_payload");

describe("buildTaskDetailPayload — project_id passthrough (bug #57)", () => {
    test("personal task with project_id keeps the project_id", () => {
        const payload = buildTaskDetailPayload({
            title: "udpate resume",
            tier: "today",
            type: "personal",
            project_id: "710cbbea-60ce-4c2e-bb5d-c69b3e7645c4",
            due_date: "",
            goal_id: "",
            url: "",
            notes: "",
            checklist: [],
            repeat: null,
        });
        expect(payload.project_id).toBe("710cbbea-60ce-4c2e-bb5d-c69b3e7645c4");
    });

    test("work task with project_id keeps the project_id", () => {
        const payload = buildTaskDetailPayload({
            title: "ship feature",
            tier: "today",
            type: "work",
            project_id: "abc-123",
            due_date: "",
            goal_id: "",
            url: "",
            notes: "",
            checklist: [],
            repeat: null,
        });
        expect(payload.project_id).toBe("abc-123");
    });

    test("empty project_id becomes null", () => {
        const payload = buildTaskDetailPayload({
            title: "x",
            tier: "inbox",
            type: "personal",
            project_id: "",
            due_date: "",
            goal_id: "",
            url: "",
            notes: "",
            checklist: [],
            repeat: null,
        });
        expect(payload.project_id).toBeNull();
    });
});

describe("buildTaskDetailPayload — basic field passthrough", () => {
    test("all fields round-trip", () => {
        const form = {
            title: "task title",
            tier: "week",
            type: "work",
            project_id: "p1",
            due_date: "2026-05-01",
            goal_id: "g1",
            url: "https://example.com",
            notes: "some notes",
            checklist: [{ id: "0", text: "step 1", checked: false }],
            repeat: { frequency: "weekly", day_of_week: 1 },
        };
        const payload = buildTaskDetailPayload(form);
        expect(payload).toEqual({
            title: "task title",
            tier: "week",
            type: "work",
            project_id: "p1",
            due_date: "2026-05-01",
            goal_id: "g1",
            url: "https://example.com",
            notes: "some notes",
            checklist: [{ id: "0", text: "step 1", checked: false }],
            repeat: { frequency: "weekly", day_of_week: 1 },
        });
    });

    test("empty optionals collapse to nulls / defaults", () => {
        const payload = buildTaskDetailPayload({
            title: "x",
            tier: "inbox",
            type: "personal",
            project_id: "",
            due_date: "",
            goal_id: "",
            url: "",
            notes: "",
            checklist: [],
            repeat: null,
        });
        expect(payload.due_date).toBeNull();
        expect(payload.goal_id).toBeNull();
        expect(payload.url).toBeNull();
        expect(payload.notes).toBe("");
        expect(payload.checklist).toEqual([]);
        expect(payload.repeat).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// #148 (2026-05-05): detail-panel tier change on a completed/cancelled task
// must un-archive when the user actually changed something.
// ---------------------------------------------------------------------------

const ARCHIVED_TASK = Object.freeze({
    id: "t1",
    title: "Original title",
    tier: "today",
    type: "personal",
    project_id: "p1",
    due_date: "2026-05-04",
    goal_id: null,
    url: null,
    notes: "",
    checklist: [],
    repeat: null,
    status: "archived",
});

const CANCELLED_TASK = Object.freeze({
    ...ARCHIVED_TASK,
    status: "cancelled",
    cancellation_reason: "Decided not to do it",
});

function _formFromTask(task, overrides = {}) {
    return {
        title: task.title,
        tier: task.tier,
        type: task.type,
        project_id: task.project_id || "",
        due_date: task.due_date || "",
        goal_id: task.goal_id || "",
        url: task.url || "",
        notes: task.notes || "",
        checklist: task.checklist || [],
        repeat: task.repeat || null,
        ...overrides,
    };
}

describe("buildTaskDetailPayload — #148 unarchive on field change", () => {
    test("archived task + changed tier → status:active + cancellation_reason:null", () => {
        const form = _formFromTask(ARCHIVED_TASK, { tier: "today" });
        // Change tier from saved "today" to "this_week" so the diff fires.
        form.tier = "this_week";
        const payload = buildTaskDetailPayload(form, ARCHIVED_TASK);
        expect(payload.status).toBe("active");
        expect(payload.cancellation_reason).toBeNull();
        expect(payload.tier).toBe("this_week");
    });

    test("cancelled task + changed title → status:active + cancellation_reason cleared", () => {
        const form = _formFromTask(CANCELLED_TASK, { title: "New title" });
        const payload = buildTaskDetailPayload(form, CANCELLED_TASK);
        expect(payload.status).toBe("active");
        expect(payload.cancellation_reason).toBeNull();
        expect(payload.title).toBe("New title");
    });

    test("archived task with NO field change → no status flip", () => {
        // User opened the panel and clicked Save absent-mindedly; the
        // task should stay archived. This is the explicit guard
        // requested in the BACKLOG row.
        const form = _formFromTask(ARCHIVED_TASK);
        const payload = buildTaskDetailPayload(form, ARCHIVED_TASK);
        expect(payload.status).toBeUndefined();
        expect(payload.cancellation_reason).toBeUndefined();
    });

    test("active task with field change → no status flip (no upgrade needed)", () => {
        const active = { ...ARCHIVED_TASK, status: "active" };
        const form = _formFromTask(active, { tier: "this_week" });
        const payload = buildTaskDetailPayload(form, active);
        expect(payload.status).toBeUndefined();
    });

    test("no snapshot at all → no status flip (creating-via-panel path is null-safe)", () => {
        const form = _formFromTask(ARCHIVED_TASK, { title: "anything" });
        const payload = buildTaskDetailPayload(form);
        expect(payload.status).toBeUndefined();
    });

    test("checklist-checked-state change counts as a field change", () => {
        const taskWithChecklist = {
            ...ARCHIVED_TASK,
            checklist: [{ id: "0", text: "step 1", checked: false }],
        };
        const form = _formFromTask(taskWithChecklist, {
            checklist: [{ id: "0", text: "step 1", checked: true }],
        });
        const payload = buildTaskDetailPayload(form, taskWithChecklist);
        expect(payload.status).toBe("active");
    });
});

describe("detailFormDiffersFromSnapshot — diff helper", () => {
    test("returns false when form mirrors snapshot exactly", () => {
        const form = _formFromTask(ARCHIVED_TASK);
        expect(detailFormDiffersFromSnapshot(form, ARCHIVED_TASK)).toBe(false);
    });

    test("treats null vs empty-string as equal (form/API shape parity)", () => {
        const original = { ...ARCHIVED_TASK, url: null, goal_id: null };
        const form = _formFromTask(original);
        // _formFromTask already converts null → "", which is what the
        // form actually emits. Nothing else changed.
        expect(detailFormDiffersFromSnapshot(form, original)).toBe(false);
    });

    test("returns true on title change", () => {
        const form = _formFromTask(ARCHIVED_TASK, { title: "Different" });
        expect(detailFormDiffersFromSnapshot(form, ARCHIVED_TASK)).toBe(true);
    });

    test("returns true on repeat change", () => {
        const original = { ...ARCHIVED_TASK, repeat: null };
        const form = _formFromTask(original, { repeat: { frequency: "daily" } });
        expect(detailFormDiffersFromSnapshot(form, original)).toBe(true);
    });

    test("null original means no diff (defensive — not ever expected)", () => {
        const form = _formFromTask(ARCHIVED_TASK, { title: "Whatever" });
        expect(detailFormDiffersFromSnapshot(form, null)).toBe(false);
    });
});
