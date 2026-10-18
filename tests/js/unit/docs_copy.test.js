/**
 * #504: Copy buttons on the Help page's Siri setup steps.
 *
 * Each button names a read-only field (data-copy-for); a click copies the
 * field's value through voiceTokenHelpers.copyText (#499, already tested:
 * clipboard first, else select the field so iOS shows its Copy menu) and
 * says what happened on the button.
 */
"use strict";

const { copyResultLabel, wireCopyButtons } = require("../../../static/docs_copy");

describe("copyResultLabel", () => {
    test("names each copyText result", () => {
        expect(copyResultLabel("copied")).toBe("Copied");
        expect(copyResultLabel("selected")).toBe("Selected — tap Copy");
        expect(copyResultLabel("failed")).toBe("Couldn't copy");
        expect(copyResultLabel(undefined)).toBe("Couldn't copy");
    });
});

function fakePage(fields) {
    const buttons = Object.keys(fields).map((id) => {
        const btn = {
            textContent: "Copy",
            handlers: {},
            getAttribute: (name) => (name === "data-copy-for" ? id : null),
            addEventListener(type, fn) { this.handlers[type] = fn; },
        };
        return btn;
    });
    const doc = {
        querySelectorAll: (sel) => (sel === "[data-copy-for]" ? buttons : []),
        getElementById: (id) => fields[id] || null,
    };
    return { doc, buttons };
}

describe("wireCopyButtons", () => {
    beforeEach(() => jest.useFakeTimers());
    afterEach(() => jest.useRealTimers());

    test("a click copies that button's field and says so, then resets", async () => {
        const field = { value: "https://example.test/api/voice-review/queue" };
        const { doc, buttons } = fakePage({ u1: field });
        const helpers = { copyText: jest.fn(() => Promise.resolve("copied")) };
        const env = { navigator: {}, document: doc };

        expect(wireCopyButtons(doc, helpers, env)).toBe(1);
        buttons[0].handlers.click();
        await Promise.resolve();
        await Promise.resolve();

        expect(helpers.copyText).toHaveBeenCalledWith(field.value, field, env);
        expect(buttons[0].textContent).toBe("Copied");
        jest.advanceTimersByTime(2500);
        expect(buttons[0].textContent).toBe("Copy");
    });

    test("a selected fallback tells you to tap Copy", async () => {
        const { doc, buttons } = fakePage({ u2: { value: "x" } });
        const helpers = { copyText: () => Promise.resolve("selected") };
        wireCopyButtons(doc, helpers, {});
        buttons[0].handlers.click();
        await Promise.resolve();
        await Promise.resolve();
        expect(buttons[0].textContent).toBe("Selected — tap Copy");
    });

    test("a button whose field is missing is skipped, not wired", () => {
        const { doc } = fakePage({ gone: undefined });
        const helpers = { copyText: jest.fn() };
        expect(wireCopyButtons(doc, helpers, {})).toBe(0);
    });

    test("without the helpers nothing is wired (the page still reads)", () => {
        const { doc } = fakePage({ u1: { value: "x" } });
        expect(wireCopyButtons(doc, null, {})).toBe(0);
    });
});
