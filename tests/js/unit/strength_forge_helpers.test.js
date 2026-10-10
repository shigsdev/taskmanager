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
    usesResistance,
    isDraftFresh,
    planTypesForRole,
    exerciseSearchLinks,
    isPerSide,
    summarizeSets,
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

describe("usesResistance", () => {
    const catalog = {
        "band-squat": { resist: true },
        "plank": { safe: "back-safe" },        // no resist key
        "glute-bridge": { resist: false },      // bodyweight default
        "dead-bug": {},
    };

    test("catalog resist:true → true", () => {
        expect(usesResistance({ id: "band-squat" }, catalog)).toBe(true);
    });

    test("catalog without resist / resist:false → false", () => {
        expect(usesResistance({ id: "plank" }, catalog)).toBe(false);
        expect(usesResistance({ id: "glute-bridge" }, catalog)).toBe(false);
        expect(usesResistance({ id: "dead-bug" }, catalog)).toBe(false);
    });

    test("item.resist override wins over the catalog", () => {
        // Band Glute Bridge: catalog says bodyweight, plan item adds a band.
        expect(usesResistance({ id: "glute-bridge", resist: true }, catalog)).toBe(true);
        // …and the reverse override also wins.
        expect(usesResistance({ id: "band-squat", resist: false }, catalog)).toBe(false);
    });

    test("unknown id, null item, or missing catalog → false", () => {
        expect(usesResistance({ id: "nope" }, catalog)).toBe(false);
        expect(usesResistance(null, catalog)).toBe(false);
        expect(usesResistance({ id: "band-squat" }, undefined)).toBe(false);
    });
});

describe("isDraftFresh", () => {
    const now = 1_000_000_000_000;

    test("within the default 24h window → fresh", () => {
        expect(isDraftFresh(now - 60 * 1000, now)).toBe(true);          // 1 min ago
        expect(isDraftFresh(now - 23 * 3600 * 1000, now)).toBe(true);   // 23h ago
    });

    test("older than 24h → stale", () => {
        expect(isDraftFresh(now - 25 * 3600 * 1000, now)).toBe(false);
    });

    test("custom maxHours honored", () => {
        expect(isDraftFresh(now - 5 * 3600 * 1000, now, 2)).toBe(false);
        expect(isDraftFresh(now - 1 * 3600 * 1000, now, 2)).toBe(true);
    });

    test("negative age (clock skew) → keep rather than lose work", () => {
        expect(isDraftFresh(now + 5000, now)).toBe(true);
    });

    test("non-finite / missing timestamps → stale", () => {
        expect(isDraftFresh(undefined, now)).toBe(false);
        expect(isDraftFresh(now, undefined)).toBe(false);
        expect(isDraftFresh(NaN, now)).toBe(false);
    });
});

describe("planTypesForRole (#313 — full-plan print)", () => {
    test("band → both workouts, in order", () => {
        expect(planTypesForRole("band")).toEqual(["band-a", "band-b"]);
    });

    test("mil → all three sessions, in order", () => {
        expect(planTypesForRole("mil")).toEqual(["mil-1", "mil-2", "mil-3"]);
    });

    test("iso → all six one-muscle sessions, in order (#315)", () => {
        expect(planTypesForRole("iso")).toEqual([
            "iso-chest", "iso-back", "iso-shoulders",
            "iso-biceps", "iso-triceps", "iso-legs",
        ]);
    });

    test("split → the three training days, in order (#320)", () => {
        expect(planTypesForRole("split")).toEqual(["split-1", "split-2", "split-3"]);
    });

    test("split excludes the rest day — it is schedule-only (#320)", () => {
        expect(planTypesForRole("split")).not.toContain("split-4");
        expect(planTypesForRole("split")).toHaveLength(3);
    });

    test("unknown / missing role → empty list (button falls back to current day)", () => {
        expect(planTypesForRole("flare")).toEqual([]);
        expect(planTypesForRole("")).toEqual([]);
        expect(planTypesForRole(undefined)).toEqual([]);
        expect(planTypesForRole(null)).toEqual([]);
    });

    test("every returned key is a real plan label (no drift vs PLAN_LABELS_JS keys)", () => {
        // The print sheet looks each key up in PLAN_LABELS_JS; guard the two
        // lists can't drift. These are the labeled plan types the app ships.
        const known = new Set([
            "band-a", "band-b", "mil-1", "mil-2", "mil-3",
            "iso-chest", "iso-back", "iso-shoulders",
            "iso-biceps", "iso-triceps", "iso-legs",
            "split-1", "split-2", "split-3",
        ]);
        for (const role of ["band", "mil", "iso", "split"]) {
            for (const key of planTypesForRole(role)) {
                expect(known.has(key)).toBe(true);
            }
        }
    });
});


// #409: the modal's "Photos — Google" and "Videos — YouTube" links.
describe("exerciseSearchLinks", () => {
    test("Google Images uses udm=2 (tbm=isch is legacy) with the query as-is", () => {
        const { images } = exerciseSearchLinks("resistance band face pull");
        const u = new URL(images);
        expect(u.origin + u.pathname).toBe("https://www.google.com/search");
        expect(u.searchParams.get("q")).toBe("resistance band face pull");
        expect(u.searchParams.get("udm")).toBe("2");
        expect(u.searchParams.has("tbm")).toBe(false);
    });

    test("nothing is appended to the image query (no doubled words)", () => {
        const q = new URL(exerciseSearchLinks("glute bridge form").images).searchParams.get("q");
        expect(q).toBe("glute bridge form");
    });

    test("YouTube searches 'how to <query>'", () => {
        const u = new URL(exerciseSearchLinks("pike push up").video);
        expect(u.origin + u.pathname).toBe("https://www.youtube.com/results");
        expect(u.searchParams.get("search_query")).toBe("how to pike push up");
    });

    test("'how to' is not doubled when the query already starts with it", () => {
        const u = new URL(exerciseSearchLinks("How to box breathe").video);
        expect(u.searchParams.get("search_query")).toBe("How to box breathe");
    });

    test("whitespace is collapsed and special characters are encoded", () => {
        const links = exerciseSearchLinks("  90/90   hip & stretch ");
        expect(new URL(links.images).searchParams.get("q")).toBe("90/90 hip & stretch");
        expect(links.images).toContain("90%2F90");
        expect(links.images).toContain("%26");
    });

    test("an empty or missing query gives no links", () => {
        expect(exerciseSearchLinks("")).toBeNull();
        expect(exerciseSearchLinks("   ")).toBeNull();
        expect(exerciseSearchLinks(null)).toBeNull();
        expect(exerciseSearchLinks(undefined)).toBeNull();
    });
});


// #410: per-side exercises log Left + Right reps with one shared band.
describe("isPerSide", () => {
    const catalog = { "pallof-press": { perSide: true }, "band-squat": {} };
    test("catalog flag decides", () => {
        expect(isPerSide({ id: "pallof-press" }, catalog)).toBe(true);
        expect(isPerSide({ id: "band-squat" }, catalog)).toBe(false);
    });
    test("an item-level flag wins; unknown ids and bad input are bilateral", () => {
        expect(isPerSide({ id: "band-squat", perSide: true }, catalog)).toBe(true);
        expect(isPerSide({ id: "nope" }, catalog)).toBe(false);
        expect(isPerSide(null, catalog)).toBe(false);
        expect(isPerSide({ id: "pallof-press" }, null)).toBe(false);
    });
});

describe("buildSetsPayload — per-side rows", () => {
    const ex = (sets) => [{ exercise_id: "pallof-press", name: "Pallof Press", sets }];

    test("both sides → an L and an R entry sharing the set number and band", () => {
        expect(buildSetsPayload(ex([{ repsL: "10", repsR: "9", resistance: " Medium " }]))).toEqual([
            { exercise_id: "pallof-press", name: "Pallof Press", set_number: 1, side: "L", reps: 10, resistance: "Medium" },
            { exercise_id: "pallof-press", name: "Pallof Press", set_number: 1, side: "R", reps: 9, resistance: "Medium" },
        ]);
    });

    test("only one side filled → just that side", () => {
        const out = buildSetsPayload(ex([{ repsL: "", repsR: "8", resistance: "" }]));
        expect(out).toEqual([
            { exercise_id: "pallof-press", name: "Pallof Press", set_number: 1, side: "R", reps: 8, resistance: "" },
        ]);
    });

    test("resistance but no reps → one side-less entry (keeps the band reference)", () => {
        const out = buildSetsPayload(ex([{ repsL: "", repsR: "", resistance: "Heavy" }]));
        expect(out).toEqual([
            { exercise_id: "pallof-press", name: "Pallof Press", set_number: 1, reps: null, resistance: "Heavy" },
        ]);
    });

    test("blank per-side rows are skipped and set numbers stay dense", () => {
        const out = buildSetsPayload(ex([
            { repsL: "", repsR: "", resistance: "" },
            { repsL: "10", repsR: "10", resistance: "" },
        ]));
        expect(out.map((e) => [e.set_number, e.side])).toEqual([[1, "L"], [1, "R"]]);
    });

    test("bilateral rows still produce a single side-less entry", () => {
        const out = buildSetsPayload([{ exercise_id: "band-squat", name: "Squat", sets: [{ reps: "12", resistance: "Light" }] }]);
        expect(out).toEqual([{ exercise_id: "band-squat", name: "Squat", set_number: 1, reps: 12, resistance: "Light" }]);
        expect("side" in out[0]).toBe(false);
    });
});

describe("summarizeSets", () => {
    test("pairs L and R of the same set", () => {
        expect(summarizeSets([
            { set_number: 1, side: "L", reps: 10, resistance: "Medium" },
            { set_number: 1, side: "R", reps: 9, resistance: "Medium" },
            { set_number: 2, side: "L", reps: 10, resistance: "Medium" },
            { set_number: 2, side: "R", reps: 10, resistance: "Medium" },
        ])).toBe("L 10 · R 9 @ Medium, L 10 · R 10 @ Medium");
    });

    test("one side only", () => {
        expect(summarizeSets([{ set_number: 1, side: "R", reps: 8, resistance: "" }])).toBe("R 8");
    });

    test("bilateral and legacy rows keep the old format", () => {
        expect(summarizeSets([
            { set_number: 1, reps: 12, resistance: "Light" },
            { set_number: 2, reps: null, resistance: "Heavy" },
            { set_number: 3, side: null, reps: 10, resistance: "" },
        ])).toBe("12 reps @ Light, Heavy, 10 reps");
    });

    test("an empty row shows a dash; no rows → empty string", () => {
        expect(summarizeSets([{ set_number: 1, reps: null, resistance: "" }])).toBe("—");
        expect(summarizeSets([])).toBe("");
        expect(summarizeSets(null)).toBe("");
    });
});
