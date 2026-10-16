/**
 * Jest tests for reflection_helpers (#165 frontend).
 *
 * Per CLAUDE.md anti-pattern #3, the branchy client-side logic for the
 * Weekly Reflection review screen is exercised here against its OUTPUTS
 * — never string-matched in prod smoke. Covers:
 *   - default check state per bucket
 *   - action label composition
 *   - change-diff summarization (incl. empty→value)
 *   - focus-candidate derivation (priority, entity/op filter, dedupe, cap)
 *   - confirm-summary humanization (incl. errors)
 *   - selection filtering by checked-map
 */
"use strict";

const {
    defaultChecked,
    actionLabel,
    changeSummary,
    focusCandidates,
    applySummaryText,
    selectedActions,
} = require("../../../static/reflection_helpers");

describe("defaultChecked", () => {
    test("explicit bucket defaults checked", () => {
        expect(defaultChecked("explicit")).toBe(true);
    });
    test("suggested bucket defaults unchecked", () => {
        expect(defaultChecked("suggested")).toBe(false);
    });
    test("unknown bucket is unchecked", () => {
        expect(defaultChecked("whatever")).toBe(false);
    });
});

describe("actionLabel", () => {
    test("create task with target", () => {
        expect(actionLabel({ op: "create", entity: "task", target: "Ship auth" }))
            .toBe("Create task: Ship auth");
    });
    test("delete project with target", () => {
        expect(actionLabel({ op: "delete", entity: "project", target: "Old CSV" }))
            .toBe("Delete project: Old CSV");
    });
    test("missing target omits colon", () => {
        expect(actionLabel({ op: "update", entity: "goal" }))
            .toBe("Update goal");
    });
    test("non-object → empty string", () => {
        expect(actionLabel(null)).toBe("");
    });
});

describe("changeSummary", () => {
    test("formats from → to pairs", () => {
        expect(changeSummary([
            { field: "tier", from: "backlog", to: "today" },
            { field: "type", from: "work", to: "personal" },
        ])).toBe("tier: backlog → today; type: work → personal");
    });
    test("blank from renders as ∅", () => {
        expect(changeSummary([{ field: "status", from: "", to: "archived" }]))
            .toBe("status: ∅ → archived");
    });
    test("empty / non-array → empty string", () => {
        expect(changeSummary([])).toBe("");
        expect(changeSummary(undefined)).toBe("");
    });
});

describe("focusCandidates", () => {
    const proposed = {
        explicit: [
            { op: "create", entity: "task", target: "Finish calendar redesign" },
            { op: "delete", entity: "project", target: "Old CSV importer" },
            { op: "update", entity: "goal", target: "Ship v2" },
        ],
        suggested: [
            { op: "create", entity: "task", target: "Triage stale backlog" },
            { op: "update", entity: "project", target: "Infra cleanup" },
        ],
    };

    test("explicit before suggested, task/goal create/update only", () => {
        expect(focusCandidates(proposed, 5)).toEqual([
            "Finish calendar redesign",
            "Ship v2",
            "Triage stale backlog",
        ]);
    });
    test("caps at max", () => {
        expect(focusCandidates(proposed, 2)).toEqual([
            "Finish calendar redesign",
            "Ship v2",
        ]);
    });
    test("dedupes case-insensitively", () => {
        const dup = {
            explicit: [{ op: "create", entity: "task", target: "Do X" }],
            suggested: [{ op: "update", entity: "task", target: "do x" }],
        };
        expect(focusCandidates(dup, 5)).toEqual(["Do X"]);
    });
    test("default cap is 3 when max invalid", () => {
        const many = {
            explicit: [1, 2, 3, 4, 5].map((n) => ({
                op: "create", entity: "task", target: "T" + n,
            })),
            suggested: [],
        };
        expect(focusCandidates(many, undefined)).toHaveLength(3);
    });
    test("empty proposed → empty array", () => {
        expect(focusCandidates({}, 3)).toEqual([]);
        expect(focusCandidates(null, 3)).toEqual([]);
    });
});

describe("applySummaryText", () => {
    test("created + updated + errors", () => {
        expect(applySummaryText({
            created: { task: 2, goal: 1, project: 0 },
            updated: { task: 1, goal: 0, project: 0 },
            deleted: { task: 0, goal: 0, project: 0 },
            errors: ["update goal X: not found"],
        })).toBe("Created 2 tasks, 1 goal. Updated 1 task. 1 error.");
    });
    test("singular/plural agreement", () => {
        expect(applySummaryText({
            created: { task: 1, goal: 0, project: 0 },
            updated: {}, deleted: {}, errors: [],
        })).toBe("Created 1 task.");
    });
    test("nothing → empty string", () => {
        expect(applySummaryText({
            created: {}, updated: {}, deleted: {}, errors: [],
        })).toBe("");
        expect(applySummaryText(null)).toBe("");
    });
});

describe("selectedActions", () => {
    const proposed = {
        explicit: [{ id: "a" }, { id: "b" }],
        suggested: [{ id: "c" }],
    };
    test("returns only checked rows, explicit before suggested", () => {
        const map = { "explicit:0": true, "explicit:1": false, "suggested:0": true };
        expect(selectedActions(proposed, map)).toEqual([{ id: "a" }, { id: "c" }]);
    });
    test("empty map → no actions", () => {
        expect(selectedActions(proposed, {})).toEqual([]);
    });
    test("defensive against missing buckets", () => {
        expect(selectedActions({}, { "explicit:0": true })).toEqual([]);
    });
});

describe("appendTranscriptSegment (#232 pause+resume)", () => {
    const { appendTranscriptSegment } = require("../../../static/reflection_helpers");

    test("empty existing + segment → just segment", () => {
        expect(appendTranscriptSegment("", "Hello world.")).toBe("Hello world.");
    });

    test("null existing handled as empty", () => {
        expect(appendTranscriptSegment(null, "Hello.")).toBe("Hello.");
    });

    test("undefined existing handled as empty", () => {
        expect(appendTranscriptSegment(undefined, "Hello.")).toBe("Hello.");
    });

    test("existing ends with trailing space → just concatenate", () => {
        expect(appendTranscriptSegment("First. ", "Second."))
            .toBe("First. Second.");
    });

    test("existing ends with trailing newline → just concatenate", () => {
        expect(appendTranscriptSegment("First.\n", "Second."))
            .toBe("First.\nSecond.");
    });

    test("existing ends without whitespace → insert single space", () => {
        expect(appendTranscriptSegment("First.", "Second."))
            .toBe("First. Second.");
    });

    test("Whisper leading whitespace on segment is trimmed", () => {
        // Whisper sometimes prepends " " or " hello"; trim it so we
        // don't get double spaces in the textarea.
        expect(appendTranscriptSegment("First.", "  Second."))
            .toBe("First. Second.");
    });

    test("preserves segment's trailing space for the next concat", () => {
        // The segment-side trailing whitespace is intentionally KEPT
        // so the next append doesn't need to recompute the boundary.
        const result = appendTranscriptSegment("First.", "Second. ");
        expect(result).toBe("First. Second. ");
    });

    test("empty segment is a no-op", () => {
        expect(appendTranscriptSegment("Existing.", "")).toBe("Existing.");
    });

    test("empty segment after leading-whitespace trim is a no-op", () => {
        // " " trims to "" so segment is empty → no-op.
        expect(appendTranscriptSegment("Existing.", "   ")).toBe("Existing.");
    });

    test("null segment is a no-op", () => {
        expect(appendTranscriptSegment("Existing.", null)).toBe("Existing.");
    });

    test("typed existing + voice segment → space-separated", () => {
        // The user typed before clicking Record. New voice segments
        // append after their typed text.
        expect(appendTranscriptSegment("I typed this.", "Then I said this."))
            .toBe("I typed this. Then I said this.");
    });

    test("two voice segments chain naturally", () => {
        let acc = "";
        acc = appendTranscriptSegment(acc, "First segment.");
        acc = appendTranscriptSegment(acc, "Second segment.");
        acc = appendTranscriptSegment(acc, "Third segment.");
        expect(acc).toBe("First segment. Second segment. Third segment.");
    });

    test("non-string types are coerced gracefully", () => {
        // Defensive: a fetch error could pass us a number or object;
        // String() coercion makes the helper crash-resistant.
        expect(appendTranscriptSegment("base", 42)).toBe("base 42");
    });
});

// #464: a failed Finish & analyze is "saved" only when the server says so.
describe("submitFailure (#464)", () => {
    const { submitFailure } = require("../../../static/reflection_helpers");
    const httpErr = (status, body, message) =>
        Object.assign(new Error(message), { status, body });

    test("a saved 422 keeps the old behaviour and message", () => {
        const out = submitFailure(httpErr(422, {
            error: "Analysis failed: the model is busy.", saved: true, reflection_id: "r1",
        }, "Analysis failed: the model is busy."));
        expect(out).toEqual({ saved: true, message: "Analysis failed: the model is busy." });
    });

    test("a saved 500 adds the label once", () => {
        const out = submitFailure(httpErr(500, { error: "boom", saved: true }, "boom"));
        expect(out).toEqual({ saved: true, message: "Analysis failed: boom" });
    });

    test("a 429 (HTML body) saved nothing and says to wait", () => {
        const out = submitFailure(httpErr(429, {}, "TOO MANY REQUESTS"));
        expect(out.saved).toBe(false);
        expect(out.message).toBe("Couldn't send it for analysis: too many analyses in a "
            + "minute — wait a minute and try again. Nothing went to your history — your "
            + "text is still here, and still saved as your draft.");
    });

    test("an unsaved 422 passes the server's reason through, one full stop", () => {
        const out = submitFailure(httpErr(422, { error: "text must be text." }, "text must be text."));
        expect(out).toEqual({
            saved: false,
            message: "Couldn't send it for analysis: text must be text. Nothing went to your "
                + "history — your text is still here, and still saved as your draft.",
        });
    });

    test("a network error (no status) saved nothing", () => {
        const out = submitFailure(new TypeError("Failed to fetch"));
        expect(out.saved).toBe(false);
        expect(out.message).toMatch(/^Couldn't send it for analysis: Failed to fetch\. Nothing went/);
    });

    test("only saved === true counts", () => {
        for (const saved of ["true", 1, null, undefined, false]) {
            expect(submitFailure(httpErr(500, { error: "x", saved }, "x")).saved).toBe(false);
        }
        expect(submitFailure(null).saved).toBe(false);
    });
});
