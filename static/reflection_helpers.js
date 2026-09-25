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
     *
     * #330 (2026-09-25) — the segment counts. Text is not the whole of a
     * draft: `raw_segments` carries the verbatim Whisper output, its
     * duration and its cost, and that can grow while the text stays
     * byte-identical (a segment landing whose words the user had already
     * typed, or a flush that raced an in-flight save). Judging on text
     * alone is what made #330 UNREPAIRABLE — the visibilitychange
     * safety net looked at the text, saw no change, and returned false,
     * so a draft that was one segment behind stayed one segment behind
     * for the rest of the sitting. Comparing what the server HAS against
     * what we HOLD turns an ordering-dependent invariant into a
     * state-compared one: any future path that appends a segment without
     * flushing is still repaired by the next save opportunity.
     *
     * Both counts are optional; omit them and the rule is exactly the
     * #324 text comparison. GROWTH only — a shrink means the draft was
     * reset, and both counters move together there.
     */
    function shouldAutosaveDraft(lastSaved, current, savedSegments, segments) {
        var cur = typeof current === "string" ? current : "";
        var prev = typeof lastSaved === "string" ? lastSaved : "";
        if (!cur.trim() && !prev) return false;  // empty, nothing to erase
        if (cur !== prev) return true;           // the text itself changed
        return _segmentCount(segments) > _segmentCount(savedSegments);
    }

    /** #330: a count from either a number or the array itself. Anything
     *  unusable reads as 0, so a junk argument can never manufacture a
     *  save (or suppress one) on its own. */
    function _segmentCount(v) {
        if (typeof v === "number" && isFinite(v) && v > 0) return Math.floor(v);
        if (Array.isArray(v)) return v.length;
        return 0;
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

    /**
     * autoPauseReason — should recording stop now, and why? (#326)
     *
     * Two independent limits, and the SIZE one is the real constraint:
     * Whisper rejects any request over 25MB, so a segment that exceeds
     * the byte budget cannot be transcribed at all. The clock cap is a
     * secondary comfort limit.
     *
     * Returns "size" | "time" | null. Size is checked FIRST because
     * blowing the byte budget is the failure that loses the recording;
     * hitting the clock is merely an interruption.
     */
    function autoPauseReason(bytes, maxBytes, elapsedMs, capMs) {
        var b = typeof bytes === "number" && isFinite(bytes) ? bytes : 0;
        var mb = typeof maxBytes === "number" && maxBytes > 0 ? maxBytes : Infinity;
        if (b >= mb) return "size";
        var e = typeof elapsedMs === "number" && isFinite(elapsedMs) ? elapsedMs : 0;
        var cm = typeof capMs === "number" && capMs > 0 ? capMs : Infinity;
        if (e >= cm) return "time";
        return null;
    }

    function _mmss(totalSec) {
        var m = Math.floor(totalSec / 60);
        var s = totalSec % 60;
        return m + ":" + (s < 10 ? "0" : "") + s;
    }

    /**
     * formatRecordingTime — the live timer, WITH its cap (#326).
     *
     * The timer used to count up with no indication a cap existed, so
     * recording just stopped mid-sentence at the limit. Showing
     * "12:34 / 30:00" makes the budget visible, and `warn` goes true
     * for the last `warnSec` so the user can wrap up a thought instead
     * of being cut off.
     */
    function formatRecordingTime(elapsedMs, capMs, warnSec) {
        var e = typeof elapsedMs === "number" && isFinite(elapsedMs) && elapsedMs > 0
            ? elapsedMs : 0;
        var elapsedSec = Math.floor(e / 1000);
        if (typeof capMs !== "number" || !(capMs > 0)) {
            return { text: _mmss(elapsedSec), warn: false, remainingSec: null };
        }
        var capSec = Math.floor(capMs / 1000);
        var remaining = Math.max(0, capSec - elapsedSec);
        var threshold = typeof warnSec === "number" && warnSec >= 0 ? warnSec : 120;
        return {
            text: _mmss(elapsedSec) + " / " + _mmss(capSec),
            warn: remaining <= threshold,
            remainingSec: remaining,
        };
    }

    /**
     * #328 — how one attached context file reads in the list.
     *
     * The character count is the honest unit here, not the file size:
     * what actually reaches Claude is the extracted text, and a 4MB PDF
     * of scanned pages can yield less of it than a 3KB note. Truncation
     * is stated outright — quietly analysing the first third of a
     * document would be a worse failure than refusing it.
     */
    function attachmentLabel(file) {
        if (!file || typeof file !== "object") return "";
        var name = (file.filename || "attachment").trim() || "attachment";
        var chars = typeof file.chars === "number" && file.chars > 0
            ? file.chars : 0;
        var kind = (file.kind || "").toString().toLowerCase();
        var bits = [];
        if (kind) bits.push(kind.toUpperCase());
        if (chars) bits.push(_thousands(chars) + " characters");
        var meta = bits.join(" · ");
        if (file.truncated) {
            var src = typeof file.source_chars === "number"
                && file.source_chars > chars ? file.source_chars : null;
            meta += src
                ? " (shortened from " + _thousands(src) + ")"
                : " (shortened)";
        }
        return { name: name, meta: meta };
    }

    function _thousands(n) {
        return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    }

    /**
     * #328 — the one-line summary under the attachment list.
     *
     * Returns "" when nothing is attached so the block stays quiet on a
     * fresh reflection rather than announcing an empty state.
     */
    function attachmentSummary(files, maxFiles, maxChars) {
        var list = Array.isArray(files) ? files : [];
        if (!list.length) return "";
        var used = 0;
        for (var i = 0; i < list.length; i++) {
            var c = list[i] && list[i].chars;
            if (typeof c === "number" && c > 0) used += c;
        }
        var n = list.length;
        var cap = typeof maxFiles === "number" && maxFiles > 0 ? maxFiles : 5;
        var budget = typeof maxChars === "number" && maxChars > 0
            ? maxChars : 60000;
        return n + " of " + cap + (n === 1 ? " file" : " files") + " · "
            + _thousands(used) + " of " + _thousands(budget)
            + " characters of context";
    }

    /**
     * #328 — is this file worth sending at all?
     *
     * Checked client-side purely so an obviously-wrong pick fails
     * instantly instead of after a 10MB upload. The server re-validates
     * everything; this is a courtesy, never the gate.
     */
    var ATTACHMENT_EXTENSIONS = [
        ".pdf", ".docx", ".xlsx", ".txt", ".md",
        ".png", ".jpg", ".jpeg", ".webp",
    ];

    function attachmentPreflight(file, maxBytes, allowed) {
        if (!file) return "No file selected.";
        var exts = Array.isArray(allowed) && allowed.length
            ? allowed : ATTACHMENT_EXTENSIONS;
        var name = (file.name || "").toLowerCase();
        var ok = false;
        for (var i = 0; i < exts.length; i++) {
            if (name.length > exts[i].length
                && name.slice(-exts[i].length) === exts[i]) {
                ok = true;
                break;
            }
        }
        if (!ok) {
            return "That file type isn't supported. Attach a "
                + exts.join(", ") + " file.";
        }
        var cap = typeof maxBytes === "number" && maxBytes > 0
            ? maxBytes : 10 * 1024 * 1024;
        if (typeof file.size === "number" && file.size > cap) {
            return "That file is too large (max "
                + Math.floor(cap / 1024 / 1024) + " MB).";
        }
        if (typeof file.size === "number" && file.size === 0) {
            return "That file is empty.";
        }
        return null;
    }

    /**
     * voiceIdleCopy - what the Record tab says when it is NOT recording.
     *
     * #332: the idle button used to always read "Start recording", even
     * when the reflection already held thousands of words from an earlier
     * sitting. A user coming back (or bounced out by a page reload) read
     * that as "this will start over" and stalled. Worse, `selectMode`
     * hides the transcript in voice mode, so the Record tab gives no other
     * evidence the earlier work still exists.
     *
     * So the copy is derived from the text already captured: the verb
     * becomes Resume, and a note states the size of what is being resumed
     * and that new speech is APPENDED. Pure so the wording is testable
     * without a browser.
     */
    function voiceIdleCopy(existingText) {
        var text = (typeof existingText === "string" ? existingText : "").trim();
        if (!text) {
            return {
                label: "Start recording",
                aria: "Start recording",
                note: "",
                resuming: false,
            };
        }
        var words = text.split(/\s+/).filter(Boolean).length;
        return {
            label: "Resume recording",
            aria: "Resume recording - adds to the " + _thousands(words)
                + (words === 1 ? " word" : " words") + " already captured",
            note: "Picking up a reflection already in progress - "
                + _thousands(words) + (words === 1 ? " word" : " words")
                + " so far. New recording is added to the end, and nothing "
                + "you have already said is replaced.",
            resuming: true,
        };
    }

    /**
     * blocksAutoReload - may the service worker reload the page now? (#331)
     *
     * On 2026-09-24 a deploy bumped CACHE_VERSION while the user was
     * dictating. base.html polls for a new SW every 60s and auto-applies
     * it unless `userIsBusy()` objects - but that guard only knew about a
     * focused input/textarea/select and an open detail panel. Someone
     * SPEAKING has no focused field, so the page reloaded and killed the
     * live MediaRecorder mid-sentence.
     *
     * Blocking states, and why each one:
     *   recording    - audio only in memory since the last 5s flush
     *   transcribing - a paid Whisper upload is in flight
     *   paused       - mid-session; a reload drops the Resume affordance
     *   processing / review - voice-memo equivalents, same reasoning
     *
     * Deliberately NOT blocking on a merely non-empty draft: the draft is
     * server-side and survives a reload, and blocking on it would strand
     * the user on stale code for days. They still get the "Update
     * available" banner and choose their own moment.
     */
    var AUTO_RELOAD_BLOCKING_STATES = [
        "recording", "transcribing", "paused", "processing", "review",
    ];

    function blocksAutoReload(state) {
        if (typeof state !== "string") return false;
        return AUTO_RELOAD_BLOCKING_STATES.indexOf(state) !== -1;
    }

    function _pad2(n) { return (n < 10 ? "0" : "") + n; }

    /**
     * reflectionLabel - how one past reflection is named in history.
     *
     * #339: rows used to read `iso_week - date - input_mode`, which is
     * byte-identical for two reflections written on the same day in the
     * same mode. A user could not tell a throwaway test apart from a
     * real multi-hour session. Two changes: the generated label carries
     * the TIME, and a user-supplied `title` overrides it entirely.
     *
     * The time is derived in the viewer's LOCAL zone from `created_at`,
     * together with the date, so the two can never disagree across a
     * midnight boundary the way a sliced ISO prefix plus a local clock
     * would.
     */
    function reflectionLabel(r) {
        if (!r || typeof r !== "object") return "";
        var title = typeof r.title === "string" ? r.title.trim() : "";
        if (title) return title;
        var parts = [];
        if (r.iso_week) parts.push(String(r.iso_week));
        var stamp = "";
        var d = r.created_at ? new Date(r.created_at) : null;
        if (d && !isNaN(d.getTime())) {
            stamp = d.getFullYear() + "-" + _pad2(d.getMonth() + 1) + "-"
                + _pad2(d.getDate()) + " " + _pad2(d.getHours()) + ":"
                + _pad2(d.getMinutes());
        }
        if (stamp) parts.push(stamp);
        parts.push(String(r.input_mode || "typed"));
        return parts.join(" · ");
    }

    /**
     * reflectionIsNamed - does this row carry a user-given name? (#339)
     * Drives whether the control reads "Rename" or "Name it".
     */
    function reflectionIsNamed(r) {
        return !!(r && typeof r.title === "string" && r.title.trim());
    }

    /**
     * continuationNote - the banner shown while writing a continuation.
     *
     * #334: continuing FORKS. The text in the box is a past reflection's,
     * and finishing will save a NEW row. Both facts have to be on screen,
     * because the screen otherwise looks exactly like a restored draft
     * and the user would reasonably assume they are editing the original.
     *
     * Takes the serialised `continued_from` lineage block (the few fields
     * reflectionLabel needs), so there is one naming rule, not two.
     * Returns "" when the draft isn't a continuation, which is also the
     * signal to keep the banner hidden.
     */
    /**
     * _nameableLabel - reflectionLabel, but only when the row actually
     * carries something to name it BY.
     *
     * reflectionLabel always appends `input_mode` (defaulting to "typed")
     * so a history row can never render blank. That safety net reads as
     * nonsense the moment it stands alone: an empty lineage object would
     * produce the sentence "Continuing typed". Here a missing identity
     * must collapse to "" so the caller hides the line instead.
     */
    function _nameableLabel(r) {
        if (!r || typeof r !== "object") return "";
        var named = typeof r.title === "string" && r.title.trim();
        if (!named && !r.iso_week && !r.created_at) return "";
        return reflectionLabel(r);
    }

    function continuationNote(parent) {
        var label = _nameableLabel(parent);
        if (!label) return "";
        return "Continuing " + label
            + " — its words are below. Finishing saves a NEW reflection; "
            + "the original is left exactly as it is.";
    }

    /**
     * lineageNote - the "grew out of" line under a history row. (#334)
     *
     * Without it a forked reflection looks like someone wrote the same
     * opening paragraphs twice.
     */
    function lineageNote(r) {
        if (!r || typeof r !== "object") return "";
        var label = _nameableLabel(r.continued_from);
        return label ? "↳ continues " + label : "";
    }

    /**
     * continueBlockedReason - may we fork right now? (#334)
     *
     * The server refuses with 409 when a draft holding work is already
     * open, and refusing is the only safe answer: drafts are hard-deleted
     * with no recycle bin, and these sittings run for hours. Checking
     * client-side too means the user reads WHY before a request fires,
     * rather than after.
     *
     * Text, voice segments and attachments each count as work — a file
     * attached before a word was typed is still something to protect.
     * Returns null when forking is fine.
     */
    function continueBlockedReason(draft) {
        if (!draft || typeof draft !== "object") return null;
        var hasText = typeof draft.transcript === "string"
            && draft.transcript.trim().length > 0;
        var hasSegments = Array.isArray(draft.raw_segments)
            && draft.raw_segments.length > 0;
        var hasFiles = Array.isArray(draft.context_files)
            && draft.context_files.length > 0;
        if (!hasText && !hasSegments && !hasFiles) return null;
        var holding = [];
        if (hasText) holding.push("text");
        if (hasSegments) holding.push("recorded audio");
        if (hasFiles) {
            holding.push(draft.context_files.length === 1
                ? "1 attached document"
                : draft.context_files.length + " attached documents");
        }
        return "You already have a reflection in progress ("
            + holding.join(", ")
            + "). Finish or discard it before continuing a past one.";
    }

    /**
     * MAX_COMBINED - mirrors reflection_service.MAX_COMBINED (#335).
     *
     * Client-side so the bar can say "that's too many" while the user is
     * still ticking boxes, rather than after a paid round trip. The
     * server re-checks; this is courtesy, never the gate.
     */
    var MAX_COMBINED = 10;

    /**
     * combinedSelectionText - what the "analyze together" bar says. (#335)
     *
     * Three states the user can be in, each needing different words:
     * one ticked (not yet useful - say what's missing), a workable set
     * (say what will happen and that it costs), too many (say the limit).
     * Returning `enabled` alongside the copy keeps the button's state and
     * its label derived from the same rule.
     */
    function combinedSelectionText(count, max) {
        var cap = typeof max === "number" && max > 0 ? max : MAX_COMBINED;
        var n = typeof count === "number" && count > 0 ? Math.floor(count) : 0;
        if (n === 0) return { summary: "", buttonLabel: "", enabled: false };
        if (n === 1) {
            return {
                summary: "1 reflection selected — pick at least one more to "
                    + "read them together.",
                buttonLabel: "Analyze together",
                enabled: false,
            };
        }
        if (n > cap) {
            return {
                summary: n + " selected — " + cap + " is the most that can be "
                    + "read together. The reply length is capped however "
                    + "much goes in, so more would give you a thinner answer, "
                    + "not a richer one.",
                buttonLabel: "Analyze together",
                enabled: false,
            };
        }
        return {
            summary: n + " reflections selected.",
            buttonLabel: "Analyze " + n + " together",
            enabled: true,
        };
    }

    /**
     * combinedReviewNote - what the review screen says about a synthesis.
     *
     * Without it a list of proposals on the review screen looks like it
     * came from whichever reflection happened to be open, and the user
     * has no way to tell how far back it looked.
     */
    function combinedReviewNote(count, shortened) {
        var n = typeof count === "number" && count > 0 ? Math.floor(count) : 0;
        if (!n) return "";
        var note = n === 1
            ? "Read across 1 reflection."
            : "Read across " + n + " reflections, in full.";
        note += " Applying these works exactly as it does for a single "
            + "reflection — nothing changes until you confirm.";
        if (Array.isArray(shortened) && shortened.length) {
            note += " Note: " + shortened.join(", ")
                + (shortened.length === 1 ? " was" : " were")
                + " too long to include in full and got shortened.";
        }
        return note;
    }

    /**
     * synthesisBadge - marks a combined-analysis row in history. (#335)
     *
     * A synthesis row's transcript is a header listing its sources, so
     * without a badge it reads as a reflection where someone typed a list
     * of dates. Counted from the stored ids, which the row already
     * carries — no lookup.
     */
    function synthesisBadge(r) {
        if (!r || typeof r !== "object") return "";
        var ids = r.synthesis_of;
        if (!Array.isArray(ids) || !ids.length) return "";
        return ids.length === 1
            ? "🔗 Combined analysis of 1 reflection"
            : "🔗 Combined analysis of " + ids.length + " reflections";
    }

    var api = {
        attachmentLabel: attachmentLabel,
        attachmentSummary: attachmentSummary,
        attachmentPreflight: attachmentPreflight,
        ATTACHMENT_EXTENSIONS: ATTACHMENT_EXTENSIONS,
        defaultChecked: defaultChecked,
        autoPauseReason: autoPauseReason,
        formatRecordingTime: formatRecordingTime,
        actionLabel: actionLabel,
        changeSummary: changeSummary,
        focusCandidates: focusCandidates,
        applySummaryText: applySummaryText,
        selectedActions: selectedActions,
        appendTranscriptSegment: appendTranscriptSegment,
        shouldAutosaveDraft: shouldAutosaveDraft,
        milestoneHeadline: milestoneHeadline,
        formatSavedAt: formatSavedAt,
        voiceIdleCopy: voiceIdleCopy,
        blocksAutoReload: blocksAutoReload,
        reflectionLabel: reflectionLabel,
        reflectionIsNamed: reflectionIsNamed,
        continuationNote: continuationNote,
        lineageNote: lineageNote,
        continueBlockedReason: continueBlockedReason,
        combinedSelectionText: combinedSelectionText,
        combinedReviewNote: combinedReviewNote,
        synthesisBadge: synthesisBadge,
        MAX_COMBINED: MAX_COMBINED,
        AUTO_RELOAD_BLOCKING_STATES: AUTO_RELOAD_BLOCKING_STATES,
    };

    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    } else if (typeof window !== "undefined") {
        window.reflectionHelpers = api;
    }
})();
