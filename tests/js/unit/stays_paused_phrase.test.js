/**
 * #373: Purge and Empty Bin name the repeating tasks that stay paused.
 *
 * A purge clears the "resume when unarchived" marker for the projects and
 * goals it deletes, so a template the undo paused never comes back on its
 * own. The server lists them (list_bin / bin_summary `stays_paused`); this
 * phrase is what the dialog says. None = "" so the quiet case reads exactly
 * as before.
 */
"use strict";

const { staysPausedPhrase } = require("../../../static/recycle_bin_helpers");

const t = (title) => ({ id: title, title });

describe("staysPausedPhrase (#373)", () => {
    test("none, missing or not a list says nothing", () => {
        expect(staysPausedPhrase([], "purge")).toBe("");
        expect(staysPausedPhrase(undefined, "purge")).toBe("");
        expect(staysPausedPhrase(null, "empty")).toBe("");
        expect(staysPausedPhrase("x", "purge")).toBe("");
    });

    test("one, on a batch", () => {
        expect(staysPausedPhrase([t("Water plants")], "purge")).toBe(
            "1 repeating task on it stays paused: \"Water plants\". " +
            "Resume it on Recurring if you still want it.");
    });

    test("many, on a batch", () => {
        expect(staysPausedPhrase([t("A"), t("B")], "purge")).toBe(
            "2 repeating tasks on it stay paused: \"A\", \"B\". " +
            "Resume them on Recurring if you still want them.");
    });

    test("Empty Bin reads 'on them'", () => {
        expect(staysPausedPhrase([t("A")], "empty")).toBe(
            "1 repeating task on them stays paused: \"A\". " +
            "Resume it on Recurring if you still want it.");
    });

    test("names five, then counts the rest (as #369's confirm)", () => {
        const list = ["a", "b", "c", "d", "e", "f", "g"].map(t);
        expect(staysPausedPhrase(list, "purge")).toBe(
            "7 repeating tasks on it stay paused: \"a\", \"b\", \"c\", \"d\", \"e\" and 2 more. " +
            "Resume them on Recurring if you still want them.");
    });
});
