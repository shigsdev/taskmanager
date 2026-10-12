/**
 * #430: board actions that fail say so.
 *
 * Drag-and-drop, the quick tier buttons, ✓, the panel's Delete / Complete,
 * swipe-Delete, Inbox triage, a drop on Completed, the subtask checkbox and
 * the goal page's linked-task checkbox / Archive had no failure handling: the
 * card stayed where it was dropped (or the panel closed) as if it had worked,
 * until the next poll quietly put it back. They now share one path: say what
 * didn't save, then reload what's on the page.
 */
"use strict";

const { actionFailureMessage } = require("../../../static/api_helpers");
const apiClient = require("../../../static/api_client");

describe("actionFailureMessage (#430)", () => {
    test("a thrown error names the action and the reason", () => {
        expect(actionFailureMessage("Moving the task", new Error("tier invalid")))
            .toBe("Moving the task didn't save: tier invalid. The page now shows what's saved.");
    });

    test("an error apiFetch already told you about gets no second dialog", () => {
        const err = new TypeError("Failed to fetch");
        err.userNotified = true;
        expect(actionFailureMessage("Moving the task", err)).toBeNull();
    });

    test("an error with no message still says something", () => {
        expect(actionFailureMessage("Deleting the task", {}))
            .toBe("Deleting the task didn't save. The page now shows what's saved.");
        expect(actionFailureMessage("Deleting the task", "boom"))
            .toBe("Deleting the task didn't save: boom. The page now shows what's saved.");
    });

    test("a bulk result with failures counts them", () => {
        expect(actionFailureMessage("Completing the tasks", null, {
            updated: 1, not_found: ["x"], errors: [{ id: "y" }],
        })).toBe("Completing the tasks: 2 of 3 didn't save. The page now shows what's saved.");
    });

    test("a bulk result names the server's reasons once each (#433)", () => {
        const why = "2 open subtask(s) — complete them too or close them individually first";
        expect(actionFailureMessage("Completing the tasks", null, {
            updated: 1, not_found: [],
            errors: [{ id: "a", message: why }, { id: "b", message: why }],
        })).toBe(`Completing the tasks: 2 of 3 didn't save (${why}). The page now shows what's saved.`);
    });

    test("a clean bulk result, or nothing at all, says nothing", () => {
        expect(actionFailureMessage("Moving the tasks", null, { updated: 3, not_found: [], errors: [] }))
            .toBeNull();
        expect(actionFailureMessage("Moving the tasks", null, null)).toBeNull();
        expect(actionFailureMessage("Moving the tasks")).toBeNull();
    });
});

describe("apiFetch marks the errors it already showed a prompt for (#430)", () => {
    beforeEach(() => {
        apiClient._resetRecoveryFlag();
        global.confirm = jest.fn(() => false);
        global.setTimeout = (fn) => fn();
    });

    test("a network failure on a write", async () => {
        global.fetch = jest.fn(async () => { throw new TypeError("Failed to fetch"); });
        const err = await apiClient.apiFetch("/api/tasks/1", { method: "PATCH", body: "{}" })
            .catch((e) => e);
        expect(err.userNotified).toBe(true);
    });

    test("an expired sign-in", async () => {
        global.fetch = jest.fn(async () => ({ status: 401, ok: false }));
        const err = await apiClient.apiFetch("/api/tasks/1", { method: "PATCH" }).catch((e) => e);
        expect(err.userNotified).toBe(true);
    });

    test("a server error is NOT marked (the caller must say it)", async () => {
        global.fetch = jest.fn(async () => ({
            status: 500, ok: false, statusText: "Server Error",
            json: async () => ({ error: "db down" }),
        }));
        const err = await apiClient.apiFetch("/api/tasks/1", { method: "PATCH" }).catch((e) => e);
        expect(err.message).toBe("db down");
        expect(err.userNotified).toBeFalsy();
    });
});
