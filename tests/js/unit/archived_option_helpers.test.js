/**
 * @jest-environment jsdom
 *
 * Jest tests for #355 — an archived project/goal link must stay
 * representable in a dropdown that restores a stored value.
 *
 * The bug: every select that restores a stored project_id / goal_id was
 * populated from an ACTIVE-ONLY list. An archived stored value matched no
 * <option>, so the select read back "" and the save path wrote that
 * clearing to the database — on a save where the user edited nothing. On
 * the task detail panel the phantom diff also tripped the #148 revival
 * branch, resurrecting completed tasks onto the active board (270 such
 * tasks on prod when this was filed).
 *
 * Per CLAUDE.md anti-pattern #3 these assert OUTPUTS — the rows chosen,
 * the DOM actually rendered, the value actually read back, and the real
 * detailFormDiffersFromSnapshot verdict. No source-string matching, and
 * the round-trip drives the SHIPPED renderer rather than a paraphrase of
 * it, which is why renderValuePreservingOptions lives in the helper
 * instead of being copied into all five call sites.
 */
"use strict";

const {
    optionRowsPreservingValue,
    optionLabelForState,
    optionIsDisabled,
    renderValuePreservingOptions,
    splitByActive,
    OPTION_STATE_LIVE,
    OPTION_STATE_ARCHIVED,
    OPTION_STATE_MISSING,
} = require("../../../static/archived_option_helpers");

const { detailFormDiffersFromSnapshot } = require("../../../static/task_detail_payload");

// Mirrors the real shapes: two live work projects, one archived.
const LIVE = [
    { id: "live-1", name: "Reflection Prep", type: "work", is_active: true },
    { id: "live-2", name: "DTCC Onboarding", type: "work", is_active: true },
];
const ARCHIVED = [
    { id: "arch-cop", name: "Community of Practice", type: "work", is_active: false },
    { id: "arch-personal", name: "Matteo Birthday", type: "personal", is_active: false },
];

const nameOf = (row) => row.name;

/** Build a select with the same static placeholder the templates ship. */
function makeSelect(placeholder) {
    const sel = document.createElement("select");
    const none = document.createElement("option");
    none.value = "";
    none.textContent = placeholder || "— None —";
    sel.appendChild(none);
    document.body.appendChild(sel);
    return sel;
}

afterEach(() => {
    document.body.replaceChildren();
});

describe("optionRowsPreservingValue — which rows to render", () => {
    test("stored value is live: no extra row, list matches `live` exactly", () => {
        const rows = optionRowsPreservingValue({
            live: LIVE, archived: ARCHIVED, currentId: "live-2",
        });
        expect(rows.map((r) => r.row.id)).toEqual(["live-1", "live-2"]);
        expect(rows.every((r) => r.state === OPTION_STATE_LIVE)).toBe(true);
    });

    test("no stored value: no extra row", () => {
        const rows = optionRowsPreservingValue({
            live: LIVE, archived: ARCHIVED, currentId: "",
        });
        expect(rows.map((r) => r.row.id)).toEqual(["live-1", "live-2"]);
    });

    test("stored value is archived: appended once, tagged archived", () => {
        const rows = optionRowsPreservingValue({
            live: LIVE, archived: ARCHIVED, currentId: "arch-cop",
        });
        expect(rows.map((r) => r.row.id)).toEqual(["live-1", "live-2", "arch-cop"]);
        expect(rows[2].state).toBe(OPTION_STATE_ARCHIVED);
        // The real row comes back, so the caller can label it.
        expect(rows[2].row.name).toBe("Community of Practice");
    });

    test("stored value in neither list: appended as missing, id preserved", () => {
        const rows = optionRowsPreservingValue({
            live: LIVE, archived: ARCHIVED, currentId: "ghost-id",
        });
        expect(rows).toHaveLength(3);
        expect(rows[2].state).toBe(OPTION_STATE_MISSING);
        expect(rows[2].row.id).toBe("ghost-id");
    });

    test("archived stored value of the WRONG type is still kept", () => {
        // The caller type-filters `live`; the stored value must survive it.
        // This is #272's lesson generalised — a filter must never be able
        // to delete data by hiding it.
        const workOnly = LIVE.filter((p) => p.type === "work");
        const rows = optionRowsPreservingValue({
            live: workOnly, archived: ARCHIVED, currentId: "arch-personal",
        });
        expect(rows.map((r) => r.row.id)).toContain("arch-personal");
        expect(rows[rows.length - 1].state).toBe(OPTION_STATE_ARCHIVED);
    });

    test("appends exactly one row, never duplicates", () => {
        const rows = optionRowsPreservingValue({
            live: LIVE, archived: [...ARCHIVED, ...ARCHIVED], currentId: "arch-cop",
        });
        expect(rows.filter((r) => r.row.id === "arch-cop")).toHaveLength(1);
    });

    test("tolerates junk input", () => {
        expect(optionRowsPreservingValue()).toEqual([]);
        expect(optionRowsPreservingValue({})).toEqual([]);
        expect(optionRowsPreservingValue({ live: null, currentId: null })).toEqual([]);
        expect(
            optionRowsPreservingValue({ live: [null, { id: "a" }], currentId: "a" })
                .map((r) => r.row.id),
        ).toEqual(["a"]);
        // currentId set but no archived list → still preserved as missing.
        expect(
            optionRowsPreservingValue({ live: [], currentId: "x" })[0].state,
        ).toBe(OPTION_STATE_MISSING);
    });
});

describe("label + disabled rules", () => {
    test("live keeps the caller's label and stays selectable", () => {
        expect(optionLabelForState(OPTION_STATE_LIVE, "Reflection Prep"))
            .toBe("Reflection Prep");
        expect(optionIsDisabled(OPTION_STATE_LIVE)).toBe(false);
    });

    test("archived appends the suffix and is not selectable", () => {
        expect(optionLabelForState(OPTION_STATE_ARCHIVED, "Community of Practice"))
            .toBe("Community of Practice (archived)");
        expect(optionIsDisabled(OPTION_STATE_ARCHIVED)).toBe(true);
    });

    test("missing replaces the label entirely and is not selectable", () => {
        expect(optionLabelForState(OPTION_STATE_MISSING, "anything")).toBe("(unavailable)");
        expect(optionIsDisabled(OPTION_STATE_MISSING)).toBe(true);
    });

    test("the goal-side label format survives the suffix", () => {
        // Goals render `${title} (${category})`, projects render `name`.
        // The helper must not assume either.
        expect(optionLabelForState(OPTION_STATE_ARCHIVED, "AI Upskilling (work)"))
            .toBe("AI Upskilling (work) (archived)");
    });
});

describe("splitByActive", () => {
    test("splits an is_active=all response", () => {
        const { active, archived } = splitByActive([...LIVE, ...ARCHIVED]);
        expect(active.map((r) => r.id)).toEqual(["live-1", "live-2"]);
        expect(archived.map((r) => r.id)).toEqual(["arch-cop", "arch-personal"]);
    });

    test("a row with no is_active field counts as active", () => {
        // Defensive: the endpoints return active-only by default, so an
        // absent flag must not silently archive a live row.
        const { active, archived } = splitByActive([{ id: "x" }]);
        expect(active.map((r) => r.id)).toEqual(["x"]);
        expect(archived).toEqual([]);
    });

    test("tolerates junk input", () => {
        expect(splitByActive(null)).toEqual({ active: [], archived: [] });
        expect(splitByActive([null])).toEqual({ active: [], archived: [] });
    });
});

describe("renderValuePreservingOptions — the populate→set→read round-trip", () => {
    test("an archived stored value reads back as itself, NOT empty string", () => {
        // This is the assertion that fails without #355: the select used
        // to report "" and selectedIndex -1.
        const sel = makeSelect();
        const rows = optionRowsPreservingValue({
            live: LIVE, archived: ARCHIVED, currentId: "arch-cop",
        });
        const applied = renderValuePreservingOptions(sel, rows, nameOf, "arch-cop");

        expect(applied).toBe(true);
        expect(sel.value).toBe("arch-cop");
        expect(sel.selectedIndex).toBeGreaterThan(-1);
        expect(sel.options[sel.selectedIndex].textContent)
            .toBe("Community of Practice (archived)");
        expect(sel.options[sel.selectedIndex].disabled).toBe(true);
    });

    test("the placeholder option is preserved, generated options replaced", () => {
        const sel = makeSelect("(no goal)");
        renderValuePreservingOptions(
            sel, optionRowsPreservingValue({ live: LIVE, currentId: "" }), nameOf, "",
        );
        expect(sel.options[0].value).toBe("");
        expect(sel.options[0].textContent).toBe("(no goal)");
        expect([...sel.options].map((o) => o.value)).toEqual(["", "live-1", "live-2"]);

        // Re-render must not stack duplicates.
        renderValuePreservingOptions(
            sel, optionRowsPreservingValue({ live: LIVE, currentId: "" }), nameOf, "",
        );
        expect([...sel.options].map((o) => o.value)).toEqual(["", "live-1", "live-2"]);
    });

    test("value passed explicitly survives when the select starts EMPTY", () => {
        // The taskDetailOpen ordering (app.js:2503 populate, :2504 assign):
        // populate runs before the value is set, so the id cannot be read
        // off the select and MUST be passed in. That missing parameter on
        // taskDetailPopulateProjects was the actual hole in #355.
        const sel = makeSelect();
        expect(sel.value).toBe("");
        const rows = optionRowsPreservingValue({
            live: LIVE, archived: ARCHIVED, currentId: "arch-cop",
        });
        renderValuePreservingOptions(sel, rows, nameOf, "arch-cop");
        expect(sel.value).toBe("arch-cop");

        // And the subsequent explicit assignment app.js does is idempotent.
        sel.value = "arch-cop";
        expect(sel.value).toBe("arch-cop");
    });

    test("a background re-populate does not drop a value the select holds", () => {
        // The app.js:161 / :174 shape — loadProjects()/loadGoals() refresh
        // fires with no type argument while the panel is open. Before #355
        // this silently cleared an archived selection.
        const sel = makeSelect();
        renderValuePreservingOptions(
            sel,
            optionRowsPreservingValue({ live: LIVE, archived: ARCHIVED, currentId: "arch-cop" }),
            nameOf,
            "arch-cop",
        );
        expect(sel.value).toBe("arch-cop");

        const held = sel.value;  // what the call sites read for currentId
        renderValuePreservingOptions(
            sel,
            optionRowsPreservingValue({ live: LIVE, archived: ARCHIVED, currentId: held }),
            nameOf,
            held,
        );
        expect(sel.value).toBe("arch-cop");
    });

    test("a dangling id round-trips as (unavailable)", () => {
        const sel = makeSelect();
        const rows = optionRowsPreservingValue({
            live: LIVE, archived: ARCHIVED, currentId: "ghost-id",
        });
        renderValuePreservingOptions(sel, rows, nameOf, "ghost-id");
        expect(sel.value).toBe("ghost-id");
        expect(sel.options[sel.selectedIndex].textContent).toBe("(unavailable)");
    });

    test("clearing to the placeholder is still possible", () => {
        // Archived options are disabled, but "— None —" stays enabled so
        // deliberately unlinking a task is unaffected.
        const sel = makeSelect();
        renderValuePreservingOptions(
            sel,
            optionRowsPreservingValue({ live: LIVE, archived: ARCHIVED, currentId: "arch-cop" }),
            nameOf,
            "arch-cop",
        );
        sel.value = "";
        expect(sel.value).toBe("");
        expect(sel.options[0].disabled).toBe(false);
    });

    test("no-op on a missing select", () => {
        expect(renderValuePreservingOptions(null, [], nameOf, "x")).toBe(false);
    });
});

describe("#355 regression — no phantom diff, no completed-task resurrection", () => {
    // A real prod row: a COMPLETED task on the archived "Community of
    // Practice" project, still carrying an active goal.
    const task = {
        id: "t1",
        title: "run the april CoP session",
        tier: "backlog",
        type: "work",
        status: "archived",
        project_id: "arch-cop",
        goal_id: "goal-ai",
        due_date: null,
        url: null,
        notes: "",
        checklist: [],
    };

    /** Open the panel the way app.js does, then read the form back. */
    function openPanelAndReadForm() {
        const projSel = makeSelect();
        const goalSel = makeSelect();
        renderValuePreservingOptions(
            projSel,
            optionRowsPreservingValue({
                live: LIVE, archived: ARCHIVED, currentId: task.project_id,
            }),
            nameOf,
            task.project_id,
        );
        projSel.value = task.project_id || "";
        renderValuePreservingOptions(
            goalSel,
            optionRowsPreservingValue({
                live: [{ id: "goal-ai", title: "AI Upskilling", category: "work" }],
                archived: [],
                currentId: task.goal_id,
            }),
            (g) => `${g.title} (${g.category})`,
            task.goal_id,
        );
        goalSel.value = task.goal_id || "";
        return {
            title: task.title,
            tier: task.tier,
            type: task.type,
            project_id: projSel.value,
            goal_id: goalSel.value,
            due_date: "",
            url: "",
            notes: "",
            checklist: [],
            repeat: null,
        };
    }

    test("opening and saving with no edits reports NO difference", () => {
        // Before #355 this was `true` — a phantom project_id diff — which
        // tripped the #148 revival branch and sent status: "active",
        // defeating the exact guard #148's comment says it provides.
        const form = openPanelAndReadForm();
        expect(form.project_id).toBe("arch-cop");
        expect(detailFormDiffersFromSnapshot(form, task)).toBe(false);
    });

    test("a real edit is still detected", () => {
        // Guard against over-fixing: the diff must not go permanently false.
        const form = openPanelAndReadForm();
        form.title = "run the MAY CoP session";
        expect(detailFormDiffersFromSnapshot(form, task)).toBe(true);
    });

    test("deliberately clearing the archived project IS a difference", () => {
        const form = openPanelAndReadForm();
        form.project_id = "";
        expect(detailFormDiffersFromSnapshot(form, task)).toBe(true);
    });
});
