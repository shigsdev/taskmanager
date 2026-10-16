/**
 * #488: the /scan review's copy follows the kind the scan came back as.
 */
const { scanReviewCopy } = require("../../../static/scan_helpers");

describe("scanReviewCopy", () => {
    test("goals name goals, not the Inbox", () => {
        const c = scanReviewCopy("goals");
        expect(c.heading).toBe("Review Goal Candidates");
        expect(c.addAll).toBe("Add All to Goals");
        expect(c.addSelected).toBe("Add Selected to Goals");
        expect(c.hint).toMatch(/your goals\.$/);
    });

    test("projects name projects", () => {
        const c = scanReviewCopy("projects");
        expect(c.heading).toBe("Review Project Candidates");
        expect(c.addAll).toBe("Add All to Projects");
        expect(c.addSelected).toBe("Add Selected to Projects");
        expect(c.hint).toMatch(/your projects\.$/);
    });

    test("tasks keep the Inbox wording the page always had (the quiet case)", () => {
        expect(scanReviewCopy("tasks")).toEqual({
            heading: "Review Task Candidates",
            hint: "Edit, include, or exclude each candidate before adding to inbox.",
            addAll: "Add All to Inbox",
            addSelected: "Add Selected to Inbox",
        });
    });

    test("an unknown or missing kind reads as tasks", () => {
        expect(scanReviewCopy("whatever")).toEqual(scanReviewCopy("tasks"));
        expect(scanReviewCopy(undefined)).toEqual(scanReviewCopy("tasks"));
        expect(scanReviewCopy("constructor")).toEqual(scanReviewCopy("tasks"));
    });
});
