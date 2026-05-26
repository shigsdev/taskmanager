/**
 * Weekly Reflection page (#165 frontend, 2026-05-17).
 *
 * State machine:
 *   input → analyzing → review → done
 *                     ↘ error  (transcript already saved server-side;
 *                                visible in History for re-analysis)
 *
 * Input is EITHER a typed textarea (POST JSON {text}) OR a recorded
 * audio memo (POST multipart "audio", reusing the Whisper pipeline the
 * server already wires for voice memos). Submit always persists the
 * transcript BEFORE the Claude call (backend reorder, commit 13cf7f5),
 * so a Claude failure yields a saved-but-unanalyzed reflection rather
 * than data loss.
 *
 * Review renders Claude's two proposal buckets — "explicit" (things you
 * said, checked by default) and "suggested" (proactive ideas, unchecked)
 * — and Apply routes the user-selected subset through
 * POST /api/reflection/<id>/confirm. Creations are recycle-bin-undoable
 * and deletes are soft (backend apply_selected_actions).
 *
 * "✨ Use as Next Week's Focus" seeds the #157 Next Week focus slots via
 * PATCH /api/weekly-focus/<slot>?week_offset=1.
 *
 * Pure branchy logic lives in reflection_helpers.js (Jest-tested per
 * CLAUDE.md anti-pattern #3); this file is DOM + network glue.
 */
(function () {
    "use strict";

    var H = window.reflectionHelpers || {};
    var MAX_RECORDING_MS = 10 * 60 * 1000;

    var states = {
        input: document.getElementById("reflStateInput"),
        analyzing: document.getElementById("reflStateAnalyzing"),
        review: document.getElementById("reflStateReview"),
        done: document.getElementById("reflStateDone"),
        error: document.getElementById("reflStateError"),
    };

    // Input refs
    var tabType = document.getElementById("reflTabType");
    var tabVoice = document.getElementById("reflTabVoice");
    var typedWrap = document.getElementById("reflTyped");
    var voiceWrap = document.getElementById("reflVoice");
    var textArea = document.getElementById("reflText");
    var analyzeBtn = document.getElementById("reflAnalyzeBtn");

    var voiceIdle = document.getElementById("reflVoiceIdle");
    var voiceRecording = document.getElementById("reflVoiceRecording");
    var voicePaused = document.getElementById("reflVoicePaused");
    var voiceTranscribing = document.getElementById("reflVoiceTranscribing");
    var voiceStatus = document.getElementById("reflVoiceStatus");
    var recordBtn = document.getElementById("reflRecordBtn");
    var pauseBtn = document.getElementById("reflPauseBtn");
    var resumeBtn = document.getElementById("reflResumeBtn");
    var doneBtn = document.getElementById("reflDoneBtn");
    var cancelBtn = document.getElementById("reflCancelBtn");
    var cancelBtn2 = document.getElementById("reflCancelBtn2");
    var timerEl = document.getElementById("reflTimer");
    var segmentError = document.getElementById("reflSegmentError");
    var segmentErrorMsg = document.getElementById("reflSegmentErrorMsg");
    var segmentRetryBtn = document.getElementById("reflSegmentRetryBtn");
    var segmentSkipBtn = document.getElementById("reflSegmentSkipBtn");

    var stepSave = document.getElementById("reflStepSave");
    var stepClaude = document.getElementById("reflStepClaude");

    // Review refs
    var bucketsEl = document.getElementById("reflBuckets");
    var emptyEl = document.getElementById("reflEmpty");
    var costHintEl = document.getElementById("reflCostHint");
    var transcriptEl = document.getElementById("reflTranscript");
    var applyBtn = document.getElementById("reflApplyBtn");
    var focusBtn = document.getElementById("reflFocusBtn");
    var startOverBtn = document.getElementById("reflStartOverBtn");

    // Done refs
    var doneMessage = document.getElementById("reflDoneMessage");
    var doneSummary = document.getElementById("reflDoneSummary");
    var anotherBtn = document.getElementById("reflAnotherBtn");

    // Error refs
    var errorMessage = document.getElementById("reflErrorMessage");
    var errorSaved = document.getElementById("reflErrorSaved");
    var retryBtn = document.getElementById("reflRetryBtn");

    // Focus modal refs
    var focusModal = document.getElementById("reflFocusModal");
    var focusChoices = document.getElementById("reflFocusChoices");
    var focusMaxEl = document.getElementById("reflFocusMax");
    var focusApply = document.getElementById("reflFocusApply");
    var focusCancel = document.getElementById("reflFocusCancel");
    var focusClose = document.getElementById("reflFocusClose");

    var historyEl = document.getElementById("reflHistory");

    // ---- runtime state ----
    var current = null;          // last serialized reflection
    var checkedMap = {};         // "bucket:idx" → bool
    var mediaRecorder = null;
    var mediaStream = null;
    var chunks = [];
    var recordStartMs = 0;
    var recordTimerId = null;
    var recordCapTimeoutId = null;
    var focusSlotCount = 3;

    function showState(name) {
        Object.keys(states).forEach(function (k) {
            if (states[k]) states[k].style.display = (k === name) ? "" : "none";
        });
    }

    // ---- input mode tabs ----

    function selectMode(mode) {
        var typed = mode === "type";
        tabType.classList.toggle("active", typed);
        tabVoice.classList.toggle("active", !typed);
        typedWrap.style.display = typed ? "" : "none";
        voiceWrap.style.display = typed ? "none" : "";
    }
    tabType.addEventListener("click", function () { selectMode("type"); });
    tabVoice.addEventListener("click", function () { selectMode("voice"); });

    // ---- typed submit ----

    analyzeBtn.addEventListener("click", function () {
        var text = (textArea.value || "").trim();
        if (!text) {
            alert("Write something to reflect on first.");
            return;
        }
        submitReflection({ json: { text: text } });
    });

    // ---- voice submit (#232 — pause/resume + append-to-textarea) ----
    //
    // State machine:
    //
    //   idle ─Record→ recording ─Pause→ (segment uploads in background)
    //                  │                       ↓
    //                  Cancel              transcribing
    //                  ↓                       ↓
    //                idle                paused ─Resume→ recording (loop)
    //                                          │
    //                                          Done → finalize → submit
    //                                          │
    //                                          Cancel → discard last
    //                                                   recording but keep
    //                                                   prior textarea text
    //
    // The mic stream is created on first Record and stays alive across
    // Pause/Resume cycles so the user doesn't get a permission prompt
    // again. It's only released on Done or Cancel.
    //
    // Each Pause stops the MediaRecorder; its `onstop` fires and uploads
    // the segment to /api/reflection/transcribe-segment. While the
    // upload is in flight we show the "Transcribing…" sub-state. On
    // success the returned transcript is appended to #reflText via
    // reflectionHelpers.appendTranscriptSegment(). On failure the
    // segment-error UI offers Retry (re-uploads the same blob) or Skip
    // (drops the segment, keeps prior text intact).
    //
    // Resume is disabled while a segment is transcribing — prevents
    // out-of-order text appends and bounds concurrent Whisper calls.

    if (!navigator.mediaDevices || !window.MediaRecorder) {
        // Disable the record tab gracefully — typed still works.
        tabVoice.disabled = true;
        tabVoice.title = "Audio recording unsupported in this browser";
    }

    var voiceSubState = "idle";  // idle|recording|transcribing|paused|error
    var lastSegmentBlob = null;  // kept around for Retry
    var lastSegmentMime = null;
    var hasSegmentText = false;  // true once at least one segment landed in textarea
    // #237 (2026-05-26): buffer of raw per-segment Whisper transcripts.
    // Each push: { text, duration_seconds, cost_usd, recorded_at }.
    // Sent alongside the final merged textarea content on Done so the
    // server can persist the original (pre-edit) words for audit
    // (Reflection.raw_segments column). Cleared by cancelEverything +
    // finalizeAndSubmit.
    var rawSegments = [];

    function showVoiceSubState(name) {
        voiceSubState = name;
        voiceIdle.style.display = (name === "idle") ? "" : "none";
        voiceRecording.style.display = (name === "recording") ? "" : "none";
        voicePaused.style.display = (name === "paused") ? "" : "none";
        voiceTranscribing.style.display = (name === "transcribing") ? "" : "none";
        segmentError.style.display = (name === "error") ? "" : "none";
    }

    recordBtn.addEventListener("click", function () { startSegment(/*resume=*/false); });
    resumeBtn.addEventListener("click", function () { startSegment(/*resume=*/true); });
    pauseBtn.addEventListener("click", pauseSegment);
    doneBtn.addEventListener("click", finalizeAndSubmit);
    cancelBtn.addEventListener("click", cancelEverything);
    cancelBtn2.addEventListener("click", cancelEverything);
    segmentRetryBtn.addEventListener("click", retryLastSegment);
    segmentSkipBtn.addEventListener("click", skipLastSegment);

    async function startSegment(isResume) {
        if (!navigator.mediaDevices || !window.MediaRecorder) {
            showErr("This browser doesn't support audio recording. "
                + "Use the Type tab instead.", false);
            return;
        }
        if (!mediaStream) {
            // First Record click: request the mic. On Resume the stream
            // is reused, so this branch only runs once per session.
            try {
                mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            } catch (err) {
                var msg = (err && err.name === "NotAllowedError")
                    ? "Microphone access was blocked. Allow it and try again, "
                      + "or use the Type tab."
                    : "Couldn't access the microphone: "
                      + (err && err.message ? err.message : err);
                showErr(msg, false);
                return;
            }
        }
        chunks = [];
        try {
            mediaRecorder = new MediaRecorder(mediaStream);
        } catch (err) {
            stopMediaStream();
            showErr("MediaRecorder failed to initialize: " + err.message, false);
            return;
        }
        mediaRecorder.ondataavailable = function (e) {
            if (e.data && e.data.size > 0) chunks.push(e.data);
        };
        mediaRecorder.onstop = function () {
            // Per-segment upload. Don't release the mic stream — we may
            // resume. Only Done/Cancel release it (stopMediaStream).
            var mime = mediaRecorder.mimeType || "audio/webm";
            var blob = new Blob(chunks, { type: mime });
            if (blob.size === 0) {
                // Empty segment (user paused immediately). Just bounce
                // back to paused without an error.
                showVoiceSubState(hasSegmentText ? "paused" : "idle");
                return;
            }
            uploadSegment(blob, mime);
        };
        mediaRecorder.onerror = function (e) {
            mediaRecorder.onstop = null;
            clearCap();
            stopTimer();
            showSegmentError(
                "Recording error: "
                + ((e.error && e.error.message) || "unknown"),
            );
        };
        recordStartMs = Date.now();
        startTimer();
        // Per-segment 10-min cap (was per-session before #232). Each
        // segment can be up to 10 min; user can chain many.
        recordCapTimeoutId = setTimeout(pauseSegment, MAX_RECORDING_MS);
        mediaRecorder.start();
        showVoiceSubState("recording");
    }

    document.addEventListener("visibilitychange", function () {
        if (document.visibilityState !== "visible") return;
        if (!mediaRecorder || mediaRecorder.state !== "recording") return;
        // iOS Safari freezes setTimeout when backgrounded; re-check the
        // per-segment cap when foregrounding.
        if (Date.now() - recordStartMs >= MAX_RECORDING_MS) pauseSegment();
    });

    function pauseSegment() {
        clearCap();
        stopTimer();
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            // The onstop handler will pick up here and either upload
            // the segment OR (if empty) bounce back to paused/idle.
            showVoiceSubState("transcribing");
            mediaRecorder.stop();
        } else {
            // Already inactive — show the appropriate idle state.
            showVoiceSubState(hasSegmentText ? "paused" : "idle");
        }
    }

    async function uploadSegment(blob, mime) {
        lastSegmentBlob = blob;
        lastSegmentMime = mime;
        showVoiceSubState("transcribing");
        var fd = new FormData();
        fd.append("audio", blob, "reflection-segment." + mimeExt(mime));
        var data;
        try {
            data = await window.apiFetch(
                "/api/reflection/transcribe-segment",
                {
                    method: "POST",
                    credentials: "same-origin",
                    body: fd,
                },
            );
        } catch (err) {
            showSegmentError(
                "Transcription failed: "
                + (err && err.message ? err.message : err),
            );
            return;
        }
        var seg = (data && data.transcript) || "";
        if (seg.trim() === "") {
            // Whisper returned empty — no words heard. Don't append, just
            // tell the user and let them try again.
            voiceStatus.textContent =
                "Last segment was silent — try again.";
            showVoiceSubState(hasSegmentText ? "paused" : "idle");
            return;
        }
        var H_ = window.reflectionHelpers || {};
        if (typeof H_.appendTranscriptSegment === "function") {
            textArea.value = H_.appendTranscriptSegment(textArea.value, seg);
        } else {
            // Defensive fallback (helpers file failed to load).
            textArea.value = (textArea.value
                ? textArea.value + " " : "") + seg;
        }
        hasSegmentText = true;
        // #237 (2026-05-26): buffer the raw Whisper output for this
        // segment so we can ship the full audit-trail to the server on
        // Done. The textarea above is the (possibly edited) form the
        // user will eventually submit; this is the verbatim Whisper
        // output the user MIGHT edit between segments. Both are
        // persisted (Reflection.transcript vs Reflection.raw_segments).
        rawSegments.push({
            text: seg,
            duration_seconds: (data && typeof data.duration_seconds === "number")
                ? data.duration_seconds
                : null,
            cost_usd: (data && typeof data.cost_usd === "number")
                ? data.cost_usd
                : null,
            recorded_at: new Date().toISOString(),
        });
        var wc = seg.split(/\s+/).filter(Boolean).length;
        voiceStatus.textContent =
            "Added " + wc + " word" + (wc === 1 ? "" : "s") + ". "
            + "Resume to add more, or Done to analyze.";
        // Successful segment — drop the kept-for-retry blob so a future
        // Retry click doesn't re-upload the already-applied segment.
        lastSegmentBlob = null;
        lastSegmentMime = null;
        showVoiceSubState("paused");
    }

    function showSegmentError(msg) {
        segmentErrorMsg.textContent = msg;
        showVoiceSubState("error");
    }

    async function retryLastSegment() {
        if (!lastSegmentBlob) {
            // Lost the blob — best we can do is bounce back to paused.
            showVoiceSubState(hasSegmentText ? "paused" : "idle");
            return;
        }
        await uploadSegment(lastSegmentBlob, lastSegmentMime);
    }

    function skipLastSegment() {
        lastSegmentBlob = null;
        lastSegmentMime = null;
        showVoiceSubState(hasSegmentText ? "paused" : "idle");
    }

    async function finalizeAndSubmit() {
        // If a segment is currently transcribing, wait for it to
        // resolve (the next paused state). The simplest correct way is
        // a short poll on voiceSubState — uploadSegment is the only
        // thing that flips us out of "transcribing".
        if (voiceSubState === "transcribing") {
            await new Promise(function (resolve) {
                var iv = setInterval(function () {
                    if (voiceSubState !== "transcribing") {
                        clearInterval(iv);
                        resolve();
                    }
                }, 100);
            });
        }
        // If the wait surfaced a segment-error, bail out — user picks
        // Retry / Skip before retrying Done.
        if (voiceSubState === "error") return;
        stopMediaStream();
        chunks = [];
        hasSegmentText = false;
        var text = (textArea.value || "").trim();
        if (!text) {
            alert("Record or type something to reflect on first.");
            showVoiceSubState("idle");
            return;
        }
        // #237 (2026-05-26): include the per-segment raw transcripts
        // alongside the final merged text. Server persists both —
        // `transcript` = the user's edited final form, `raw_segments`
        // = the verbatim Whisper output per segment. Snapshot + clear
        // the buffer before posting so a slow network round-trip
        // can't accidentally re-include them on a follow-up submit.
        var segmentsSnapshot = rawSegments.slice();
        rawSegments = [];
        var payload = { text: text };
        if (segmentsSnapshot.length > 0) {
            payload.raw_segments = segmentsSnapshot;
        }
        submitReflection({ json: payload });
    }

    function cancelEverything() {
        clearCap();
        stopTimer();
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            // Drop the onstop so we don't upload the discarded segment.
            mediaRecorder.onstop = null;
            mediaRecorder.stop();
        }
        stopMediaStream();
        chunks = [];
        lastSegmentBlob = null;
        lastSegmentMime = null;
        // Prior segments' text in #reflText INTENTIONALLY survives Cancel
        // — the user can hit Cancel mid-session to abandon a bad segment
        // without losing the words they already committed.
        hasSegmentText = false;
        showVoiceSubState("idle");
    }

    function clearCap() {
        if (recordCapTimeoutId) {
            clearTimeout(recordCapTimeoutId);
            recordCapTimeoutId = null;
        }
    }
    function stopMediaStream() {
        if (mediaStream) {
            mediaStream.getTracks().forEach(function (t) { t.stop(); });
            mediaStream = null;
        }
    }
    function startTimer() {
        updateTimer();
        recordTimerId = setInterval(updateTimer, 250);
    }
    function stopTimer() {
        if (recordTimerId) {
            clearInterval(recordTimerId);
            recordTimerId = null;
        }
    }
    function updateTimer() {
        var totalSec = Math.floor((Date.now() - recordStartMs) / 1000);
        var m = Math.floor(totalSec / 60);
        var s = totalSec % 60;
        timerEl.textContent = m + ":" + (s < 10 ? "0" : "") + s;
    }
    function mimeExt(mt) {
        mt = (mt || "").toLowerCase().split(";")[0];
        if (mt.indexOf("mp4") !== -1) return "mp4";
        if (mt.indexOf("mpeg") !== -1) return "mp3";
        if (mt.indexOf("ogg") !== -1) return "ogg";
        if (mt.indexOf("wav") !== -1) return "wav";
        return "webm";
    }

    // ---- submit + analyze ----

    async function submitReflection(opts) {
        showState("analyzing");
        markStep(stepSave, "running");
        markStep(stepClaude, "pending");

        var fetchOpts = { method: "POST", credentials: "same-origin" };
        if (opts.form) {
            fetchOpts.body = opts.form;
        } else {
            fetchOpts.body = JSON.stringify(opts.json);
        }

        var data;
        try {
            data = await window.apiFetch("/api/reflection", fetchOpts);
        } catch (err) {
            // apiFetch throws on !ok. The 422/500 saved-but-unanalyzed
            // body carries {saved:true, reflection_id}; apiFetch only
            // surfaces .message, so we can't read saved flag here —
            // tell the user the transcript was kept (always true now,
            // backend persists before the Claude call) and point them
            // at History.
            markStep(stepSave, "done");
            markStep(stepClaude, "fail");
            showErr("Analysis failed: " + (err.message || err), true);
            loadHistory();
            return;
        }
        markStep(stepSave, "done");
        markStep(stepClaude, "done");
        current = data;
        renderReview(data);
        loadHistory();
    }

    function markStep(el, st) {
        if (!el) return;
        var prefix = st === "done" ? "✓ "
            : st === "running" ? "⏳ "
            : st === "fail" ? "✗ "
            : "○ ";
        el.textContent = prefix + el.textContent.replace(/^\S+\s/, "");
    }

    // ---- review ----

    var BUCKETS = [
        { key: "explicit", label: "From your reflection" },
        { key: "suggested", label: "Suggested cleanup (optional)" },
    ];

    function renderReview(refl) {
        checkedMap = {};
        bucketsEl.innerHTML = "";
        var proposed = (refl && refl.proposed_actions) || {};
        var total = (proposed.explicit || []).length
            + (proposed.suggested || []).length;

        if (total === 0) {
            emptyEl.style.display = "";
            applyBtn.style.display = "none";
            focusBtn.style.display = "none";
        } else {
            emptyEl.style.display = "none";
            applyBtn.style.display = "";
            focusBtn.style.display = "";
        }

        BUCKETS.forEach(function (b) {
            var rows = proposed[b.key] || [];
            if (rows.length === 0) return;
            var section = document.createElement("section");
            section.className = "reflection-bucket";

            var h = document.createElement("h3");
            h.textContent = b.label + " (" + rows.length + ")";
            section.appendChild(h);

            rows.forEach(function (action, idx) {
                section.appendChild(renderActionRow(action, b.key, idx));
            });
            bucketsEl.appendChild(section);
        });

        var cost = refl && refl.ai_cost_usd;
        costHintEl.textContent = cost
            ? "Claude analysis cost ~$" + Number(cost).toFixed(4) + "."
            : "";
        transcriptEl.textContent = (refl && refl.transcript) || "(no transcript)";
        updateApplyLabel();
        showState("review");
    }

    function renderActionRow(action, bucket, idx) {
        var key = bucket + ":" + idx;
        var checked = H.defaultChecked(bucket);
        checkedMap[key] = checked;

        var row = document.createElement("div");
        row.className = "reflection-action-row op-" + (action.op || "");

        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.className = "reflection-action-check";
        cb.checked = checked;
        cb.addEventListener("change", function () {
            checkedMap[key] = cb.checked;
            updateApplyLabel();
        });
        row.appendChild(cb);

        var body = document.createElement("div");
        body.className = "reflection-action-body";

        var title = document.createElement("div");
        title.className = "reflection-action-title";
        var badge = document.createElement("span");
        badge.className = "reflection-op-badge op-" + (action.op || "");
        badge.textContent = (action.op || "?").toUpperCase();
        title.appendChild(badge);
        var label = document.createElement("span");
        label.textContent = H.actionLabel(action);
        title.appendChild(label);
        body.appendChild(title);

        var diff = H.changeSummary(action.changes);
        if (diff) {
            var d = document.createElement("div");
            d.className = "reflection-action-diff";
            d.textContent = diff;
            body.appendChild(d);
        }
        if (action.reason) {
            var r = document.createElement("div");
            r.className = "reflection-action-reason";
            r.textContent = action.reason;
            body.appendChild(r);
        }
        row.appendChild(body);
        return row;
    }

    function updateApplyLabel() {
        var n = H.selectedActions(
            (current && current.proposed_actions) || {}, checkedMap
        ).length;
        applyBtn.textContent = "Apply Selected (" + n + ")";
        applyBtn.disabled = n === 0;
    }

    // ---- apply ----

    applyBtn.addEventListener("click", async function () {
        if (!current) return;
        var actions = H.selectedActions(current.proposed_actions || {}, checkedMap);
        if (actions.length === 0) return;
        applyBtn.disabled = true;
        applyBtn.textContent = "Applying…";
        var resp;
        try {
            resp = await window.apiFetch(
                "/api/reflection/" + current.id + "/confirm",
                { method: "POST", body: JSON.stringify({ actions: actions }) }
            );
        } catch (err) {
            applyBtn.disabled = false;
            updateApplyLabel();
            showErr("Apply failed: " + (err.message || err), false);
            return;
        }
        renderDone(resp && resp.summary);
        loadHistory();
    });

    function renderDone(summary) {
        var text = H.applySummaryText(summary);
        doneMessage.textContent = text
            ? "Done. " + text
            : "Done — no changes were applied.";
        doneSummary.innerHTML = "";
        if (summary && Array.isArray(summary.errors) && summary.errors.length) {
            summary.errors.forEach(function (e) {
                var li = document.createElement("li");
                li.className = "reflection-done-error";
                li.textContent = e;
                doneSummary.appendChild(li);
            });
        }
        showState("done");
    }

    // ---- ✨ Use as Next Week's Focus ----

    focusBtn.addEventListener("click", openFocusModal);
    focusCancel.addEventListener("click", closeFocusModal);
    focusClose.addEventListener("click", closeFocusModal);
    focusModal.querySelector(".reflection-focus-backdrop")
        .addEventListener("click", closeFocusModal);

    async function openFocusModal() {
        var proposed = (current && current.proposed_actions) || {};
        // Pull slot_count for the Next Week tab so we cap correctly.
        try {
            var wf = await window.apiFetch("/api/weekly-focus?week_offset=1");
            focusSlotCount = (wf && wf.slot_count) || 3;
        } catch (e) {
            focusSlotCount = 3;
        }
        focusMaxEl.textContent = String(focusSlotCount);
        var candidates = H.focusCandidates(proposed, focusSlotCount);
        focusChoices.innerHTML = "";
        if (candidates.length === 0) {
            var p = document.createElement("p");
            p.className = "reflection-hint";
            p.textContent = "No task/goal statements in this reflection to "
                + "turn into focus items.";
            focusChoices.appendChild(p);
            focusApply.disabled = true;
        } else {
            focusApply.disabled = false;
            candidates.forEach(function (text, i) {
                var lbl = document.createElement("label");
                lbl.className = "reflection-focus-choice";
                var cb = document.createElement("input");
                cb.type = "checkbox";
                cb.value = text;
                cb.checked = i < focusSlotCount;
                cb.addEventListener("change", enforceFocusCap);
                lbl.appendChild(cb);
                var span = document.createElement("span");
                span.textContent = text;
                lbl.appendChild(span);
                focusChoices.appendChild(lbl);
            });
        }
        focusModal.style.display = "";
    }

    function enforceFocusCap() {
        var boxes = focusChoices.querySelectorAll("input[type=checkbox]");
        var n = 0;
        boxes.forEach(function (b) { if (b.checked) n++; });
        boxes.forEach(function (b) {
            b.disabled = !b.checked && n >= focusSlotCount;
        });
        focusApply.disabled = n === 0;
    }

    function closeFocusModal() {
        focusModal.style.display = "none";
    }

    focusApply.addEventListener("click", async function () {
        var picked = [];
        focusChoices.querySelectorAll("input[type=checkbox]").forEach(
            function (b) { if (b.checked) picked.push(b.value); }
        );
        if (picked.length === 0) return;
        focusApply.disabled = true;
        focusApply.textContent = "Setting…";
        var failed = 0;
        for (var i = 0; i < picked.length && i < focusSlotCount; i++) {
            try {
                await window.apiFetch(
                    "/api/weekly-focus/" + (i + 1) + "?week_offset=1",
                    {
                        method: "PATCH",
                        body: JSON.stringify({ text: picked[i], goal_id: null }),
                    }
                );
            } catch (e) {
                failed += 1;
            }
        }
        focusApply.textContent = "Set Focus";
        focusApply.disabled = false;
        closeFocusModal();
        if (failed === 0) {
            focusBtn.textContent = "✓ Set as Next Week's Focus";
            focusBtn.disabled = true;
        } else {
            alert(failed + " focus slot(s) failed to save.");
        }
    });

    // ---- start over / retry / another ----

    function resetInput() {
        textArea.value = "";
        // #237: also clear the raw-segments buffer when starting over.
        // Without this, a new reflection started via "Start Over" /
        // "New Reflection" / "Try Again" would carry the prior
        // session's raw segments into the next submit — confusingly
        // attaching old voice transcripts to a fresh typed reflection.
        rawSegments = [];
        showState("input");
        selectMode("type");
        focusBtn.disabled = false;
        focusBtn.textContent = "✨ Use as Next Week's Focus";
    }
    startOverBtn.addEventListener("click", resetInput);
    anotherBtn.addEventListener("click", resetInput);
    retryBtn.addEventListener("click", resetInput);

    function showErr(message, savedTranscript) {
        errorMessage.textContent = message || "Unknown error.";
        errorSaved.style.display = savedTranscript ? "" : "none";
        showState("error");
    }

    // ---- history ----

    async function loadHistory() {
        try {
            var data = await window.apiFetch("/api/reflection");
            renderHistory((data && data.reflections) || []);
        } catch (e) {
            historyEl.innerHTML =
                '<p class="reflection-hint">Couldn\'t load history.</p>';
        }
    }

    function renderHistory(list) {
        historyEl.innerHTML = "";
        if (list.length === 0) {
            historyEl.innerHTML =
                '<p class="reflection-hint">No past reflections yet.</p>';
            return;
        }
        list.forEach(function (r) {
            var item = document.createElement("details");
            item.className = "reflection-history-item";
            var sum = document.createElement("summary");
            var when = (r.created_at || "").slice(0, 10);
            var applied = r.applied_at ? " ✓ applied" : "";
            sum.textContent = r.iso_week + " · " + when
                + " · " + (r.input_mode || "typed") + applied;
            item.appendChild(sum);
            var pre = document.createElement("pre");
            pre.className = "reflection-history-transcript";
            pre.textContent = r.transcript || "(no transcript)";
            item.appendChild(pre);
            historyEl.appendChild(item);
        });
    }

    // ---- init ----
    selectMode("type");
    showState("input");
    loadHistory();
})();
