/**
 * Jest tests for #353 — archiving a project pauses its repeating tasks,
 * and /projects tells the user which ones BEFORE it happens.
 *
 * Per CLAUDE.md anti-pattern #3 these assert OUTPUTS: which templates
 * the helper says will pause, and the exact confirm text. The copy is
 * fixed by the spec (§4.4), so it's asserted verbatim.
 */
"use strict";

const {
    templatesPausedBy,
    archiveConfirmMessage,
    MAX_NAMED,
} = require("../../../static/project_archive_helpers.js");

// #374: the closing sentence follows the count.
const ONE = "It resumes when you unarchive the project.";
const TAIL = "They resume when you unarchive the project.";

function rt(id, title, projectId, isActive = true) {
    return { id, title, project_id: projectId, is_active: isActive };
}

describe("templatesPausedBy", () => {
    test("returns only active templates on the given projects", () => {
        const rows = [
            rt("1", "on target", "p1"),
            rt("2", "other project", "p2"),
            rt("3", "no project", null),
            rt("4", "already paused", "p1", false),
        ];
        expect(templatesPausedBy(rows, ["p1"]).map((t) => t.id)).toEqual(["1"]);
    });

    test("aggregates across several projects (bulk)", () => {
        const rows = [rt("1", "a", "p1"), rt("2", "b", "p2"), rt("3", "c", "p3")];
        expect(templatesPausedBy(rows, ["p1", "p3"]).map((t) => t.id))
            .toEqual(["1", "3"]);
    });

    test("a failed fetch (null / non-array) means nothing to report", () => {
        expect(templatesPausedBy(null, ["p1"])).toEqual([]);
        expect(templatesPausedBy({ error: "x" }, ["p1"])).toEqual([]);
        expect(templatesPausedBy(undefined, ["p1"])).toEqual([]);
    });

    test("no project ids means nothing pauses", () => {
        expect(templatesPausedBy([rt("1", "a", "p1")], [])).toEqual([]);
    });
});

describe("archiveConfirmMessage", () => {
    test("nothing pausing → empty string (the quiet case stays quiet)", () => {
        expect(archiveConfirmMessage([])).toBe("");
    });

    test("one template uses the singular, closing sentence too (#374)", () => {
        expect(archiveConfirmMessage([{ title: "A" }])).toBe(
            `This will pause 1 repeating task: "A". ${ONE}`,
        );
    });

    test("several templates use the plural and list every name", () => {
        expect(archiveConfirmMessage([{ title: "A" }, { title: "B" }])).toBe(
            `This will pause 2 repeating tasks: "A", "B". ${TAIL}`,
        );
    });

    test(`names at most ${5} and counts the rest`, () => {
        expect(MAX_NAMED).toBe(5);
        const seven = ["A", "B", "C", "D", "E", "F", "G"].map((title) => ({ title }));
        expect(archiveConfirmMessage(seven)).toBe(
            `This will pause 7 repeating tasks: "A", "B", "C", "D", "E" and 2 more. ${TAIL}`,
        );
    });

    test("titles render verbatim — confirm() is plain text, not HTML", () => {
        expect(archiveConfirmMessage([{ title: 'say "hi" <b>now</b>' }])).toBe(
            `This will pause 1 repeating task: "say "hi" <b>now</b>". ${ONE}`,
        );
    });

    // #369: the Settings import-undo confirm reuses this builder with its
    // own tail — a {one, many} pair since #374; /projects keeps the default.
    describe("optional tail (#369, #374)", () => {
        const UNDO_TAIL = {
            one: "It resumes if you restore this import from the Recycle Bin.",
            many: "They resume if you restore this import from the Recycle Bin.",
        };

        test("a custom tail replaces the project tail, picked by count", () => {
            expect(archiveConfirmMessage([{ title: "A" }], UNDO_TAIL)).toBe(
                `This will pause 1 repeating task: "A". ${UNDO_TAIL.one}`,
            );
            expect(archiveConfirmMessage([{ title: "A" }, { title: "B" }], UNDO_TAIL)).toBe(
                `This will pause 2 repeating tasks: "A", "B". ${UNDO_TAIL.many}`,
            );
        });

        test("omitted, empty or malformed tail keeps the project tail", () => {
            for (const tail of [undefined, "", "a plain string", {}, { one: "x" }, null]) {
                expect(archiveConfirmMessage([{ title: "A" }], tail)).toBe(
                    `This will pause 1 repeating task: "A". ${ONE}`,
                );
                expect(archiveConfirmMessage([{ title: "A" }, { title: "B" }], tail)).toBe(
                    `This will pause 2 repeating tasks: "A", "B". ${TAIL}`,
                );
            }
        });

        test("nothing pausing is still \"\" with a tail", () => {
            expect(archiveConfirmMessage([], UNDO_TAIL)).toBe("");
            expect(archiveConfirmMessage(undefined, UNDO_TAIL)).toBe("");
        });
    });
});

// #482: changing a project's type retypes its tasks and repeating tasks
// (user decision 2026-10-16), so /projects says how many first.
describe("typeChangeMessage (#482)", () => {
    const { typeChangeMessage } = require("../../../static/project_archive_helpers.js");
    const projects = [
        { id: "p1", name: "Kitchen", type: "work", task_counts: { active: 3, done: 1 } },
        { id: "p2", name: "Garden", type: "work", task_counts: { active: 1, done: 0 } },
        { id: "p3", name: "Empty", type: "work", task_counts: { active: 0, done: 0 } },
        { id: "p4", name: "Home", type: "personal", task_counts: { active: 5, done: 0 } },
    ];
    const templates = [
        { id: "t1", project_id: "p1", is_active: true },
        { id: "t2", project_id: "p1", is_active: false },   // paused counts too
        { id: "t3", project_id: "p9", is_active: true },
    ];

    test("one project: names it, counts tasks and repeating tasks", () => {
        expect(typeChangeMessage(projects, ["p1"], "personal", templates))
            .toBe('4 tasks and 2 repeating tasks on "Kitchen" become Personal too.');
    });

    test("singular words", () => {
        expect(typeChangeMessage(projects, ["p2"], "personal", []))
            .toBe('1 task on "Garden" becomes Personal too.');
        expect(typeChangeMessage(
            [{ id: "p5", name: "Solo", type: "work", task_counts: { active: 0, done: 0 } }],
            ["p5"], "personal", [{ project_id: "p5", is_active: true }]))
            .toBe('1 repeating task on "Solo" becomes Personal too.');
    });

    test("several projects are counted together", () => {
        expect(typeChangeMessage(projects, ["p1", "p2"], "personal", templates))
            .toBe("5 tasks and 2 repeating tasks on 2 projects become Personal too.");
    });

    test("a project already of that type isn't counted", () => {
        expect(typeChangeMessage(projects, ["p2", "p4"], "personal", []))
            .toBe('1 task on "Garden" becomes Personal too.');
    });

    test("nothing would move: no message (the quiet cases)", () => {
        expect(typeChangeMessage(projects, ["p3"], "personal", templates)).toBe("");
        expect(typeChangeMessage(projects, ["p1"], "work", templates)).toBe("");
        expect(typeChangeMessage(projects, [], "personal", templates)).toBe("");
        expect(typeChangeMessage(null, ["p1"], "personal", null)).toBe("");
    });

    test("Work reads as Work", () => {
        expect(typeChangeMessage(projects, ["p4"], "work", []))
            .toBe('5 tasks on "Home" become Work too.');
    });
});
