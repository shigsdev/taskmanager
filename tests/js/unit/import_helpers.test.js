/**
 * Jest tests for #432 — which confirm endpoint an import goes to.
 *
 * The import page's confirm step used to pick its URL with an if / else-if /
 * else whose last branch was goals. A review shown after Back (mode null)
 * fell through to it, and task candidates were posted as goals. The URL now
 * comes from a fixed table: an unknown mode has no URL, so nothing is sent.
 */
const { importConfirmUrl, importNoun } = require("../../../static/import_helpers.js");

describe("importConfirmUrl (#432)", () => {
    test("each real mode has its own endpoint", () => {
        expect(importConfirmUrl("tasks")).toBe("/api/import/tasks/confirm");
        expect(importConfirmUrl("projects")).toBe("/api/import/projects/confirm");
        expect(importConfirmUrl("goals")).toBe("/api/import/goals/confirm");
    });

    test("no mode never falls through to goals", () => {
        expect(importConfirmUrl(null)).toBeNull();
        expect(importConfirmUrl(undefined)).toBeNull();
        expect(importConfirmUrl("")).toBeNull();
    });

    test("an unknown or inherited name has no endpoint", () => {
        expect(importConfirmUrl("task")).toBeNull();
        expect(importConfirmUrl("constructor")).toBeNull();
        expect(importConfirmUrl("toString")).toBeNull();
    });
});

describe("importNoun (#432)", () => {
    test("names what each mode imports", () => {
        expect(importNoun("tasks")).toBe("task(s)");
        expect(importNoun("projects")).toBe("project(s)");
        expect(importNoun("goals")).toBe("goal(s)");
    });

    test("no mode is never called goals", () => {
        expect(importNoun(null)).toBe("item(s)");
        expect(importNoun("constructor")).toBe("item(s)");
    });
});
