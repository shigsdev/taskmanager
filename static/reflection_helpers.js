/**
 * Weekly Reflection pure helpers (#165 frontend, 2026-05-17).
 *
 * Same dual-export pattern as parse_capture.js / filter_helpers.js:
 * in the browser the functions hang off window.reflectionHelpers via a
 * <script> tag; in Node/Jest they are require()-able via module.exports.
 *
 * Per CLAUDE.md anti-pattern #3, the non-trivial branchy logic
 * (focus-candidate derivation, summary formatting, selection filtering)
 * lives here so it can be unit-tested against its OUTPUTS rather than
 * string-matched in prod smoke. Everything here is pure: inputs in,
 * value out, no DOM, no module state.
 */
(function () {
    "use strict";

    var OP_VERB = { create: "Create", update: "Update", delete: "Delete" };

    /**
     * Explicit actions are things the user actually asked for, so they
     * default to checked. Suggested actions are proactive ideas the user
     * opted into but should affirmatively pick — default unchecked.
     */
    function defaultChecked(bucket) {
        return bucket === "explicit";
    }

    /** "Create task: Ship auth refresh" — the row's primary label. */
    function actionLabel(action) {
        if (!action || typeof action !== "object") return "";
        var verb = OP_VERB[action.op] || action.op || "?";
        var entity = action.entity || "item";
        var target = (action.target || "").toString().trim();
        return verb + " " + entity + (target ? ": " + target : "");
    }

    /**
     * Compact "field: from → to; field2: …" string for an update's
     * `changes` list (display only). Empty values render as "∅" so a
     * blank → value transition is still visible.
     */
    function changeSummary(changes) {
        if (!Array.isArray(changes) || changes.length === 0) return "";
        return changes
            .map(function (c) {
                var f = c && c.field != null ? String(c.field) : "?";
                var from = c && c.from != null && String(c.from) !== ""
                    ? String(c.from) : "∅";
                var to = c && c.to != null && String(c.to) !== ""
                    ? String(c.to) : "∅";
                return f + ": " + from + " → " + to;
            })
            .join("; ");
    }

    /**
     * Derive up to `max` free-form focus statements from the proposed
     * actions, for seeding next week's Focus slots (#157 hook).
     *
     * Priority: explicit bucket before suggested; within a bucket,
     * preserve order. Only create/update actions on a task or goal are
     * focus-worthy (a delete or a project tweak isn't a "focus for the
     * week"). Deduped case-insensitively on the trimmed target text.
     * Returns an array of strings (length ≤ max).
     */
    function focusCandidates(proposed, max) {
        var cap = typeof max === "number" && max > 0 ? max : 3;
        var p = proposed && typeof proposed === "object" ? proposed : {};
        var ordered = []
            .concat(Array.isArray(p.explicit) ? p.explicit : [])
            .concat(Array.isArray(p.suggested) ? p.suggested : []);
        var seen = {};
        var out = [];
        for (var i = 0; i < ordered.length && out.length < cap; i++) {
            var a = ordered[i];
            if (!a || typeof a !== "object") continue;
            if (a.op !== "create" && a.op !== "update") continue;
            if (a.entity !== "task" && a.entity !== "goal") continue;
            var text = (a.target || "").toString().trim();
            if (!text) continue;
            var key = text.toLowerCase();
            if (seen[key]) continue;
            seen[key] = true;
            out.push(text);
        }
        return out;
    }

    /**
     * Human one-liner from the confirm endpoint's summary dict
     * (shape: {created:{task,goal,project}, updated:{…}, deleted:{…},
     * errors:[…]}). Returns "" if nothing happened.
     */
    function applySummaryText(summary) {
        if (!summary || typeof summary !== "object") return "";
        var parts = [];
        ["created", "updated", "deleted"].forEach(function (verb) {
            var bucket = summary[verb];
            if (!bucket || typeof bucket !== "object") return;
            var bits = [];
            ["task", "goal", "project"].forEach(function (ent) {
                var n = bucket[ent] || 0;
                if (n > 0) bits.push(n + " " + ent + (n === 1 ? "" : "s"));
            });
            if (bits.length) {
                parts.push(
                    verb.charAt(0).toUpperCase() + verb.slice(1)
                    + " " + bits.join(", ")
                );
            }
        });
        var errs = Array.isArray(summary.errors) ? summary.errors.length : 0;
        if (errs > 0) {
            parts.push(errs + " error" + (errs === 1 ? "" : "s"));
        }
        return parts.join(". ") + (parts.length ? "." : "");
    }

    /**
     * Given the proposed buckets and a checked-map keyed "bucket:index",
     * return the flat array of action objects the user selected. The
     * action objects are returned verbatim (the confirm endpoint
     * re-validates server-side).
     */
    function selectedActions(proposed, checkedMap) {
        var p = proposed && typeof proposed === "object" ? proposed : {};
        var map = checkedMap && typeof checkedMap === "object"
            ? checkedMap : {};
        var out = [];
        ["explicit", "suggested"].forEach(function (bucket) {
            var arr = Array.isArray(p[bucket]) ? p[bucket] : [];
            for (var i = 0; i < arr.length; i++) {
                if (map[bucket + ":" + i]) out.push(arr[i]);
            }
        });
        return out;
    }

    var api = {
        defaultChecked: defaultChecked,
        actionLabel: actionLabel,
        changeSummary: changeSummary,
        focusCandidates: focusCandidates,
        applySummaryText: applySummaryText,
        selectedActions: selectedActions,
    };

    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    } else if (typeof window !== "undefined") {
        window.reflectionHelpers = api;
    }
})();
