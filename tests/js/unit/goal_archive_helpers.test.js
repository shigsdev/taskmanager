/**
 * Jest tests for #349 — archive / unarchive a goal, and the guarded
 * permanent delete.
 *
 * Written before the DOM wiring, per anti-pattern #3: the interesting
 * part here is a set of branches that decide what a DESTRUCTIVE button
 * says and whether it is live, and a Playwright test that merely clicks
 * it would not pin any of them.
 *
 * The bug being closed is worth restating, because it is what the
 * assertions are defending. `delete_goal` has always been a soft delete
 * setting `is_active = false`, but the button said Delete, the board
 * hard-filtered to active goals with no filter control, and nothing
 * anywhere could unarchive. Pressing it made a goal permanently
 * invisible and unrecoverable from the UI while the row survived in the
 * database — and `delete_goal` clears `batch_id` deliberately, so even
 * the recycle-bin restore could not bring it back.
 *
 * Two rules are pinned here:
 *
 * 1. THE SAFE FALLBACK IS "HIDE". An unknown filter mode, or a goal
 *    carrying no `is_active` field, must not cause archived rows to
 *    appear or live rows to vanish.
 *
 * 2. A DESTRUCTIVE BUTTON NEVER DEFAULTS TO ENABLED. Unknown reference
 *    state leaves it disabled. Enabling on unknown state would offer to
 *    delete something that might still be referenced, which is exactly
 *    the failure the server-side guard exists to prevent.
 */
"use strict";

const {
    goalArchiveFilter,
    goalArchiveToggleLabel,
    goalReferenceSummary,
    goalHardDeleteState,
    goalHardDeleteConfirm,
} = require("../../../static/goal_archive_helpers");

const live = { id: "g1", title: "Land the DTCC role", is_active: true };
const dead = { id: "g2", title: "Old BAU duplicate", is_active: false };
const partial = { id: "g3", title: "From a partial payload" };   // no is_active

const NONE = { tasks: 0, projects: 0, recurring: 0, weekly_focus: 0 };

// --- the board filter -------------------------------------------------------

describe("goalArchiveFilter", () => {
    const all = [live, dead, partial];

    test("active hides archived goals", () => {
        expect(goalArchiveFilter(all, "active").map((g) => g.id))
            .toEqual(["g1", "g3"]);
    });

    test("archived shows only archived goals", () => {
        expect(goalArchiveFilter(all, "archived").map((g) => g.id))
            .toEqual(["g2"]);
    });

    test("all shows everything", () => {
        expect(goalArchiveFilter(all, "all")).toHaveLength(3);
    });

    test("all returns a copy, not the caller's array", () => {
        // goalsRender sorts the result in place; handing back the live
        // array would reorder goalsData as a side effect.
        const out = goalArchiveFilter(all, "all");
        out.push({ id: "x" });
        expect(all).toHaveLength(3);
    });

    test("an unknown mode falls back to active, not to all", () => {
        // Hiding archived rows is the safe failure. Showing them
        // silently is the bug this feature exists to fix.
        expect(goalArchiveFilter(all, "banana").map((g) => g.id))
            .toEqual(["g1", "g3"]);
        expect(goalArchiveFilter(all, undefined).map((g) => g.id))
            .toEqual(["g1", "g3"]);
    });

    test("a goal with no is_active field counts as active", () => {
        // A partial payload is a missing field, not an archived row —
        // treating it as archived would make live goals disappear.
        expect(goalArchiveFilter([partial], "active")).toHaveLength(1);
        expect(goalArchiveFilter([partial], "archived")).toHaveLength(0);
    });

    test("an empty or missing list is not a crash", () => {
        expect(goalArchiveFilter([], "all")).toEqual([]);
        expect(goalArchiveFilter(null, "active")).toEqual([]);
        expect(goalArchiveFilter(undefined, "archived")).toEqual([]);
    });
});

// --- the toggle label -------------------------------------------------------

describe("goalArchiveToggleLabel", () => {
    test("an active goal offers Archive", () => {
        expect(goalArchiveToggleLabel(live)).toBe("Archive");
    });

    test("an archived goal offers Unarchive", () => {
        expect(goalArchiveToggleLabel(dead)).toBe("Unarchive");
    });

    test("a partial payload offers Archive", () => {
        expect(goalArchiveToggleLabel(partial)).toBe("Archive");
        expect(goalArchiveToggleLabel(null)).toBe("Archive");
    });
});

// --- the reference sentence -------------------------------------------------

describe("goalReferenceSummary", () => {
    test("nothing pointing at it is an empty string", () => {
        expect(goalReferenceSummary(NONE)).toBe("");
        expect(goalReferenceSummary({})).toBe("");
        expect(goalReferenceSummary(null)).toBe("");
    });

    test("one kind reads on its own", () => {
        expect(goalReferenceSummary({ ...NONE, tasks: 3 })).toBe("3 tasks");
    });

    test("singular and plural both read correctly", () => {
        expect(goalReferenceSummary({ ...NONE, tasks: 1 })).toBe("1 task");
        expect(goalReferenceSummary({ ...NONE, projects: 1 })).toBe("1 project");
        expect(goalReferenceSummary({ ...NONE, recurring: 1 }))
            .toBe("1 repeating task");
        expect(goalReferenceSummary({ ...NONE, weekly_focus: 1 }))
            .toBe("1 weekly focus");
    });

    test("two kinds are joined with and", () => {
        expect(goalReferenceSummary({ ...NONE, tasks: 2, projects: 1 }))
            .toBe("2 tasks and 1 project");
    });

    test("three or more use commas then and", () => {
        expect(goalReferenceSummary({
            tasks: 5, projects: 2, recurring: 1, weekly_focus: 3,
        })).toBe("5 tasks, 2 projects, 1 repeating task and 3 weekly focuses");
    });

    test("order is fixed, not count-sorted", () => {
        // The sentence should read the same way every time rather than
        // reshuffling as counts change.
        expect(goalReferenceSummary({ ...NONE, weekly_focus: 9, tasks: 1 }))
            .toBe("1 task and 9 weekly focuses");
    });
});

// --- the destructive button -------------------------------------------------

describe("goalHardDeleteState", () => {
    test("an archived goal with nothing pointing at it is deletable", () => {
        const s = goalHardDeleteState(dead, NONE);
        expect(s.enabled).toBe(true);
        expect(s.reason).toBe("ok");
        expect(s.hint).toMatch(/nothing points at this goal/i);
    });

    test("an ACTIVE goal cannot be hard-deleted, and says why", () => {
        const s = goalHardDeleteState(live, NONE);
        expect(s.enabled).toBe(false);
        expect(s.reason).toBe("active");
        expect(s.hint).toMatch(/archive this goal first/i);
    });

    test("a referenced goal names what is in the way", () => {
        const s = goalHardDeleteState(dead, { ...NONE, tasks: 4, projects: 1 });
        expect(s.enabled).toBe(false);
        expect(s.reason).toBe("referenced");
        expect(s.hint).toContain("4 tasks and 1 project");
        expect(s.hint).toMatch(/pointing at nothing/i);
    });

    test("a single blocker reads as singular throughout", () => {
        // Phase 6 caught this rendering as "1 task still point at this
        // goal … clear them first". The assertions above all checked
        // the noun phrase and never the verb, so none of them failed.
        const s = goalHardDeleteState(dead, { ...NONE, tasks: 1 });
        expect(s.hint).toBe(
            "1 task still points at this goal. Move or clear it first — "
            + "deleting would leave it pointing at nothing.");
    });

    test("agreement follows the TOTAL rows, not the number of kinds", () => {
        // One task AND one project is two rows, so it reads plural even
        // though every individual count is 1.
        const s = goalHardDeleteState(dead, { ...NONE, tasks: 1, projects: 1 });
        expect(s.hint).toContain("1 task and 1 project still point at");
        expect(s.hint).toContain("clear them first");
    });

    test("a WeeklyFocus alone is enough to block it", () => {
        // The fourth and least visible goal foreign key. Its ondelete is
        // SET NULL, so leaving it out of the guard would silently empty
        // a past week's focus with nothing shown to the user.
        const s = goalHardDeleteState(dead, { ...NONE, weekly_focus: 1 });
        expect(s.enabled).toBe(false);
        expect(s.hint).toContain("1 weekly focus");
    });

    test("unknown reference state leaves the button DISABLED", () => {
        // Never default a destructive control to enabled on state you
        // have not actually checked.
        const s = goalHardDeleteState(dead, null);
        expect(s.enabled).toBe(false);
        expect(s.hint).toBeTruthy();
    });

    test("no goal selected is disabled and silent", () => {
        expect(goalHardDeleteState(null, NONE))
            .toEqual({ enabled: false, reason: "no-goal", hint: "" });
        expect(goalHardDeleteState({}, NONE).enabled).toBe(false);
    });

    test("a partial payload is treated as active, so not deletable", () => {
        expect(goalHardDeleteState(partial, NONE).reason).toBe("active");
    });

    test("the two gates are independent — active AND referenced", () => {
        // An active, referenced goal reports the archive step first:
        // it is the one the user can act on next.
        const s = goalHardDeleteState(live, { ...NONE, tasks: 9 });
        expect(s.enabled).toBe(false);
        expect(s.reason).toBe("active");
    });
});

describe("goalHardDeleteConfirm", () => {
    test("names the goal and says the recycle bin will not help", () => {
        const msg = goalHardDeleteConfirm(dead);
        expect(msg).toContain('Permanently delete "Old BAU duplicate"?');
        expect(msg).toMatch(/cannot be undone/i);
        expect(msg).toMatch(/recycle bin will not bring it back/i);
    });

    test("a missing title does not render undefined", () => {
        expect(goalHardDeleteConfirm(null)).toContain('"this goal"');
    });
});
