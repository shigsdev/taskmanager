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

/**
 * formatLastResist — the "last used" resistance reference string for an
 * exercise, from a `{resistance, reps, date}` record (or null/undefined).
 *
 *   {resistance:"Medium", reps:12, date:"2026-07-05"} -> "last: Medium · 12r · Jul 5"
 *   {resistance:"Heavy",  reps:null, date:"2026-06-30"} -> "last: Heavy · Jun 30"
 *   {resistance:"Light",  reps:8,   date:null}          -> "last: Light · 8r"
 *   null / {resistance:""}                              -> ""   (no reference)
 *
 * Deterministic (fixed month abbreviations — no locale/timezone), so it's
 * unit-testable and renders identically on the print sheet and log form.
 */
var _SF_MON = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function _sfShortDate(iso) {
    if (typeof iso !== "string") return "";
    var m = iso.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return "";
    var mon = _SF_MON[parseInt(m[2], 10) - 1];
    if (!mon) return "";
    return mon + " " + parseInt(m[3], 10);
}

function formatLastResist(rec) {
    if (!rec || !rec.resistance) return "";
    var bits = [String(rec.resistance)];
    if (rec.reps != null && rec.reps !== "") bits.push(rec.reps + "r");
    var d = _sfShortDate(rec.date);
    if (d) bits.push(d);
    return "last: " + bits.join(" · ");
}

var strengthForgeHelpers = {
    defaultSetCount: defaultSetCount,
    buildSetsPayload: buildSetsPayload,
    formatLastResist: formatLastResist,
};

// Browser global
if (typeof window !== "undefined") {
    window.strengthForgeHelpers = strengthForgeHelpers;
}
// Node/Jest
if (typeof module !== "undefined" && module.exports) {
    module.exports = strengthForgeHelpers;
}
