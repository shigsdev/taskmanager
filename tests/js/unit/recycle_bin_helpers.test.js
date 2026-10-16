/**
 * #428: deleted tasks can be restored from the Recycle Bin.
 *
 * A deleted task only ever had `status = DELETED` set — it stayed in the
 * database, but no screen listed it, so "They will land in the recycle bin"
 * (the bulk-delete confirm) was false. The bin's new Deleted tasks section
 * is built from these helpers.
 */
"use strict";

const {
    binDeletedTasks, binSectionLabel, binDeletedDate,
} = require("../../../static/recycle_bin_helpers");

const t = (id, updated_at, over) => ({
    id, title: `Task ${id}`, tier: "backlog", parent_id: null, updated_at, ...over,
});

describe("binDeletedTasks (#428)", () => {
    test("newest delete first", () => {
        const out = binDeletedTasks([
            t("a", "2026-10-01T10:00:00"),
            t("b", "2026-10-11T09:00:00"),
            t("c", "2026-10-05T12:00:00"),
        ]);
        expect(out.rows.map((r) => r.id)).toEqual(["b", "c", "a"]);
        expect(out.total).toBe(3);
        expect(out.hidden).toBe(0);
    });

    test("a limit shows the newest and counts the rest", () => {
        const tasks = Array.from({ length: 30 }, (_, i) =>
            t(`t${i}`, `2026-10-${String(i % 28 + 1).padStart(2, "0")}T00:00:00`));
        const out = binDeletedTasks(tasks, 25);
        expect(out.rows).toHaveLength(25);
        expect(out.hidden).toBe(5);
        expect(out.total).toBe(30);
    });

    test("rows carry the title, section label and delete date", () => {
        const [row] = binDeletedTasks([t("a", "2026-10-11T23:06:10.770710", { tier: "this_week" })]).rows;
        expect(row).toMatchObject({ id: "a", title: "Task a", section: "This Week", parentDeleted: false });
        expect(row.deletedAt.getTime()).toBe(Date.UTC(2026, 9, 11, 23, 6, 10, 770));
    });

    test("a subtask whose parent is deleted too is flagged", () => {
        const out = binDeletedTasks([
            t("parent", "2026-10-11T10:00:00"),
            t("child", "2026-10-11T10:00:01", { parent_id: "parent" }),
            t("loose", "2026-10-11T10:00:02", { parent_id: "alive" }),
        ]);
        const byId = Object.fromEntries(out.rows.map((r) => [r.id, r]));
        expect(byId.child.parentDeleted).toBe(true);
        expect(byId.loose.parentDeleted).toBe(false);
        expect(byId.parent.parentDeleted).toBe(false);
    });

    test("a task in an undone import batch is left to its batch", () => {
        // Undoing an import marks its tasks deleted too, but they keep their
        // batch_id and come back with the batch's own Restore; restoring one
        // alone would pull it out from under the batch. An ordinary delete
        // clears batch_id.
        const out = binDeletedTasks([
            t("mine", "2026-10-11T10:00:00", { batch_id: null }),
            t("imported", "2026-10-11T11:00:00", { batch_id: "b1" }),
        ]);
        expect(out.rows.map((r) => r.id)).toEqual(["mine"]);
        expect(out.total).toBe(1);
    });

    test("nothing deleted", () => {
        expect(binDeletedTasks([])).toEqual({ rows: [], hidden: 0, total: 0 });
        expect(binDeletedTasks(null)).toEqual({ rows: [], hidden: 0, total: 0 });
    });

    // #433: deleting a parent takes its open subtasks to the bin, marked
    // deleted_with_parent; restoring the parent brings them back.
    test("subtasks that went with their parent are listed under it", () => {
        const out = binDeletedTasks([
            t("parent", "2026-10-12T10:00:00"),
            t("s1", "2026-10-12T10:00:00", { parent_id: "parent", deleted_with_parent: true }),
            t("s2", "2026-10-12T10:00:00", { parent_id: "parent", deleted_with_parent: true }),
            t("alone", "2026-10-11T10:00:00", { parent_id: "parent" }),
        ]);
        expect(out.rows.map((r) => r.id)).toEqual(["parent", "alone"]);
        expect(out.total).toBe(2);
        const byId = Object.fromEntries(out.rows.map((r) => [r.id, r]));
        expect(byId.parent.subtaskCount).toBe(2);
        expect(byId.alone.subtaskCount).toBe(0);
        // Deleted on its own earlier: its own row, flagged as before.
        expect(byId.alone.parentDeleted).toBe(true);
    });

    // #465: an import Undo takes the subtasks you added to its tasks; they
    // come back with the batch's Restore, so they're not listed on their own
    // — although the batch parent itself isn't listed here either.
    test("a subtask that went with an undone import's task is not listed", () => {
        const out = binDeletedTasks([
            t("imported", "2026-10-16T10:00:00", { batch_id: "b1" }),
            t("added", "2026-10-16T10:00:00", { parent_id: "imported", deleted_with_parent: true }),
            t("own", "2026-10-15T10:00:00", { parent_id: "imported" }),
        ]);
        expect(out.rows.map((r) => r.id)).toEqual(["own"]);
        expect(out.total).toBe(1);
        // Deleted on its own: listed, and flagged — its parent is in the bin.
        expect(out.rows[0].parentDeleted).toBe(true);
    });

    test("a marked subtask whose parent isn't in the bin keeps its own row", () => {
        const out = binDeletedTasks([
            t("s1", "2026-10-12T10:00:00", { parent_id: "gone", deleted_with_parent: true }),
        ]);
        expect(out.rows.map((r) => r.id)).toEqual(["s1"]);
    });
});

describe("binSectionLabel (#428)", () => {
    test("every section reads as it does on the board", () => {
        expect(binSectionLabel("inbox")).toBe("Inbox");
        expect(binSectionLabel("today")).toBe("Today");
        expect(binSectionLabel("tomorrow")).toBe("Tomorrow");
        expect(binSectionLabel("this_week")).toBe("This Week");
        expect(binSectionLabel("next_week")).toBe("Next Week");
        expect(binSectionLabel("backlog")).toBe("Backlog");
        expect(binSectionLabel("freezer")).toBe("Freezer");
    });
});

describe("binDeletedDate (#428)", () => {
    test("a timestamp with no zone is UTC (the server's isoformat)", () => {
        expect(binDeletedDate("2026-10-11T23:06:10").getTime()).toBe(Date.UTC(2026, 9, 11, 23, 6, 10));
    });
    test("a timestamp with a zone is taken as given", () => {
        expect(binDeletedDate("2026-10-11T23:06:10+00:00").getTime()).toBe(Date.UTC(2026, 9, 11, 23, 6, 10));
        expect(binDeletedDate("2026-10-11T19:06:10-04:00").getTime()).toBe(Date.UTC(2026, 9, 11, 23, 6, 10));
    });
    test("missing or bad → null", () => {
        expect(binDeletedDate(null)).toBeNull();
        expect(binDeletedDate("nope")).toBeNull();
    });
});

// #478: projects count too. A bin holding only undone project imports read
// "No undone imports." with Empty Bin disabled, and the dialogs never named
// the projects they restore or delete.
const { binItemTotal, binItemPhrase } = require("../../../static/recycle_bin_helpers.js");

describe("binItemTotal (#478)", () => {
    test("tasks + goals + projects", () => {
        expect(binItemTotal({ task_count: 1, goal_count: 2, project_count: 3 })).toBe(6);
    });
    test("a projects-only bin is not empty", () => {
        expect(binItemTotal({ task_count: 0, goal_count: 0, project_count: 2 })).toBe(2);
    });
    test("missing counts are zero (the quiet case: an empty bin)", () => {
        expect(binItemTotal({})).toBe(0);
        expect(binItemTotal(null)).toBe(0);
    });
});

describe("binItemPhrase (#478)", () => {
    test("names each kind, singular and plural, leaving out zeros", () => {
        expect(binItemPhrase({ task_count: 2, goal_count: 1, project_count: 3 }))
            .toBe("2 tasks, 1 goal and 3 projects");
        expect(binItemPhrase({ task_count: 1, goal_count: 0, project_count: 0 })).toBe("1 task");
        expect(binItemPhrase({ task_count: 0, goal_count: 0, project_count: 1 })).toBe("1 project");
        expect(binItemPhrase({ task_count: 3, goal_count: 0, project_count: 2 }))
            .toBe("3 tasks and 2 projects");
    });
    test("nothing at all", () => {
        expect(binItemPhrase({ task_count: 0, goal_count: 0, project_count: 0 })).toBe("nothing");
    });
    test("a caller can name which counts to read (Restore's)", () => {
        const batch = { task_count: 1, goal_count: 2, restore_goal_count: 1,
                        project_count: 2, restore_project_count: 0 };
        expect(binItemPhrase(batch, {
            task: "task_count", goal: "restore_goal_count", project: "restore_project_count",
        })).toBe("1 task and 1 goal");
    });
    test("a missing restore count falls back to the plain count", () => {
        expect(binItemPhrase({ task_count: 0, goal_count: 0, project_count: 2 }, {
            task: "task_count", goal: "restore_goal_count", project: "restore_project_count",
        })).toBe("2 projects");
    });
});
