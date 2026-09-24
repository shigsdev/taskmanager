/**
 * #339 - naming a reflection sitting.
 *
 * The bug: history rows read `iso_week - date - input_mode`, which is
 * byte-identical for two reflections written on the same day in the same
 * mode. A user who had done a throwaway test and then a real multi-hour
 * session could not tell the two rows apart.
 *
 * The load-bearing property here is DISTINCTNESS, not a particular
 * string, so that is what these assert - and they build expectations
 * from the same Date API the helper uses, rather than hardcoding a
 * clock-time that would only pass in one timezone.
 */
"use strict";

const H = require("../../../static/reflection_helpers");

const AT = (iso) => ({
    iso_week: "2026-W39", created_at: iso, input_mode: "typed",
});

describe("reflectionLabel - the generated fallback", () => {
    test("two sittings on the SAME DAY get different labels", () => {
        // This is the entire bug.
        const morning = H.reflectionLabel(AT("2026-09-24T09:15:00Z"));
        const evening = H.reflectionLabel(AT("2026-09-24T21:40:00Z"));
        expect(morning).not.toBe(evening);
    });

    test("the label carries week, date, time and mode", () => {
        const out = H.reflectionLabel(AT("2026-09-24T09:15:00Z"));
        expect(out).toMatch(/^2026-W39 · \d{4}-\d{2}-\d{2} \d{2}:\d{2} · typed$/);
    });

    test("date and time come from the same instant", () => {
        // Slicing the ISO prefix for the date and reading a local clock
        // for the time would disagree across midnight in some zones.
        const iso = "2026-09-24T23:50:00Z";
        const d = new Date(iso);
        const p = (n) => String(n).padStart(2, "0");
        expect(H.reflectionLabel(AT(iso))).toContain(
            `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} `
            + `${p(d.getHours())}:${p(d.getMinutes())}`
        );
    });

    test("voice and typed are distinguished", () => {
        const r = AT("2026-09-24T09:15:00Z");
        expect(H.reflectionLabel({ ...r, input_mode: "voice" })).toContain("voice");
        expect(H.reflectionLabel(r)).toContain("typed");
    });

    test("a missing mode falls back to typed rather than blank", () => {
        expect(H.reflectionLabel({ iso_week: "2026-W39" })).toContain("typed");
    });

    test("an unparseable timestamp degrades without producing NaN", () => {
        const out = H.reflectionLabel({
            iso_week: "2026-W39", created_at: "not a date", input_mode: "typed",
        });
        expect(out).toBe("2026-W39 · typed");
        expect(out).not.toMatch(/NaN/);
    });

    test("junk input returns empty rather than throwing", () => {
        [null, undefined, "str", 7].forEach((bad) => {
            expect(H.reflectionLabel(bad)).toBe("");
        });
    });
});

describe("reflectionLabel - a user-given title wins", () => {
    test("the title replaces the whole generated label", () => {
        expect(H.reflectionLabel({ ...AT("2026-09-24T09:15:00Z"),
            title: "DTCC week 1 plan" })).toBe("DTCC week 1 plan");
    });

    test("surrounding whitespace is trimmed", () => {
        expect(H.reflectionLabel({ ...AT("2026-09-24T09:15:00Z"),
            title: "   Handover notes   " })).toBe("Handover notes");
    });

    test("a whitespace-only title is NOT a name", () => {
        // Otherwise a stray space renders as a blank row label.
        const out = H.reflectionLabel({ ...AT("2026-09-24T09:15:00Z"),
            title: "   " });
        expect(out).toContain("2026-W39");
    });

    test("a non-string title is ignored", () => {
        const out = H.reflectionLabel({ ...AT("2026-09-24T09:15:00Z"), title: 42 });
        expect(out).toContain("2026-W39");
    });
});

describe("reflectionIsNamed", () => {
    test("true only for a real name", () => {
        expect(H.reflectionIsNamed({ title: "Week 1" })).toBe(true);
    });
    test("false for empty, whitespace, missing, and junk", () => {
        [{ title: "" }, { title: "  " }, {}, null, undefined, { title: 1 }]
            .forEach((r) => expect(H.reflectionIsNamed(r)).toBe(false));
    });
});
