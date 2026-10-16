/**
 * #490: what /scan's Add All / Add Selected send, per kind. The mapping was
 * inline in scan.js with nothing checking it against the keys the server
 * reads — a renamed field would silently drop data (the voice A1 bug's
 * shape). Server keys: scan_service.create_tasks_from_candidates (title,
 * type), create_goals_from_candidates (title, category, priority,
 * target_quarter, actions), import_service.create_projects_from_import
 * (name, type, target_quarter).
 */
"use strict";

const { scanConfirmPayload } = require("../../../static/scan_helpers");

describe("scanConfirmPayload (#490)", () => {
    test("tasks send title and type", () => {
        expect(scanConfirmPayload("tasks", [{ title: "Call Bob", type: "personal", included: true }], false))
            .toEqual([{ title: "Call Bob", type: "personal", included: true }]);
    });

    test("goals send every field the review edits", () => {
        const [row] = scanConfirmPayload("goals", [{
            title: "Run a half", category: "health", priority: "must",
            target_quarter: "2026-Q4", actions: "Train 3x a week", included: true,
        }], false);
        expect(row).toEqual({
            title: "Run a half", category: "health", priority: "must",
            target_quarter: "2026-Q4", actions: "Train 3x a week", included: true,
        });
    });

    test("projects send the edited title as `name`", () => {
        const [row] = scanConfirmPayload("projects", [
            { title: "Kitchen", type: "personal", target_quarter: "2027-Q1", included: true },
        ], false);
        expect(row).toEqual({ name: "Kitchen", type: "personal", target_quarter: "2027-Q1", included: true });
        expect("title" in row).toBe(false);
    });

    test("missing fields get the server's own defaults", () => {
        expect(scanConfirmPayload("goals", [{ title: "G" }], false)[0]).toEqual({
            title: "G", category: "personal_growth", priority: "need_more_info",
            target_quarter: "", actions: "", included: true,
        });
        expect(scanConfirmPayload("projects", [{ title: "P" }], false)[0])
            .toEqual({ name: "P", type: "work", target_quarter: "", included: true });
        expect(scanConfirmPayload("tasks", [{ title: "T" }], false)[0])
            .toEqual({ title: "T", type: "work", included: true });
    });

    test("Add Selected leaves out an unticked row; Add All sends it", () => {
        const rows = [{ title: "a", included: true }, { title: "b", included: false }];
        expect(scanConfirmPayload("tasks", rows, false).map((r) => r.included)).toEqual([true, false]);
        expect(scanConfirmPayload("tasks", rows, true).map((r) => r.included)).toEqual([true, true]);
    });

    test("an unknown kind sends task rows", () => {
        expect(scanConfirmPayload("whatever", [{ title: "T", type: "work" }], false))
            .toEqual([{ title: "T", type: "work", included: true }]);
    });
});
