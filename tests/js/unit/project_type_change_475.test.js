/**
 * #475: a task can only sit on a project of its own type.
 *
 * projectAfterTypeChange — what the task panel's Project select becomes when
 * Type changes. It used to keep the old project selected as "(unavailable)",
 * and Save wrote a work task onto a personal project.
 */
"use strict";

const { projectAfterTypeChange } = require("../../../static/filter_helpers");

const projects = [
    { id: "p-work", type: "work" },
    { id: "p-home", type: "personal" },
    { id: "p-old-work", type: "work", is_active: false },
];

describe("projectAfterTypeChange (#475)", () => {
    test("a project of the other type is dropped", () => {
        expect(projectAfterTypeChange("p-work", "personal", projects)).toBe("");
        expect(projectAfterTypeChange("p-home", "work", projects)).toBe("");
    });

    test("an archived project of the other type is dropped too", () => {
        expect(projectAfterTypeChange("p-old-work", "personal", projects)).toBe("");
    });

    test("a project of the new type stays", () => {
        expect(projectAfterTypeChange("p-work", "work", projects)).toBe("p-work");
        expect(projectAfterTypeChange("p-home", "personal", projects)).toBe("p-home");
    });

    test("no project, an unknown id or no type changes nothing", () => {
        expect(projectAfterTypeChange("", "work", projects)).toBe("");
        expect(projectAfterTypeChange(null, "work", projects)).toBe("");
        expect(projectAfterTypeChange("p-gone", "personal", projects)).toBe("p-gone");
        expect(projectAfterTypeChange("p-work", "", projects)).toBe("p-work");
        expect(projectAfterTypeChange("p-work", "personal", null)).toBe("p-work");
    });
});
