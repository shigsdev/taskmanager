/**
 * Jest unit tests for static/strength_forge_helpers.js (#287).
 *
 * These exercise the per-set logging form's pure logic — never a
 * string-match against the source (CLAUDE.md anti-pattern #3). The same
 * file runs in the browser (window.strengthForgeHelpers) and Node (require).
 */
const {
    defaultSetCount,
    buildSetsPayload,
    formatLastResist,
} = require("../../../static/strength_forge_helpers");

describe("defaultSetCount", () => {
    test("leading count before × marker", () => {
        expect(defaultSetCount("3 × 10")).toBe(3);
        expect(defaultSetCount("3 × 10 each side")).toBe(3);
    });

    test("leading count before 'sets' word", () => {
        expect(defaultSetCount("3 sets × 8 each side")).toBe(3);
        expect(defaultSetCount("2 sets of 12")).toBe(2);
    });

    test("leading count before x marker", () => {
        expect(defaultSetCount("4x12")).toBe(4);
    });

    test("time-based / rep-only strings default to 1", () => {
        expect(defaultSetCount("45s × 2 sides")).toBe(1); // 45 is a duration, not a set count
        expect(defaultSetCount("10 reps")).toBe(1);
        expect(defaultSetCount("4–6 cycles")).toBe(1);
        expect(defaultSetCount("No rest")).toBe(1);
    });

    test("blank / non-string defaults to 1", () => {
        expect(defaultSetCount("")).toBe(1);
        expect(defaultSetCount(undefined)).toBe(1);
        expect(defaultSetCount(null)).toBe(1);
        expect(defaultSetCount(3)).toBe(1);
    });

    test("clamps to 1..5", () => {
        expect(defaultSetCount("9 × 10")).toBe(5);
        expect(defaultSetCount("0 × 10")).toBe(1);
    });
});

describe("buildSetsPayload", () => {
    test("flattens exercises into per-set entries with 1-based set_number", () => {
        const out = buildSetsPayload([
            {
                exercise_id: "band-squat",
                name: "Band Assisted Squat",
                sets: [
                    { reps: "12", resistance: "Medium" },
                    { reps: "10", resistance: "Medium" },
                    { reps: "8", resistance: "Heavy" },
                ],
            },
        ]);
        expect(out).toHaveLength(3);
        expect(out[0]).toEqual({
            exercise_id: "band-squat",
            name: "Band Assisted Squat",
            set_number: 1,
            reps: 12,
            resistance: "Medium",
        });
        expect(out[2].set_number).toBe(3);
        expect(out[2].reps).toBe(8);
    });

    test("drops rows with neither reps nor resistance", () => {
        const out = buildSetsPayload([
            {
                exercise_id: "plank",
                name: "Plank",
                sets: [
                    { reps: "", resistance: "" },
                    { reps: "", resistance: "  " },
                    { reps: "", resistance: "Bodyweight" },
                ],
            },
        ]);
        expect(out).toHaveLength(1);
        expect(out[0].set_number).toBe(1); // renumbered after the blanks drop
        expect(out[0].reps).toBeNull();
        expect(out[0].resistance).toBe("Bodyweight");
    });

    test("reps-only row is kept (resistance optional)", () => {
        const out = buildSetsPayload([
            { exercise_id: "dead-bug", name: "Dead Bug", sets: [{ reps: "8", resistance: "" }] },
        ]);
        expect(out).toHaveLength(1);
        expect(out[0].reps).toBe(8);
        expect(out[0].resistance).toBe("");
    });

    test("invalid reps coerce to null (kept only if resistance present)", () => {
        const out = buildSetsPayload([
            { exercise_id: "x", name: "X", sets: [{ reps: "abc", resistance: "Light" }, { reps: "abc", resistance: "" }] },
        ]);
        expect(out).toHaveLength(1);
        expect(out[0].reps).toBeNull();
        expect(out[0].resistance).toBe("Light");
    });

    test("renumbers set_number per exercise independently", () => {
        const out = buildSetsPayload([
            { exercise_id: "a", name: "A", sets: [{ reps: "5", resistance: "" }, { reps: "5", resistance: "" }] },
            { exercise_id: "b", name: "B", sets: [{ reps: "3", resistance: "" }] },
        ]);
        expect(out.filter((s) => s.exercise_id === "a").map((s) => s.set_number)).toEqual([1, 2]);
        expect(out.filter((s) => s.exercise_id === "b").map((s) => s.set_number)).toEqual([1]);
    });

    test("non-array input returns empty array", () => {
        expect(buildSetsPayload(null)).toEqual([]);
        expect(buildSetsPayload(undefined)).toEqual([]);
    });
});

describe("formatLastResist", () => {
    test("resistance + reps + date", () => {
        expect(formatLastResist({ resistance: "Medium", reps: 12, date: "2026-07-05" }))
            .toBe("last: Medium · 12r · Jul 5");
    });

    test("null reps omits the reps part", () => {
        expect(formatLastResist({ resistance: "Heavy", reps: null, date: "2026-06-30" }))
            .toBe("last: Heavy · Jun 30");
    });

    test("missing date omits the date part", () => {
        expect(formatLastResist({ resistance: "Light", reps: 8, date: null }))
            .toBe("last: Light · 8r");
        expect(formatLastResist({ resistance: "Light", reps: 8 }))
            .toBe("last: Light · 8r");
    });

    test("no record or blank resistance returns empty string", () => {
        expect(formatLastResist(null)).toBe("");
        expect(formatLastResist(undefined)).toBe("");
        expect(formatLastResist({ resistance: "" })).toBe("");
        expect(formatLastResist({})).toBe("");
    });

    test("malformed date is dropped, not crashed", () => {
        expect(formatLastResist({ resistance: "Red band", reps: 10, date: "not-a-date" }))
            .toBe("last: Red band · 10r");
    });

    test("month boundaries map correctly", () => {
        expect(formatLastResist({ resistance: "X", reps: null, date: "2026-01-01" }))
            .toBe("last: X · Jan 1");
        expect(formatLastResist({ resistance: "X", reps: null, date: "2026-12-31" }))
            .toBe("last: X · Dec 31");
    });
});
