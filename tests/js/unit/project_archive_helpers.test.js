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

    test("one template uses the singular", () => {
        expect(archiveConfirmMessage([{ title: "A" }])).toBe(
            `This will pause 1 repeating task: "A". ${TAIL}`,
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
            `This will pause 1 repeating task: "say "hi" <b>now</b>". ${TAIL}`,
        );
    });

    // #369: the Settings import-undo confirm reuses this builder with its
    // own tail; /projects keeps the default.
    describe("optional tail (#369)", () => {
        const UNDO_TAIL = "They resume if you restore this import from the Recycle Bin.";

        test("a custom tail replaces the project tail", () => {
            expect(archiveConfirmMessage([{ title: "A" }], UNDO_TAIL)).toBe(
                `This will pause 1 repeating task: "A". ${UNDO_TAIL}`,
            );
        });

        test("omitted or empty tail keeps the project tail", () => {
            expect(archiveConfirmMessage([{ title: "A" }])).toBe(
                `This will pause 1 repeating task: "A". ${TAIL}`,
            );
            expect(archiveConfirmMessage([{ title: "A" }], "")).toBe(
                `This will pause 1 repeating task: "A". ${TAIL}`,
            );
        });

        test("nothing pausing is still \"\" with a tail", () => {
            expect(archiveConfirmMessage([], UNDO_TAIL)).toBe("");
            expect(archiveConfirmMessage(undefined, UNDO_TAIL)).toBe("");
        });
    });
});
