/**
 * #489: review-screen rows name their controls after the row's title.
 */
"use strict";

const { labelFor, name } = require("../../../static/row_label_helpers");

describe("labelFor", () => {
    test("Include and other purposes name the row's title", () => {
        expect(labelFor("Include", "Call the dentist", 0)).toBe("Include “Call the dentist”");
        expect(labelFor("Type", "Call the dentist", 0)).toBe("Type for “Call the dentist”");
        expect(labelFor("Due date", "  Call   Bob ", 3)).toBe("Due date for “Call Bob”");
    });

    test("the title box is named by its row number, not its own text", () => {
        expect(labelFor("Title", "Anything", 1)).toBe("Title of row 2");
    });

    test("an empty title falls back to the row number", () => {
        expect(labelFor("Include", "", 2)).toBe("Include row 3");
        expect(labelFor("Section", null, 0)).toBe("Section for row 1");
    });

    test("a very long title is cut to 80 characters", () => {
        const out = labelFor("Include", "x".repeat(300), 0);
        expect(out).toBe("Include “" + "x".repeat(79) + "…”");
    });
});

describe("name", () => {
    function fakeRow(els) {
        return { querySelectorAll: (sel) => els[sel] || [] };
    }
    function fakeEl() {
        const attrs = {};
        return { setAttribute: (k, v) => { attrs[k] = v; }, attrs };
    }

    test("labels every matched control and skips selectors with no match", () => {
        const cb = fakeEl();
        const sel1 = fakeEl();
        const sel2 = fakeEl();
        name(fakeRow({ "input[type=checkbox]": [cb], "select": [sel1, sel2] }), "Kitchen", 0, {
            "input[type=checkbox]": "Include", "select": "Type", ".missing": "Notes",
        });
        expect(cb.attrs["aria-label"]).toBe("Include “Kitchen”");
        expect(sel1.attrs["aria-label"]).toBe("Type for “Kitchen”");
        expect(sel2.attrs["aria-label"]).toBe("Type for “Kitchen”");
    });

    test("no row or no map does nothing", () => {
        expect(() => name(null, "t", 0, {})).not.toThrow();
        expect(() => name(fakeRow({}), "t", 0, null)).not.toThrow();
    });
});
