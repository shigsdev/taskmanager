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

const { buildTaskDetailPayload } = require("../../../static/task_detail_payload");

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
