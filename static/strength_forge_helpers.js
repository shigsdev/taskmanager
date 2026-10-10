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
 *   #410: a per-side exercise's rows are { repsL, repsR, resistance }.
 * Output (array of set entries, set_number 1-based per exercise):
 *   [{ exercise_id, name, set_number, reps, resistance }, ...]
 *   #410: a per-side row yields one entry per filled side, each with
 *   `side: "L" | "R"`, sharing set_number and the one resistance. A per-side
 *   row with a resistance but no reps yields ONE side-less entry (it still
 *   records the band for the "last used" reference).
 *
 * reps: parsed to a non-negative int or null. resistance: trimmed or "".
 */
function parseReps(raw) {
    if (raw === "" || raw == null) return null;
    var parsed = parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function buildSetsPayload(exercises) {
    var out = [];
    if (!Array.isArray(exercises)) return out;
    exercises.forEach(function (ex) {
        if (!ex || !Array.isArray(ex.sets)) return;
        var n = 0;
        var base = function (setNumber) {
            return { exercise_id: ex.exercise_id || "", name: ex.name || "", set_number: setNumber };
        };
        ex.sets.forEach(function (row) {
            var resistance = (row && row.resistance ? String(row.resistance) : "").trim();
            var perSide = !!row && ("repsL" in row || "repsR" in row);
            if (perSide) {
                var l = parseReps(row.repsL), r = parseReps(row.repsR);
                if (l == null && r == null && !resistance) return; // blank row
                n += 1;
                if (l == null && r == null) {
                    var only = base(n);
                    only.reps = null;
                    only.resistance = resistance;
                    out.push(only);
                    return;
                }
                [["L", l], ["R", r]].forEach(function (pair) {
                    if (pair[1] == null) return;
                    var e = base(n);
                    e.side = pair[0];
                    e.reps = pair[1];
                    e.resistance = resistance;
                    out.push(e);
                });
                return;
            }
            var reps = parseReps(row && row.reps);
            if (reps == null && !resistance) return; // blank row — skip
            n += 1;
            var entry = base(n);
            entry.reps = reps;
            entry.resistance = resistance;
            out.push(entry);
        });
    });
    return out;
}

/**
 * isPerSide — does this plan item log Left and Right reps separately? (#410)
 * An explicit catalog flag (`perSide: true`), never parsed from "each" —
 * "10 each direction" on arm circles is not per side. An item-level flag wins.
 */
function isPerSide(item, catalog) {
    if (!item) return false;
    if (item.perSide) return true;
    if (!catalog || !item.id || !catalog[item.id]) return false;
    return !!catalog[item.id].perSide;
}

/**
 * summarizeSets — one exercise's logged rows as the history-strip text.
 *
 *   per-side:  [{set 1, L, 10, Medium}, {set 1, R, 9, Medium}] -> "L 10 · R 9 @ Medium"
 *   bilateral: [{set 1, 12, Light}, {set 2, null, Heavy}]       -> "12 reps @ Light, Heavy"
 *   empty row -> "—"; no rows -> ""
 * Sets are joined with ", " in the order given (the API returns them by
 * set_number).
 */
function summarizeSets(rows) {
    if (!Array.isArray(rows) || !rows.length) return "";
    var groups = [], bySet = {};
    rows.forEach(function (st) {
        var sided = st.side === "L" || st.side === "R";
        var key = sided ? "s" + st.set_number : "row" + groups.length;
        if (!bySet[key]) {
            bySet[key] = { n: st.set_number || 0, rows: [] };
            groups.push(bySet[key]);
        }
        bySet[key].rows.push(st);
    });
    return groups.map(function (g) {
        var sided = g.rows.filter(function (st) { return st.side === "L" || st.side === "R"; });
        var resistance = "";
        g.rows.forEach(function (st) { if (!resistance && st.resistance) resistance = st.resistance; });
        var reps;
        if (sided.length) {
            reps = ["L", "R"].map(function (s) {
                var hit = sided.filter(function (st) { return st.side === s; })[0];
                return hit && hit.reps != null ? s + " " + hit.reps : "";
            }).filter(Boolean).join(" · ");
        } else {
            reps = g.rows[0].reps != null ? g.rows[0].reps + " reps" : "";
        }
        var res = resistance ? ((reps ? " @ " : "") + resistance) : "";
        return (reps + res) || "—";
    }).join(", ");
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

/**
 * usesResistance — does this plan item take a resistance value?
 *
 * Bodyweight, stretch, and breathing moves have no resistance, so the log
 * form and print sheet should not show a resistance field for them. The
 * source of truth is the exercise catalog's `resist` flag, but an
 * individual plan item can override it (e.g. glute-bridge is bodyweight in
 * the catalog but "Band Glute Bridge" in Bands Workout A sets item.resist).
 *
 *   item.resist === true|false      -> that boolean (explicit override)
 *   else catalog[item.id].resist    -> the catalog default
 *   unknown id / null item          -> false
 */
function usesResistance(item, catalog) {
    if (!item) return false;
    if (typeof item.resist === "boolean") return item.resist;
    var info = (catalog && catalog[item.id]) || {};
    return info.resist === true;
}

/**
 * isDraftFresh — should a saved log-form draft be restored, or is it a
 * stale leftover from an already-finished / abandoned session?
 *
 * A workout is a single sitting; a draft older than `maxHours` (default 24)
 * almost certainly belongs to a session the user already logged or walked
 * away from, so we discard it rather than silently resurrecting it on top
 * of a fresh workout. Non-finite / missing timestamps are treated as stale.
 */
function isDraftFresh(savedAtMs, nowMs, maxHours) {
    var maxH = typeof maxHours === "number" && maxHours > 0 ? maxHours : 24;
    if (!Number.isFinite(savedAtMs) || !Number.isFinite(nowMs)) return false;
    var ageMs = nowMs - savedAtMs;
    if (ageMs < 0) return true; // clock skew — keep rather than lose work
    return ageMs <= maxH * 3600 * 1000;
}

/**
 * planTypesForRole — the ordered list of plan-type keys that make up a
 * training role's FULL program. The print sheet uses this to render EVERY
 * workout day of a plan at once (#313 — "print the full one"), instead of
 * only the day currently toggled on screen.
 *
 *   "band" -> ["band-a", "band-b"]                             (Workouts A + B)
 *   "mil"  -> ["mil-1", "mil-2", "mil-3"]                       (Sessions 1–3)
 *   "iso"  -> ["iso-chest", ... "iso-legs"]  (#315 — one muscle per session)
 *   "split" -> ["split-1", "split-2", "split-3"]   (#320 — 4-day cycle; the
 *              rest day is schedule-only, so it is not a plan type)
 *   unknown / missing -> []
 *
 * Single source of truth for the role→days mapping; kept here (pure) so the
 * mapping is unit-testable and can't silently drift from the print button.
 */
function planTypesForRole(role) {
    if (role === "band") return ["band-a", "band-b"];
    if (role === "mil") return ["mil-1", "mil-2", "mil-3"];
    if (role === "iso") {
        return [
            "iso-chest", "iso-back", "iso-shoulders",
            "iso-biceps", "iso-triceps", "iso-legs",
        ];
    }
    if (role === "split") return ["split-1", "split-2", "split-3"];
    return [];
}

/**
 * exerciseSearchLinks — the exercise modal's two "see it done" links (#409).
 *
 * The catalog `search` string IS the whole query (nothing is appended — the
 * old " exercise how to form" suffix doubled words like "exercise exercise").
 *   images: Google Images (`udm=2`; the old `tbm=isch` is legacy)
 *   video:  YouTube results for "how to <query>" (prefix not doubled)
 *
 *   "pike push up" -> { images: "…google.com/search?q=pike%20push%20up&udm=2",
 *                       video:  "…youtube.com/results?search_query=how%20to%20pike%20push%20up" }
 *   "" / null      -> null (render no links)
 */
function exerciseSearchLinks(query) {
    var q = (query == null ? "" : String(query)).replace(/\s+/g, " ").trim();
    if (!q) return null;
    var videoQ = /^how to\b/i.test(q) ? q : "how to " + q;
    return {
        images: "https://www.google.com/search?q=" + encodeURIComponent(q) + "&udm=2",
        video: "https://www.youtube.com/results?search_query=" + encodeURIComponent(videoQ),
    };
}

var strengthForgeHelpers = {
    defaultSetCount: defaultSetCount,
    buildSetsPayload: buildSetsPayload,
    formatLastResist: formatLastResist,
    usesResistance: usesResistance,
    isDraftFresh: isDraftFresh,
    planTypesForRole: planTypesForRole,
    exerciseSearchLinks: exerciseSearchLinks,
    isPerSide: isPerSide,
    summarizeSets: summarizeSets,
};

// Browser global
if (typeof window !== "undefined") {
    window.strengthForgeHelpers = strengthForgeHelpers;
}
// Node/Jest
if (typeof module !== "undefined" && module.exports) {
    module.exports = strengthForgeHelpers;
}
