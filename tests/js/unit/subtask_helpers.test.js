/**
 * Jest tests for #433 — the words a confirm uses when closing or deleting
 * tasks also closes or deletes their open subtasks.
 *
 * Bulk Mark complete / cancelled, a multi-drag onto Completed and every
 * Delete used to strand open subtasks as stray cards. Now they close (or go
 * to the Recycle Bin) with their parent, and the confirm says so first. A
 * repeating task keeps its subtasks open when it closes (#230), so it's
 * left out of the complete / cancel count.
 */
const { openSubtaskSummary, subtaskCloseNote } = require("../../../static/subtask_helpers.js");

const parent = (id, count, done, extra) =>
    Object.assign({ id, parent_id: null, subtask_count: count, subtask_done: done }, extra);

describe("openSubtaskSummary (#433)", () => {
    test("counts open subtasks per parent", () => {
        expect(openSubtaskSummary([
            parent("a", 3, 1),   // 2 open
            parent("b", 1, 0),   // 1 open
            parent("c", 2, 2),   // all done
            parent("d", 0, 0),
        ])).toEqual({ parents: 2, open: 3 });
    });

    test("a subtask in the selection is not a parent", () => {
        expect(openSubtaskSummary([
            parent("s", 2, 0, { parent_id: "x" }),
        ])).toEqual({ parents: 0, open: 0 });
    });

    test("repeating tasks keep their subtasks open, unless deleting", () => {
        const tasks = [parent("r", 2, 0, { recurring_task_id: "t1" }), parent("p", 1, 0)];
        expect(openSubtaskSummary(tasks)).toEqual({ parents: 1, open: 1 });
        expect(openSubtaskSummary(tasks, { includeRepeating: true }))
            .toEqual({ parents: 2, open: 3 });
    });

    test("nothing, or nonsense, is nothing", () => {
        expect(openSubtaskSummary([])).toEqual({ parents: 0, open: 0 });
        expect(openSubtaskSummary(null)).toEqual({ parents: 0, open: 0 });
        expect(openSubtaskSummary([null, undefined])).toEqual({ parents: 0, open: 0 });
    });
});

describe("subtaskCloseNote (#433)", () => {
    test("no open subtasks adds nothing", () => {
        expect(subtaskCloseNote("complete", { parents: 0, open: 0 }, 5)).toBe("");
        expect(subtaskCloseNote("delete", null, 1)).toBe("");
    });

    test("a selection names how many parents and subtasks", () => {
        expect(subtaskCloseNote("complete", { parents: 2, open: 3 }, 5))
            .toBe("2 of them have 3 open subtasks, which will be completed too.");
        expect(subtaskCloseNote("cancel", { parents: 1, open: 1 }, 4))
            .toBe("1 of them has 1 open subtask, which will be cancelled too.");
    });

    test("a single task says It", () => {
        expect(subtaskCloseNote("delete", { parents: 1, open: 3 }, 1))
            .toBe("It has 3 open subtasks, which go to the Recycle Bin with it and come back when you restore it.");
    });

    test("deleting several parents says them", () => {
        expect(subtaskCloseNote("delete", { parents: 2, open: 4 }, 3))
            .toBe("2 of them have 4 open subtasks, which go to the Recycle Bin with them and come back when you restore them.");
    });

    test("an unknown action adds nothing", () => {
        expect(subtaskCloseNote("archive", { parents: 1, open: 1 }, 1)).toBe("");
    });
});
