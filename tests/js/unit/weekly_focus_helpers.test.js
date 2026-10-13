/**
 * Jest tests for #441 — the Weekly Focus slots no longer eat typing.
 *
 * Every save used to redraw all the slots, so text typed in the next slot
 * while the first one saved was lost along with focus. The panel now
 * updates in place; these decide what each input shows after an answer
 * and whether a blur has anything to send.
 */
const { slotInputValue, slotNeedsSave } = require("../../../static/weekly_focus_helpers.js");

describe("slotInputValue (#441)", () => {
    test("an untouched input takes the server's text", () => {
        expect(slotInputValue({ value: "old", synced: "old", serverText: "new", focused: false }))
            .toBe("new");
    });

    test("an empty untouched input takes the server's text", () => {
        expect(slotInputValue({ value: "", synced: "", serverText: "Ship it", focused: false }))
            .toBe("Ship it");
    });

    test("an input with focus keeps what is being typed", () => {
        expect(slotInputValue({ value: "half-typ", synced: "", serverText: "", focused: true }))
            .toBe("half-typ");
        // Even when it is untouched: the caret must not jump.
        expect(slotInputValue({ value: "same", synced: "same", serverText: "other", focused: true }))
            .toBe("same");
    });

    test("an edit not yet saved is kept when focus has moved on", () => {
        expect(slotInputValue({ value: "edited", synced: "first", serverText: "first", focused: false }))
            .toBe("edited");
    });

    test("the text just saved, untrimmed, takes the server's trimmed text", () => {
        expect(slotInputValue({ value: "Ship it ", synced: "", serverText: "Ship it", focused: false }))
            .toBe("Ship it");
    });

    test("a cleared slot empties an untouched input", () => {
        expect(slotInputValue({ value: "gone", synced: "gone", serverText: "", focused: false }))
            .toBe("");
    });

    test("missing fields read as empty", () => {
        expect(slotInputValue({ focused: false })).toBe("");
        expect(slotInputValue({ value: "x", focused: false })).toBe("x");
    });
});

describe("slotNeedsSave (#441)", () => {
    const row = { text: "Ship it", goal_id: "g1" };

    test("nothing changed sends nothing", () => {
        expect(slotNeedsSave(row, "Ship it", "g1")).toBe("none");
    });

    test("an empty slot left empty sends nothing", () => {
        expect(slotNeedsSave(null, "", null)).toBe("none");
    });

    test("new text on an empty slot saves", () => {
        expect(slotNeedsSave(null, "New focus", null)).toBe("save");
    });

    test("changed text saves", () => {
        expect(slotNeedsSave(row, "Ship it today", "g1")).toBe("save");
    });

    test("a changed goal saves, and so does dropping it", () => {
        expect(slotNeedsSave(row, "Ship it", "g2")).toBe("save");
        expect(slotNeedsSave(row, "Ship it", null)).toBe("save");
        expect(slotNeedsSave({ text: "Ship it", goal_id: null }, "Ship it", "g1")).toBe("save");
    });

    test("no goal on either side is no change", () => {
        expect(slotNeedsSave({ text: "Ship it", goal_id: null }, "Ship it", null)).toBe("none");
        expect(slotNeedsSave({ text: "Ship it" }, "Ship it", "")).toBe("none");
    });

    test("emptying a saved slot clears it", () => {
        expect(slotNeedsSave(row, "", "g1")).toBe("clear");
    });
});
