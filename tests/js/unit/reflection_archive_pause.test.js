/**
 * #364: a reflection's "Delete project / goal" row says which repeating
 * tasks applying it pauses. The server sends `archive_pauses`, keyed
 * "<entity>:<id>"; archivePauseNote picks the row's list and words it with
 * the same sentence /projects and /goals use.
 */
const H = require("../../../static/reflection_helpers.js");
const P = require("../../../static/project_archive_helpers.js");

const fmt = P.archiveConfirmMessage;
const del = (entity, id) => ({ op: "delete", entity, id, target: "x" });

describe("archivePauseNote", () => {
    test("a project delete names its templates, with the project's closing line", () => {
        const pauses = { "project:p1": ["Backup", "Water plants"] };
        expect(H.archivePauseNote(del("project", "p1"), pauses, fmt)).toBe(
            'This will pause 2 repeating tasks: "Backup", "Water plants". '
            + "They resume when you unarchive the project.");
    });

    test("a goal delete says the goal, one task reads 'It resumes'", () => {
        const pauses = { "goal:g1": ["Weekly review"] };
        expect(H.archivePauseNote(del("goal", "g1"), pauses, fmt)).toBe(
            'This will pause 1 repeating task: "Weekly review". '
            + "It resumes when you unarchive the goal.");
    });

    test("nothing to pause is the quiet case", () => {
        expect(H.archivePauseNote(del("project", "p1"), {}, fmt)).toBe("");
        expect(H.archivePauseNote(del("project", "p1"), { "project:p1": [] }, fmt)).toBe("");
        expect(H.archivePauseNote(del("project", "p1"), undefined, fmt)).toBe("");
    });

    test("only a project or goal delete gets a line", () => {
        const pauses = { "project:p1": ["Backup"], "task:p1": ["Backup"] };
        expect(H.archivePauseNote({ op: "update", entity: "project", id: "p1" }, pauses, fmt)).toBe("");
        expect(H.archivePauseNote(del("task", "p1"), pauses, fmt)).toBe("");
        expect(H.archivePauseNote({ op: "create", entity: "project", id: null }, pauses, fmt)).toBe("");
    });

    test("another row's list is never borrowed", () => {
        const pauses = { "goal:p1": ["Backup"] };
        expect(H.archivePauseNote(del("project", "p1"), pauses, fmt)).toBe("");
    });

    test("no formatter or no action → empty", () => {
        expect(H.archivePauseNote(del("project", "p1"), { "project:p1": ["a"] }, null)).toBe("");
        expect(H.archivePauseNote(null, { "project:p1": ["a"] }, fmt)).toBe("");
    });
});
