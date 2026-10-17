/**
 * #501: a repeating task's start date in the task panel. Two rules:
 *
 * - repeatStartDateForSave: on a template that already exists, the panel
 *   showed its start date, so send whatever the field holds (blank = null,
 *   "start right away"). On a NEW repeat, a blank field is left out so the
 *   server keeps #147's default (the task's due date).
 * - repeatStartDatePrefill: picking a frequency on a task with no repeat
 *   yet fills Start on with the due date, so what you see is what's saved.
 */
"use strict";

const {
    repeatStartDateForSave,
    repeatStartDatePrefill,
} = require("../../../static/task_detail_payload");

describe("repeatStartDateForSave", () => {
    test("an existing template sends the field as it is", () => {
        expect(repeatStartDateForSave("2026-11-02", true)).toBe("2026-11-02");
    });
    test("an existing template with the field cleared sends null (clear it)", () => {
        expect(repeatStartDateForSave("", true)).toBeNull();
    });
    test("a new repeat with a date sends it", () => {
        expect(repeatStartDateForSave("2026-11-02", false)).toBe("2026-11-02");
    });
    test("a new repeat left blank sends nothing (server uses the due date)", () => {
        expect(repeatStartDateForSave("", false)).toBeUndefined();
    });
    test("junk is treated as blank", () => {
        expect(repeatStartDateForSave("not a date", true)).toBeNull();
        expect(repeatStartDateForSave(undefined, false)).toBeUndefined();
    });
});

describe("repeatStartDatePrefill", () => {
    test("a new repeat on a dated task starts on the due date", () => {
        expect(repeatStartDatePrefill("", false, "2026-10-12")).toBe("2026-10-12");
    });
    test("a new repeat on an undated task stays blank", () => {
        expect(repeatStartDatePrefill("", false, "")).toBe("");
    });
    test("what the user already typed is kept", () => {
        expect(repeatStartDatePrefill("2026-11-02", false, "2026-10-12")).toBe("2026-11-02");
    });
    test("an existing template is never prefilled (blank there means right away)", () => {
        expect(repeatStartDatePrefill("", true, "2026-10-12")).toBe("");
    });
});
