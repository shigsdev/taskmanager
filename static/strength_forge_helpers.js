/**
 * strengthForgeHelpers — pure logic for the #287 per-set logging form.
 *
 * Extracted from the DOM code in static/strength_forge.js so the
 * non-trivial branches (parsing a prescribed "sets" string, building the
 * POST payload from form state) are unit-testable in Jest — never just
 * string-matched (CLAUDE.md anti-pattern #3). Dual-export: window-side for
 * the browser, module.exports for Node/Jest.
 */
"use strict";

/**
 * defaultSetCount — how many blank set-rows to pre-render for an exercise,
 * derived from its prescribed `sets` string in SFData.
 *
 *   "3 × 10"          -> 3
 *   "3 sets × 8 each" -> 3
 *   "45s × 2 sides"   -> 1   (time-based, no leading set count)
 *   "10 reps"         -> 1
 *   "4–6 cycles"      -> 1
 *   ""/undefined      -> 1
 *
 * Rule: use the leading integer ONLY when it's immediately followed by the
 * "× / sets / x" set-marker; otherwise default to 1. Clamp to 1..5.
 */
function defaultSetCount(prescribed) {
    var n = 1;
    if (typeof prescribed === "string") {
        // Leading number followed by a set marker: "3 ×", "3x", "3 sets".
        var m = prescribed.match(/^\s*(\d+)\s*(?:×|x|sets?\b)/i);
        if (m) {
            n = parseInt(m[1], 10);
        }
    }
    if (!Number.isFinite(n) || n < 1) n = 1;
    if (n > 5) n = 5;
    return n;
}

/**
 * buildSetsPayload — flatten the form's per-exercise/per-set state into the
 * POST `sets` array, dropping rows that have NEITHER reps nor resistance.
 *
 * Input shape (array of exercises):
 *   [{ exercise_id, name, sets: [{ reps, resistance }, ...] }, ...]
 * Output (array of set entries, set_number 1-based per exercise):
 *   [{ exercise_id, name, set_number, reps, resistance }, ...]
 *
 * reps: parsed to a non-negative int or null. resistance: trimmed or "".
 */
function buildSetsPayload(exercises) {
    var out = [];
    if (!Array.isArray(exercises)) return out;
    exercises.forEach(function (ex) {
        if (!ex || !Array.isArray(ex.sets)) return;
        var n = 0;
        ex.sets.forEach(function (row) {
            var resistance = (row && row.resistance ? String(row.resistance) : "").trim();
            var reps = null;
            if (row && row.reps !== "" && row.reps != null) {
                var parsed = parseInt(row.reps, 10);
                if (Number.isFinite(parsed) && parsed >= 0) reps = parsed;
            }
            if (reps == null && !resistance) return; // blank row — skip
            n += 1;
            out.push({
                exercise_id: ex.exercise_id || "",
                name: ex.name || "",
                set_number: n,
                reps: reps,
                resistance: resistance,
            });
        });
    });
    return out;
}

var strengthForgeHelpers = {
    defaultSetCount: defaultSetCount,
    buildSetsPayload: buildSetsPayload,
};

// Browser global
if (typeof window !== "undefined") {
    window.strengthForgeHelpers = strengthForgeHelpers;
}
// Node/Jest
if (typeof module !== "undefined" && module.exports) {
    module.exports = strengthForgeHelpers;
}
