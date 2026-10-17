/**
 * #361: one rule for a project / goal link shown read-only — a stored link
 * is shown, and an archived target reads "<name> (archived)". linkLabel is
 * the one definition every surface calls (the board card badges, the
 * /projects card's goal line, /recurring's rows, the Work-view group header).
 */
const H = require("../../../static/archived_option_helpers.js");
const F = require("../../../static/filter_helpers.js");

const live = { id: "p1", name: "Kitchen", is_active: true };
const gone = { id: "p2", name: "Garage", is_active: false };
const name = (p) => p.name;

describe("linkLabel", () => {
    test("a live link reads its name", () => {
        expect(H.linkLabel("p1", [live, gone], name)).toEqual({ text: "Kitchen", archived: false });
    });

    test("an archived link reads '<name> (archived)'", () => {
        expect(H.linkLabel("p2", [live, gone], name)).toEqual({ text: "Garage (archived)", archived: true });
        expect(H.linkLabel("p2", [gone], name).text.endsWith(H.ARCHIVED_SUFFIX)).toBe(true);
    });

    test("a row with no is_active field counts as live (a partial payload)", () => {
        expect(H.linkLabel("p3", [{ id: "p3", name: "Shed" }], name)).toEqual({ text: "Shed", archived: false });
    });

    test("no id, an unknown id or an empty name → null (the caller decides)", () => {
        expect(H.linkLabel(null, [live], name)).toBeNull();
        expect(H.linkLabel("", [live], name)).toBeNull();
        expect(H.linkLabel("zz", [live, gone], name)).toBeNull();
        expect(H.linkLabel("p1", [{ id: "p1", name: "" }], name)).toBeNull();
        expect(H.linkLabel("p1", null, name)).toBeNull();
        expect(H.linkLabel("p1", [live], null)).toBeNull();
    });

    test("goals label by title the same way", () => {
        const g = { id: "g1", title: "Fitness", is_active: false };
        expect(H.linkLabel("g1", [g], (x) => x.title).text).toBe("Fitness (archived)");
    });
});

describe("groupTasksByProject uses the same suffix", () => {
    test("an archived project's group header", () => {
        const groups = F.groupTasksByProject(
            [{ id: "t1", project_id: "p2" }], [live], [gone]);
        expect(groups[0].label).toBe("Garage" + H.ARCHIVED_SUFFIX);
        expect(groups[0].archived).toBe(true);
    });
});
