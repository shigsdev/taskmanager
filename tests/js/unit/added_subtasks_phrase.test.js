/**
 * #494: the Undo / Recycle Bin words count the subtasks you added to an
 * import's tasks, which the Undo takes along (#465).
 */
"use strict";

const { addedSubtasksPhrase } = require("../../../static/recycle_bin_helpers");

describe("addedSubtasksPhrase (#494)", () => {
    test("none says nothing (the quiet case)", () => {
        for (const when of ["undo", "row", "restore", "purge"]) {
            expect(addedSubtasksPhrase(0, when)).toBe("");
            expect(addedSubtasksPhrase(undefined, when)).toBe("");
        }
    });

    test("the Undo confirm", () => {
        expect(addedSubtasksPhrase(1, "undo")).toBe("1 subtask you added goes with it.");
        expect(addedSubtasksPhrase(2, "undo")).toBe("2 subtasks you added go with it.");
    });

    test("the bin row", () => {
        expect(addedSubtasksPhrase(1, "row")).toBe("+1 subtask you added");
        expect(addedSubtasksPhrase(3, "row")).toBe("+3 subtasks you added");
    });

    test("Restore and Purge", () => {
        expect(addedSubtasksPhrase(1, "restore")).toBe("1 subtask you added comes back with it.");
        expect(addedSubtasksPhrase(2, "restore")).toBe("2 subtasks you added come back with it.");
        expect(addedSubtasksPhrase(1, "purge")).toBe("1 subtask you added is deleted with it.");
        expect(addedSubtasksPhrase(2, "purge")).toBe("2 subtasks you added are deleted with it.");
    });
});
