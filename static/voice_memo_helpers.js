/**
 * Pure helpers for the voice-memo page — #197 (CLAUDE.md anti-pattern #3).
 *
 * `mimeTypeToExt` was branchy classification logic inline in
 * voice_memo.js with zero test coverage. Extracted here as a pure,
 * dual-exported function so Jest can exercise every branch.
 *
 * Dual-export:
 *   Browser: window.voiceMemoHelpers
 *   Node (Jest): module.exports
 */
"use strict";

/**
 * Map a MediaRecorder MIME type to the file extension the server's
 * Whisper call expects. Whisper keys off the filename extension, so a
 * recording the browser tags `audio/mp4;codecs=mp4a.40.2` must be
 * uploaded as `recording.mp4`.
 *
 * @param {string} mimeType — e.g. "audio/webm", "audio/mp4;codecs=...".
 * @returns {string} extension WITHOUT the leading dot. Unknown/blank
 *   input falls back to "webm" (the most common MediaRecorder default).
 */
function mimeTypeToExt(mimeType) {
    const mt = (mimeType || "").toLowerCase().split(";")[0];
    if (mt.indexOf("mp4") !== -1) return "mp4";
    if (mt.indexOf("mpeg") !== -1) return "mp3";
    if (mt.indexOf("ogg") !== -1) return "ogg";
    if (mt.indexOf("wav") !== -1) return "wav";
    return "webm";
}

/**
 * #425: the Add All / Add Selected payload. The server routes on `route`
 * (task / goal / project), files a goal under `category`, and turns a row
 * with `repeat` into a recurring template. The old inline map dropped all
 * three, so every dictated goal, project and recurring item became an Inbox
 * task (server tests posted the fields by hand and passed).
 *
 * @param {Array<object>} candidates — the review rows
 * @param {boolean} onlySelected — Add Selected: skip unticked rows
 * @returns {Array<object>} rows with a non-blank title
 */
function buildConfirmPayload(candidates, onlySelected) {
    return (candidates || [])
        .filter(function (c) { return onlySelected ? c.included !== false : true; })
        .map(function (c) {
            const row = {
                title: (c.title || "").trim(),
                type: c.type || "personal",
                tier: c.tier || "inbox",
                due_date: c.due_date || null,
                project_id: c.project_id || null,
                goal_id: c.goal_id || null,
                route: c.route || "task",
                category: c.category || "personal_growth",
                included: true,
            };
            if (c.repeat) row.repeat = c.repeat;
            return row;
        })
        .filter(function (c) { return c.title; });
}

/**
 * #425: why a "Make recurring" choice can't be saved, or null if it can.
 * Mirrors the required fields in recurring_service._validate_frequency_fields
 * so the pop-up refuses an incomplete repeat instead of the server dropping
 * the item at confirm time.
 *
 * @param {{frequency: string, day_of_week?: number|null,
 *          day_of_month?: number|null, week_of_month?: number|null}} repeat
 * @returns {string|null}
 */
function repeatProblem(repeat) {
    const r = repeat || {};
    const hasDow = Number.isInteger(r.day_of_week) && r.day_of_week >= 0 && r.day_of_week <= 6;
    if (r.frequency === "weekly" && !hasDow) {
        return "Pick a day of the week for a weekly repeat.";
    }
    if (r.frequency === "monthly_date") {
        const d = r.day_of_month;
        if (!Number.isInteger(d) || d < 1 || d > 31) {
            return "Pick a day of the month (1-31) for a monthly repeat.";
        }
    }
    if (r.frequency === "monthly_nth_weekday") {
        const w = r.week_of_month;
        if (!Number.isInteger(w) || w < 1 || w > 4) {
            return "Pick which week of the month (1st-4th).";
        }
        if (!hasDow) return "Pick a day of the week.";
    }
    return null;
}

/**
 * #425: the done message, from what the server says it created. The old
 * text was always "N tasks added to Inbox", even for goals, projects,
 * templates and tasks filed in Today.
 *
 * @param {{tasks?: Array, goals?: Array, projects?: Array,
 *          recurring?: Array, warning?: string}|null} data
 * @returns {string}
 */
function confirmSummary(data) {
    const d = data || {};
    const parts = [];
    const add = function (list, one, many) {
        const n = (list || []).length;
        if (n) parts.push(n + " " + (n === 1 ? one : many));
    };
    add(d.tasks, "task", "tasks");
    add(d.goals, "goal", "goals");
    add(d.projects, "project", "projects");
    add(d.recurring, "recurring task", "recurring tasks");
    let msg;
    if (parts.length === 0) {
        msg = "Nothing was added.";
    } else if (parts.length === 1) {
        msg = "Added " + parts[0] + ".";
    } else {
        msg = "Added " + parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1] + ".";
    }
    return d.warning ? msg + " " + d.warning : msg;
}

/**
 * #470: what to say after a failed Add All. The server adds the whole batch
 * in one transaction, so an error it ANSWERED (a 500, the rate limit, a
 * refused list) saved nothing and adding again is safe. With no answer at
 * all (the connection dropped) it may have saved everything before the
 * reply was lost — the one case to check the Inbox first.
 *
 * @param {{status?: number}|null} err — what apiFetch threw
 * @returns {string}
 */
function confirmFailureTail(err) {
    if (err && typeof err.status === "number") {
        return "Nothing was added, and your list is still here — Add All again.";
    }
    return "Your list is still here. The connection dropped before the server answered, "
        + "so check your Inbox before adding again: it may already be there.";
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        mimeTypeToExt, buildConfirmPayload, repeatProblem, confirmSummary, confirmFailureTail,
    };
} else if (typeof window !== "undefined") {
    window.voiceMemoHelpers = {
        mimeTypeToExt, buildConfirmPayload, repeatProblem, confirmSummary, confirmFailureTail,
    };
}
