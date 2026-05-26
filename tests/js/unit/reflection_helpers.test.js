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
