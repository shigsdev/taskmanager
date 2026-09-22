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

    /**
     * #232 (2026-05-25): append a freshly-transcribed voice segment to
     * whatever's already in the reflection textarea (typed text OR
     * earlier voice segments). The rule:
     *
     *   - empty existing → return the new segment as-is
     *   - existing ends in whitespace → just concat (no extra space)
     *   - otherwise → insert a single space between
     *
     * Trim only the LEADING whitespace on the new segment (Whisper
     * sometimes returns " hello"); preserve its trailing whitespace
     * for the next concat. Never insert a hard newline — the user
     * can press Enter manually if they want paragraph breaks.
     *
     * Pure: no DOM, no module state. The DOM glue in reflection.js
     * reads the current textarea value, calls this, sets it back.
     */
    function appendTranscriptSegment(existing, segment) {
        var ex = (existing == null) ? "" : String(existing);
        var seg = (segment == null) ? "" : String(segment).replace(/^\s+/, "");
        if (seg === "") return ex;
        if (ex === "") return seg;
        if (/\s$/.test(ex)) return ex + seg;
        return ex + " " + seg;
    }

    /**
     * shouldAutosaveDraft — is this content worth a PUT? (#324)
     *
     * The autosave fires on a debounce as the user types. Re-sending
     * text identical to what the server already has is pure noise, and
     * saving "" over a draft the user hasn't touched yet would blank it
     * for no reason. Returns true only when the content actually
     * CHANGED from the last saved value.
     *
     * Note the deliberate asymmetry: clearing a draft that HAD text is a
     * real edit and must save (the user meant to erase it), but ""
     * when nothing was ever saved is a no-op.
     */
    function shouldAutosaveDraft(lastSaved, current) {
        var cur = typeof current === "string" ? current : "";
        var prev = typeof lastSaved === "string" ? lastSaved : "";
        if (cur === prev) return false;          // nothing changed
        if (!cur.trim() && !prev) return false;  // empty, nothing to erase
        return true;
    }

    /**
     * formatSavedAt — the "last saved" label on the draft banner (#324).
     *
     * Reflecting across days means the banner has to answer "how stale
     * is this?" at a glance. Recent saves read as relative time; older
     * ones name the day, because "3 days ago" is the case where the user
     * most needs to know they're resuming something old.
     *
     * `nowMs` is injected so this is deterministic under test.
     */
    function formatSavedAt(iso, nowMs) {
        if (typeof iso !== "string" || !iso) return "";
        var then = Date.parse(iso);
        if (!isFinite(then)) return "";
        var now = typeof nowMs === "number" ? nowMs : Date.now();
        var secs = Math.round((now - then) / 1000);
        if (secs < 0) secs = 0;               // clock skew — treat as now
        if (secs < 10) return "just now";
        if (secs < 60) return secs + "s ago";
        var mins = Math.floor(secs / 60);
        if (mins < 60) return mins + (mins === 1 ? " min ago" : " mins ago");
        var hours = Math.floor(mins / 60);
        if (hours < 24) return hours + (hours === 1 ? " hour ago" : " hours ago");
        var days = Math.floor(hours / 24);
        return days + (days === 1 ? " day ago" : " days ago");
    }

    var _MILE_MON = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ];

    /** "2026-11-02" -> "2 Nov 2026". Fixed month names, no locale, so
     *  the header reads the same everywhere and is testable. */
    function _mileDate(iso) {
        if (typeof iso !== "string") return "";
        var m = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (!m) return "";
        var mon = _MILE_MON[parseInt(m[2], 10) - 1];
        if (!mon) return "";
        return parseInt(m[3], 10) + " " + mon + " " + m[1];
    }

    /**
     * milestoneHeadline — the /reflection runway header (#325).
     *
     * Turns the resolved milestone into `{title, sub, warning}` (or null
     * when nothing is configured, so the header stays out of the way
     * until it has something to say).
     *
     * Countdown wording is the point: a reflection is most useful when
     * you can see how much runway is left at a glance. A milestone in
     * the PAST says so plainly rather than reading "0 weeks left"
     * forever, and a milestone with no date still shows its name
     * (partial configuration shouldn't blank the header).
     */
    function milestoneHeadline(m) {
        if (!m || !m.configured) return null;
        var label = m.label || "your milestone";
        var out = { title: "", sub: "", warning: m.warning || "" };

        if (!m.date) {
            out.title = "Working toward: " + label;
            out.sub = "No date set";
            return out;
        }

        var when = _mileDate(m.date) || m.date;
        out.title = "Working toward: " + label + " · " + when;

        var days = m.days_left;
        if (typeof days !== "number") { out.sub = ""; return out; }

        if (m.passed) {
            var ago = Math.abs(days);
            out.sub = ago === 0
                ? "That was today"
                : "That was " + ago + (ago === 1 ? " day" : " days") + " ago";
            return out;
        }
        if (days === 0) { out.sub = "That's today"; return out; }
        if (days === 1) { out.sub = "1 day left"; return out; }

        var weeks = m.weeks_left;
        var dayPart = days + " days left";
        out.sub = (typeof weeks === "number" && weeks > 1)
            ? weeks + " weeks left · " + days + " days"
            : dayPart;
        return out;
    }

    var api = {
        defaultChecked: defaultChecked,
        actionLabel: actionLabel,
        changeSummary: changeSummary,
        focusCandidates: focusCandidates,
        applySummaryText: applySummaryText,
        selectedActions: selectedActions,
        appendTranscriptSegment: appendTranscriptSegment,
        shouldAutosaveDraft: shouldAutosaveDraft,
        milestoneHeadline: milestoneHeadline,
        formatSavedAt: formatSavedAt,
    };

    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    } else if (typeof window !== "undefined") {
        window.reflectionHelpers = api;
    }
})();
