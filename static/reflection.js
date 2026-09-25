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

    // #326 — how long a single spoken segment may run.
    //
    // The REAL ceiling is Whisper's 25MB per-request limit, which is a
    // SIZE limit, not a duration one. Left unspecified, MediaRecorder
    // picks 128 kbps (measured), which puts 25MB at ~27 minutes — so the
    // old 10-minute cap was a conservative proxy for a ceiling the code
    // couldn't actually predict.
    //
    // Pinning the bitrate makes minutes-per-megabyte knowable. 32 kbps
    // is generous for speech (Whisper downsamples to 16kHz mono
    // internally anyway) and puts 25MB at ~109 minutes, so a 30-minute
    // clock cap now has ~3.6x of headroom instead of 2.6x of guesswork.
    var SPEECH_BITS_PER_SECOND = 32000;
    var MAX_RECORDING_MS = 30 * 60 * 1000;
    // Hard stop well under Whisper's 25MB so a browser that IGNORES the
    // bitrate hint (Safari records AAC and may) still can't produce a
    // segment the API will reject.
    var MAX_SEGMENT_BYTES = 20 * 1024 * 1024;
    // Deliver data every 5s so accumulated size is observable DURING
    // recording — without a timeslice, ondataavailable fires only at
    // stop(), which is far too late to prevent an oversized segment.
    var RECORDER_TIMESLICE_MS = 5000;
    // Warn for the last 2 minutes rather than cutting off mid-sentence.
    var RECORDING_WARN_SEC = 120;

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
    var reviewExit = document.getElementById("reflReviewExit");
    var interimNote = document.getElementById("reflInterimNote");
    var backToWriting = document.getElementById("reflBackToWriting");

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
    // #326: bytes accumulated in THIS segment, and why it auto-paused
    // (null when the user paused deliberately) so the status line can
    // explain an interruption the user didn't ask for.
    var recordedBytes = 0;
    var autoPauseNotice = null;
    // #327: on-device chunk buffer. Null when IndexedDB is unavailable
    // (private mode, old browser) — recording then behaves exactly as
    // it did before, just without the safety net.
    var AB = (typeof window !== "undefined" && window.audioBuffer) || null;
    var currentSegmentId = null;
    var chunkSeq = 0;
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
        // #332: the draft restores asynchronously, so the text may have
        // landed long after the initial render. Re-derive when the Record
        // tab is actually opened, which is the moment the user reads it.
        if (!typed && voiceSubState === "idle") refreshVoiceIdleCopy();
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

    // #333: analyse WITHOUT ending the reflection. Flushes the draft
    // first so the server analyses what is actually on screen, not the
    // text as of the last debounce.
    var interimBtn = document.getElementById("reflInterimBtn");
    if (interimBtn) {
        interimBtn.addEventListener("click", async function () {
            var text = (textArea.value || "").trim();
            if (!text) {
                alert("Write something to reflect on first.");
                return;
            }
            interimBtn.disabled = true;
            showState("analyzing");
            markStep(stepSave, "done");
            markStep(stepClaude, "running");
            try {
                await saveDraftNow();
            } catch (e) { /* the analyze call below surfaces any real problem */ }
            var data;
            try {
                data = await window.apiFetch("/api/reflection/draft/analyze",
                                             { method: "POST" });
            } catch (err) {
                markStep(stepClaude, "fail");
                // Deliberately NOT clearDraftUi(): unlike submit, nothing
                // was retired server-side, so the draft is still live.
                showErr("Analysis failed: " + (err.message || err), true);
                return;
            } finally {
                interimBtn.disabled = false;
            }
            markStep(stepClaude, "done");
            current = data;
            renderReview(data);
        });
    }

    if (backToWriting) {
        backToWriting.addEventListener("click", function () {
            // The draft was never retired, so this is purely a view change.
            showState("input");
        });
    }

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
        if (name === "idle") refreshVoiceIdleCopy();
        // #331: tell base.html's service-worker updater that a reload
        // right now would destroy live audio. Global because that script
        // runs outside this IIFE and cannot see `mediaRecorder`.
        var h331 = (typeof window !== "undefined" && window.reflectionHelpers)
            || null;
        if (typeof window !== "undefined") {
            window.__mediaCaptureBusy = !!(
                h331 && typeof h331.blocksAutoReload === "function"
                    ? h331.blocksAutoReload(name)
                    : (name === "recording" || name === "transcribing")
            );
        }
        voiceIdle.style.display = (name === "idle") ? "" : "none";
        voiceRecording.style.display = (name === "recording") ? "" : "none";
        voicePaused.style.display = (name === "paused") ? "" : "none";
        voiceTranscribing.style.display = (name === "transcribing") ? "" : "none";
        segmentError.style.display = (name === "error") ? "" : "none";
    }

    // #332: the idle controls describe themselves from the text already
    // captured, so "Start recording" never appears over a reflection that
    // is actually mid-flight. Re-derived every time idle is shown, which
    // covers a restored draft, a cancelled segment and a silent segment
    // alike - there is no separate "did we restore?" flag to keep in sync.
    var resumeNote = document.getElementById("reflResumeNote");
    var recordLabelEl = recordBtn
        ? recordBtn.querySelector(".voice-record-label") : null;

    function refreshVoiceIdleCopy() {
        // Read the global rather than the RH_ alias: that alias is
        // declared hundreds of lines below this point, so it is still
        // undefined while init runs.
        var h = (typeof window !== "undefined" && window.reflectionHelpers)
            || null;
        if (!h || typeof h.voiceIdleCopy !== "function") return;
        var copy = h.voiceIdleCopy(textArea ? textArea.value : "");
        if (recordLabelEl) recordLabelEl.textContent = copy.label;
        if (recordBtn) recordBtn.setAttribute("aria-label", copy.aria);
        if (resumeNote) {
            resumeNote.textContent = copy.note;
            resumeNote.style.display = copy.note ? "" : "none";
        }
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
        recordedBytes = 0;
        try {
            // #326: pin the bitrate so minutes-per-megabyte is knowable.
            mediaRecorder = new MediaRecorder(mediaStream, {
                audioBitsPerSecond: SPEECH_BITS_PER_SECOND,
            });
        } catch (err) {
            // A browser that rejects the options form still gets a
            // recorder — the byte budget below is the backstop.
            try {
                mediaRecorder = new MediaRecorder(mediaStream);
            } catch (err2) {
                stopMediaStream();
                showErr(
                    "MediaRecorder failed to initialize: " + err2.message, false,
                );
                return;
            }
        }
        // #327: identify this segment so its buffered chunks can be
        // found (and deleted) independently of any other.
        currentSegmentId = "seg-" + Date.now() + "-"
            + Math.random().toString(36).slice(2, 8);
        chunkSeq = 0;
        if (AB) {
            AB.beginSegment(currentSegmentId, {
                startedAt: Date.now(),
                mime: mediaRecorder.mimeType || "",
            });
        }
        mediaRecorder.ondataavailable = function (e) {
            if (!e.data || e.data.size <= 0) return;
            chunks.push(e.data);
            recordedBytes += e.data.size;
            // #327: persist each chunk as it lands so an evicted tab
            // costs seconds, not the whole segment. Fire-and-forget —
            // a buffer failure must never interrupt recording.
            if (AB) {
                AB.putChunk(
                    currentSegmentId, chunkSeq++, e.data,
                    mediaRecorder.mimeType || "",
                );
            }
            // #326: size is the limit that actually breaks transcription
            // (Whisper rejects >25MB outright), so enforce it live rather
            // than discovering it at upload time.
            if (H.autoPauseReason(
                recordedBytes, MAX_SEGMENT_BYTES, 0, Infinity,
            ) === "size") {
                autoPauseNotice = "size";
                pauseSegment();
            }
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
        autoPauseNotice = null;
        startTimer();
        // Per-segment clock cap (#232 made it per-segment; #326 raised it
        // to 30 min once the bitrate was pinned). Chain as many as you like.
        recordCapTimeoutId = setTimeout(function () {
            autoPauseNotice = "time";
            pauseSegment();
        }, MAX_RECORDING_MS);
        // #326: timeslice so size is observable while recording.
        mediaRecorder.start(RECORDER_TIMESLICE_MS);
        showVoiceSubState("recording");
    }

    document.addEventListener("visibilitychange", function () {
        if (document.visibilityState !== "visible") return;
        if (!mediaRecorder || mediaRecorder.state !== "recording") return;
        // iOS Safari freezes setTimeout when backgrounded; re-check the
        // per-segment cap when foregrounding.
        if (Date.now() - recordStartMs >= MAX_RECORDING_MS) {
            autoPauseNotice = "time";
            pauseSegment();
        }
    });

    /** #326: explain an interruption the user didn't ask for. Returns ""
     *  for a deliberate pause, so the status line stays quiet then. */
    function autoPauseMessage() {
        if (autoPauseNotice === "size") {
            return "Paused automatically — that segment reached the size "
                + "limit for transcription. Your words are saved; hit "
                + "Resume to keep going.";
        }
        if (autoPauseNotice === "time") {
            return "Paused automatically at the 30-minute segment limit. "
                + "Your words are saved; hit Resume to keep going.";
        }
        return "";
    }

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
            // #324: a spoken segment already cost a Whisper call — get it
            // server-side immediately rather than waiting out the typing
            // debounce that a voice user may never trigger.
            if (typeof window.__reflectionSaveDraftNow === "function") {
                window.__reflectionSaveDraftNow();
            }
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
        // #326: if the pause was FORCED (clock or size), say why — being
        // cut off mid-thought with no explanation is the worst version
        // of this. A deliberate pause keeps the normal message.
        var forced = autoPauseMessage();
        voiceStatus.textContent = forced
            ? "Added " + wc + " word" + (wc === 1 ? "" : "s") + ". " + forced
            : "Added " + wc + " word" + (wc === 1 ? "" : "s") + ". "
              + "Resume to add more, or Done to analyze.";
        autoPauseNotice = null;
        // Successful segment — drop the kept-for-retry blob so a future
        // Retry click doesn't re-upload the already-applied segment.
        lastSegmentBlob = null;
        lastSegmentMime = null;
        // #327: transcribed, so the on-disk copy has served its purpose.
        // This is the PRIMARY cleanup path — the words are now safely in
        // the textarea (and the #324 draft), so the audio is redundant.
        if (AB && currentSegmentId) {
            AB.dropSegment(currentSegmentId);
            currentSegmentId = null;
        }
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
        // #327: Done — every segment is transcribed and the text is being
        // submitted, so nothing on disk is still needed. Belt-and-braces
        // over the per-segment drop above.
        if (AB) { AB.purgeAll(); currentSegmentId = null; }
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
        // #327: Cancel means "I don't want that audio" — purge it. The
        // TEXT survives (above); the recording does not.
        if (AB) { AB.purgeAll(); currentSegmentId = null; }
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
        // #326: show the cap, not just the elapsed time. The old timer
        // counted up with no hint a limit existed, so recording simply
        // stopped mid-sentence when it hit one.
        var t = H.formatRecordingTime(
            Date.now() - recordStartMs, MAX_RECORDING_MS, RECORDING_WARN_SEC,
        );
        timerEl.textContent = t.text;
        timerEl.classList.toggle("reflection-timer-warn", t.warn);
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
            // #324: the server retires the draft right after persisting
            // the transcript and BEFORE calling Claude — so on this path
            // the draft is already gone even though analysis failed.
            // Clearing here stops a pending autosave from re-creating a
            // draft holding text that is now a submitted reflection.
            clearDraftUi();
            showErr("Analysis failed: " + (err.message || err), true);
            loadHistory();
            return;
        }
        markStep(stepSave, "done");
        markStep(stepClaude, "done");
        clearDraftUi();  // #324
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
            // #329: nothing to apply makes this screen terminal, so the
            // way out stops being a neutral sibling of "Start Over" and
            // becomes the filled primary. Dropping .btn-sm falls back to
            // the accent-filled .btn rule — no new class, and in
            // particular not the phantom .btn-primary (referenced in
            // several templates, never defined in style.css).
            if (reviewExit) reviewExit.classList.remove("btn-sm");
        } else {
            emptyEl.style.display = "none";
            applyBtn.style.display = "";
            focusBtn.style.display = "";
            // Apply Selected is the primary here; the exit goes back to
            // neutral so it doesn't compete with it.
            if (reviewExit) reviewExit.classList.add("btn-sm");
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

        // #333: a checkpoint review keeps the draft open, so it offers
        // "Back to writing" and hides Start Over — which would clear the
        // box the user is still filling. A final review is unchanged.
        var interim = !!(refl && refl.interim);
        if (interimNote) interimNote.style.display = interim ? "" : "none";
        if (backToWriting) backToWriting.style.display = interim ? "" : "none";
        if (startOverBtn) startOverBtn.style.display = interim ? "none" : "";

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
        // #328: the submitted reflection took its attachments with it;
        // a fresh one starts with none.
        renderAttachments([]);
        setCtxStatus("");
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

    // ---- history (#238: archive + soft-delete + restore) ----

    var showArchivedCheckbox = document.getElementById("reflShowArchived");
    var recentlyDeletedEl = document.getElementById("reflRecentlyDeleted");
    var recentlyDeletedSummary = document.getElementById(
        "reflRecentlyDeletedSummary",
    );

    async function loadHistory() {
        try {
            var url = "/api/reflection"
                + (showArchivedCheckbox && showArchivedCheckbox.checked
                    ? "?include_archived=true" : "");
            var data = await window.apiFetch(url);
            renderHistory((data && data.reflections) || []);
        } catch (e) {
            historyEl.innerHTML =
                '<p class="reflection-hint">Couldn\'t load history.</p>';
        }
        // Recently-deleted is loaded separately so a Show-archived
        // toggle doesn't conflate the two filters.
        loadRecentlyDeleted();
    }

    async function loadRecentlyDeleted() {
        if (!recentlyDeletedEl) return;
        try {
            var data = await window.apiFetch(
                "/api/reflection?include_deleted=true",
            );
            // The list includes BOTH active + deleted rows; filter to
            // just the deleted ones for this section.
            var all = (data && data.reflections) || [];
            var deleted = all.filter(function (r) { return !r.is_active; });
            renderDeletedList(deleted);
        } catch (e) {
            recentlyDeletedEl.innerHTML =
                '<p class="reflection-hint">Couldn\'t load recently-deleted.</p>';
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
            historyEl.appendChild(_renderHistoryItem(r, /*deleted=*/false));
        });
    }

    function renderDeletedList(list) {
        if (recentlyDeletedSummary) {
            recentlyDeletedSummary.textContent =
                "Recently deleted (" + list.length + ")";
        }
        recentlyDeletedEl.innerHTML = "";
        if (list.length === 0) {
            recentlyDeletedEl.innerHTML =
                '<p class="reflection-hint">Nothing in the recycle bin.</p>';
            return;
        }
        list.forEach(function (r) {
            recentlyDeletedEl.appendChild(_renderHistoryItem(r, /*deleted=*/true));
        });
    }

    function _renderHistoryItem(r, deleted) {
        var item = document.createElement("details");
        item.className = "reflection-history-item";
        if (r.is_archived) item.classList.add("reflection-history-item-archived");
        if (deleted) item.classList.add("reflection-history-item-deleted");
        item.dataset.reflectionId = r.id;

        var sum = document.createElement("summary");
        // #339: the name comes from reflectionLabel — a user-given title
        // when there is one, otherwise a generated label that includes
        // the TIME. The old label (week + date + mode) was identical for
        // two sittings on the same day.
        var applied = r.applied_at ? " ✓ applied" : "";
        var archivedTag = r.is_archived ? " · 📥 archived" : "";
        var baseLabel = (RH_ && typeof RH_.reflectionLabel === "function")
            ? RH_.reflectionLabel(r)
            : r.iso_week + " · " + (r.created_at || "").slice(0, 10);
        sum.textContent = baseLabel + applied + archivedTag;
        item.appendChild(sum);

        var pre = document.createElement("pre");
        pre.className = "reflection-history-transcript";
        pre.textContent = r.transcript || "(no transcript)";
        item.appendChild(pre);

        // Per-row action buttons. The set differs for deleted rows
        // (Restore) vs active rows (Archive/Unarchive + Delete).
        var actions = document.createElement("div");
        actions.className = "reflection-history-actions";
        if (deleted) {
            var restoreBtn = document.createElement("button");
            restoreBtn.type = "button";
            restoreBtn.className = "btn btn-sm";
            restoreBtn.textContent = "↺ Restore";
            restoreBtn.addEventListener("click", function () {
                _refreshAfter("/api/reflection/" + r.id + "/restore",
                              { method: "POST" });
            });
            actions.appendChild(restoreBtn);
        } else {
            var archiveBtn = document.createElement("button");
            archiveBtn.type = "button";
            archiveBtn.className = "btn btn-sm";
            archiveBtn.textContent = r.is_archived
                ? "📤 Unarchive" : "📥 Archive";
            archiveBtn.addEventListener("click", function () {
                var path = r.is_archived ? "/unarchive" : "/archive";
                _refreshAfter("/api/reflection/" + r.id + path,
                              { method: "POST" });
            });
            actions.appendChild(archiveBtn);

            // #339: name this sitting. prompt() rather than an inline
            // editor because this is a rare, one-line action and an
            // inline field would add a focus/escape/save state machine
            // to every row in the list for no gain.
            var named = RH_ && typeof RH_.reflectionIsNamed === "function"
                ? RH_.reflectionIsNamed(r) : !!(r.title || "").trim();
            var nameBtn = document.createElement("button");
            nameBtn.type = "button";
            nameBtn.className = "btn btn-sm";
            nameBtn.textContent = named ? "✎ Rename" : "✎ Name it";
            nameBtn.addEventListener("click", async function () {
                var next = window.prompt(
                    "Name this reflection (leave blank to clear the name):",
                    r.title || "");
                if (next === null) return;  // cancelled
                try {
                    await window.apiFetch("/api/reflection/" + r.id, {
                        method: "PATCH",
                        body: JSON.stringify({ title: next }),
                    });
                } catch (err) {
                    alert("Couldn't rename: " + (err.message || err));
                    return;
                }
                loadHistory();
            });
            actions.appendChild(nameBtn);

            // #338: re-run Claude over a reflection that is already
            // saved. The error state has always promised this ("can be
            // re-analyzed later"); until now nothing delivered it, so a
            // reflection whose analysis timed out was stranded forever.
            var reBtn = document.createElement("button");
            reBtn.type = "button";
            reBtn.className = "btn btn-sm";
            reBtn.textContent = r.proposed_actions
                && ((r.proposed_actions.explicit || []).length
                    + (r.proposed_actions.suggested || []).length) > 0
                ? "↻ Re-analyze" : "✨ Analyze";
            reBtn.addEventListener("click", async function () {
                // A paid call on a possibly-large reflection: say so and
                // make it a deliberate click, not a stray one.
                var NL = String.fromCharCode(10);
                if (!confirm("Ask Claude to analyze this reflection?"
                    + NL + NL
                    + "This costs a Claude call and may take up to a "
                    + "couple of minutes on a long reflection.")) return;
                reBtn.disabled = true;
                reBtn.textContent = "Analyzing…";
                var data;
                try {
                    data = await window.apiFetch(
                        "/api/reflection/" + r.id + "/analyze",
                        { method: "POST" },
                    );
                } catch (err) {
                    reBtn.disabled = false;
                    reBtn.textContent = "↻ Re-analyze";
                    showErr("Analysis failed: " + (err.message || err), true);
                    return;
                }
                current = data;
                renderReview(data);
                loadHistory();
            });
            actions.appendChild(reBtn);

            var delBtn = document.createElement("button");
            delBtn.type = "button";
            delBtn.className = "btn btn-sm btn-cancel";
            delBtn.textContent = "🗑️ Delete";
            delBtn.addEventListener("click", function () {
                if (!confirm("Delete this reflection? You can restore "
                    + "it from the Recently-deleted section below.")) {
                    return;
                }
                _refreshAfter("/api/reflection/" + r.id,
                              { method: "DELETE" });
            });
            actions.appendChild(delBtn);
        }
        item.appendChild(actions);
        return item;
    }

    async function _refreshAfter(url, opts) {
        try {
            await window.apiFetch(url, opts);
        } catch (e) {
            alert("Action failed: " + (e && e.message ? e.message : e));
            return;
        }
        loadHistory();  // refreshes BOTH active list AND recently-deleted
    }

    if (showArchivedCheckbox) {
        showArchivedCheckbox.addEventListener("change", loadHistory);
    }

    // ---- draft autosave / restore (#324) ----------------------------
    // A reflection written across several sittings has to survive
    // leaving the page — and has to follow the user between phone and
    // laptop, which rules out localStorage. The draft lives server-side
    // and costs nothing: no Whisper, no Claude, until Analyze.

    // IIFE-scoped alias — the `H_` inside handleSegment() is local to
    // that function, so it isn't visible here.
    var RH_ = window.reflectionHelpers || {};
    var draftBanner = document.getElementById("reflDraftBanner");
    var draftBannerText = document.getElementById("reflDraftBannerText");
    var draftDiscardBtn = document.getElementById("reflDraftDiscard");
    var draftStatus = document.getElementById("reflDraftStatus");
    var DRAFT_DEBOUNCE_MS = 1200;
    var draftTimer = null;
    var lastSavedText = null;   // null = "we've never saved"
    var draftSaving = false;

    function setDraftStatus(msg, isError) {
        if (!draftStatus) return;
        draftStatus.textContent = msg || "";
        draftStatus.classList.toggle("reflection-draft-status-err", !!isError);
    }

    async function saveDraftNow() {
        if (!textArea) return;
        var text = textArea.value || "";
        if (!RH_.shouldAutosaveDraft(lastSavedText, text)) return;
        if (draftSaving) return;  // a save is in flight; the trailing
                                  // debounce will catch any newer text
        draftSaving = true;
        setDraftStatus("Saving…");
        try {
            var body = { text: text };
            if (rawSegments && rawSegments.length) {
                body.raw_segments = rawSegments.slice();
            }
            await window.apiFetch("/api/reflection/draft", {
                method: "PUT",
                body: JSON.stringify(body),
            });
            lastSavedText = text;
            setDraftStatus("Draft saved");
        } catch (e) {
            // Never destructive: the text is still in the textarea. Say
            // so plainly rather than a bare "failed" — the whole point
            // of this feature is trusting that work isn't lost.
            setDraftStatus(
                "Couldn't save draft (your text is still here) — retrying…",
                true,
            );
            scheduleDraftSave(5000);  // back off, then try again
        } finally {
            draftSaving = false;
        }
    }

    function scheduleDraftSave(delayMs) {
        if (draftTimer) clearTimeout(draftTimer);
        draftTimer = setTimeout(saveDraftNow, delayMs || DRAFT_DEBOUNCE_MS);
    }

    function clearDraftUi() {
        lastSavedText = null;
        if (draftTimer) { clearTimeout(draftTimer); draftTimer = null; }
        if (draftBanner) draftBanner.style.display = "none";
        setDraftStatus("");
        // #328: every caller of this is a "the draft is gone" moment —
        // submitted, or discarded. The attachments went with it, so the
        // list must not keep advertising files the server no longer has.
        renderAttachments([]);
        setCtxStatus("");
    }

    // Exposed so the submit path can stop a pending autosave from
    // re-creating the draft the server just retired, and so a landed
    // voice segment can flush immediately.
    window.__reflectionClearDraftUi = clearDraftUi;
    window.__reflectionSaveDraftNow = saveDraftNow;

    if (textArea) {
        textArea.addEventListener("input", function () { scheduleDraftSave(); });
        // Leaving the tab is the classic "lost it" moment — flush now
        // rather than waiting out the debounce.
        document.addEventListener("visibilitychange", function () {
            if (document.visibilityState === "hidden") saveDraftNow();
        });
    }

    if (draftDiscardBtn) {
        draftDiscardBtn.addEventListener("click", async function () {
            if (!confirm("Discard this draft? The text will be deleted.")) return;
            if (draftTimer) { clearTimeout(draftTimer); draftTimer = null; }
            try {
                await window.apiFetch("/api/reflection/draft", { method: "DELETE" });
            } catch (e) { /* fall through — clear locally regardless */ }
            if (textArea) textArea.value = "";
            rawSegments.length = 0;
            clearDraftUi();
        });
    }

    async function restoreDraft() {
        if (!textArea) return;
        var data;
        try {
            data = await window.apiFetch("/api/reflection/draft");
        } catch (e) {
            return;  // no draft UI rather than a scary error on load
        }
        var draft = data && data.draft;
        if (!draft) return;
        // #328: attachments are server truth and restore independently of
        // the text. A file attached before a single word was typed is
        // still work worth bringing back — and it must come back even if
        // the user has already started typing in this tab, because the
        // server would otherwise send it to Claude invisibly.
        renderAttachments(draft.context_files);
        var hasFiles = Array.isArray(draft.context_files)
            && draft.context_files.length > 0;
        if (!draft.transcript && !hasFiles) return;
        // Don't clobber anything the user already started typing in the
        // moment before this fetch returned.
        if ((textArea.value || "").trim()) return;
        textArea.value = draft.transcript || "";
        lastSavedText = draft.transcript || "";
        if (Array.isArray(draft.raw_segments) && draft.raw_segments.length) {
            rawSegments.length = 0;
            draft.raw_segments.forEach(function (s) { rawSegments.push(s); });
        }
        if (draftBanner && draftBannerText) {
            var when = RH_.formatSavedAt(draft.updated_at, Date.now());
            draftBannerText.textContent = when
                ? "Draft restored — last saved " + when
                : "Draft restored";
            draftBanner.style.display = "";
        }
    }

    // ---- context documents (#328) ----
    // Reference material the analysis reads alongside the reflection: a
    // job description, a 30/60/90 plan, a photo of a whiteboard. The
    // uploaded file never leaves the request — the server pulls the text
    // out of it in memory and keeps only that, on the DRAFT, so an
    // attachment follows the user between sittings and devices exactly
    // like the draft text does (#324).

    var ctxInput = document.getElementById("reflContextInput");
    var ctxAddBtn = document.querySelector(".reflection-context-add");
    var ctxList = document.getElementById("reflContextList");
    var ctxSummary = document.getElementById("reflContextSummary");
    var ctxStatus = document.getElementById("reflContextStatus");
    // Mirrors reflection_context_service. The server re-validates
    // everything; these only exist so an obviously-wrong pick fails
    // instantly instead of after a 10MB upload.
    var CTX_MAX_BYTES = 10 * 1024 * 1024;
    var CTX_MAX_FILES = 5;
    var CTX_MAX_CHARS = 60000;
    var ctxBusy = false;

    function setCtxStatus(msg, isError) {
        if (!ctxStatus) return;
        ctxStatus.textContent = msg || "";
        ctxStatus.classList.toggle("reflection-context-status-err", !!isError);
    }

    function buildAttachmentRow(f) {
        var label = RH_.attachmentLabel(f);
        if (!label || !label.name) return null;

        var li = document.createElement("li");
        li.className = "reflection-context-item";

        var text = document.createElement("div");
        text.className = "reflection-context-item-text";
        var name = document.createElement("span");
        name.className = "reflection-context-item-name";
        name.textContent = label.name;
        text.appendChild(name);
        if (label.meta) {
            var meta = document.createElement("span");
            meta.className = "reflection-context-item-meta";
            meta.textContent = label.meta;
            text.appendChild(meta);
        }
        li.appendChild(text);

        var remove = document.createElement("button");
        remove.type = "button";
        remove.className = "btn-link reflection-context-remove";
        remove.textContent = "Remove";
        remove.setAttribute("aria-label", "Remove " + label.name);
        remove.addEventListener("click", function () {
            removeAttachment(f.id, label.name);
        });
        li.appendChild(remove);
        return li;
    }

    function renderAttachments(files, meta) {
        if (!ctxList) return;
        var list = Array.isArray(files) ? files : [];
        ctxList.replaceChildren();
        list.forEach(function (f) {
            var row = buildAttachmentRow(f);
            if (row) ctxList.appendChild(row);
        });

        var maxFiles = (meta && meta.max_files) || CTX_MAX_FILES;
        var maxChars = (meta && meta.max_total_chars) || CTX_MAX_CHARS;
        if (ctxSummary) {
            ctxSummary.textContent = RH_.attachmentSummary(
                list, maxFiles, maxChars,
            );
        }
        // A <label> can't be disabled, but a disabled input makes the
        // label inert — browsers won't open the picker for it. The class
        // is what makes that visible rather than mysterious.
        var full = list.length >= maxFiles;
        if (ctxInput) ctxInput.disabled = full;
        if (ctxAddBtn) {
            ctxAddBtn.classList.toggle("reflection-context-add-disabled", full);
        }
    }

    async function uploadAttachment(file) {
        if (!file || ctxBusy) return;
        var problem = RH_.attachmentPreflight(file, CTX_MAX_BYTES);
        if (problem) { setCtxStatus(problem, true); return; }

        ctxBusy = true;
        setCtxStatus("Reading " + file.name + "…");
        try {
            // Flush any pending text autosave first so the draft the
            // server is about to re-save already carries the newest
            // words — otherwise an attachment can momentarily pin an
            // older transcript back onto the row.
            await saveDraftNow();
            var form = new FormData();
            form.append("file", file);
            var data = await window.apiFetch("/api/reflection/attachment", {
                method: "POST",
                body: form,
            });
            renderAttachments(data && data.context_files, data);
            var added = data && data.attachment;
            var added_name = (added && added.filename) || file.name;
            if (added && added.truncated) {
                // Say it out loud. Silently analysing the first third of
                // a document is a worse failure than refusing it.
                setCtxStatus(
                    "Attached " + added_name + " — it's long, so only the "
                    + "first part will be sent to Claude.",
                );
            } else {
                setCtxStatus("Attached " + added_name);
            }
        } catch (err) {
            setCtxStatus(err.message || "Couldn't attach that file.", true);
        } finally {
            ctxBusy = false;
            // Reset the input so picking the SAME file again still fires
            // a change event (the browser suppresses it otherwise).
            if (ctxInput) ctxInput.value = "";
        }
    }

    async function removeAttachment(id, name) {
        if (!id || ctxBusy) return;
        ctxBusy = true;
        setCtxStatus("Removing…");
        try {
            var data = await window.apiFetch(
                "/api/reflection/attachment/" + encodeURIComponent(id),
                { method: "DELETE" },
            );
            renderAttachments(data && data.context_files, data);
            setCtxStatus(name ? "Removed " + name : "Removed");
        } catch (err) {
            setCtxStatus(err.message || "Couldn't remove that file.", true);
        } finally {
            ctxBusy = false;
        }
    }

    if (ctxInput) {
        ctxInput.addEventListener("change", function () {
            var file = ctxInput.files && ctxInput.files[0];
            if (file) uploadAttachment(file);
        });
    }

    // ---- milestone: the runway this reflection counts down to (#325) ----
    // Before this, every reflection was analysed cold — no deadline, no
    // memory of last week. The header makes the runway visible; the
    // server hands the same facts to Claude.

    var mileWrap = document.getElementById("reflMilestone");
    var mileTitle = document.getElementById("reflMilestoneTitle");
    var mileSub = document.getElementById("reflMilestoneSub");
    var mileWarn = document.getElementById("reflMilestoneWarn");
    var mileEditBtn = document.getElementById("reflMilestoneEdit");
    var mileForm = document.getElementById("reflMilestoneForm");
    var mileGoal = document.getElementById("reflMilestoneGoal");
    var mileLabel = document.getElementById("reflMilestoneLabel");
    var mileDate = document.getElementById("reflMilestoneDate");
    var mileResult = document.getElementById("reflMilestoneResult");
    var lastWeekWrap = document.getElementById("reflLastWeek");
    var lastWeekText = document.getElementById("reflLastWeekText");
    var _milestone = null;

    function renderMilestone(m) {
        _milestone = m;
        var head = RH_.milestoneHeadline(m);
        if (!head) {
            // Nothing configured — offer the entry point rather than
            // rendering an empty bar the user can't act on.
            mileTitle.textContent = "No milestone set";
            mileSub.textContent = "Add one to count down and let Claude plan against it";
            mileEditBtn.textContent = "Set a milestone";
            mileWarn.style.display = "none";
            mileWrap.classList.add("reflection-milestone-empty");
            return;
        }
        mileWrap.classList.remove("reflection-milestone-empty");
        mileTitle.textContent = head.title;
        mileSub.textContent = head.sub;
        mileEditBtn.textContent = "Edit";
        if (head.warning) {
            mileWarn.textContent = head.warning;
            mileWarn.style.display = "";
        } else {
            mileWarn.style.display = "none";
        }
    }

    async function openMilestoneForm() {
        mileResult.textContent = "";
        // Goal dropdown, refetched each open so a goal created since the
        // page loaded is selectable without a reload.
        var goals = [];
        try {
            var res = await window.apiFetch("/api/goals");
            goals = Array.isArray(res) ? res : (res && res.goals) || [];
        } catch (e) { /* fall back to the type-a-name path */ }
        mileGoal.replaceChildren();
        var none = document.createElement("option");
        none.value = "";
        none.textContent = "— Type a name instead —";
        mileGoal.appendChild(none);
        goals.forEach(function (g) {
            var o = document.createElement("option");
            o.value = g.id;
            o.textContent = g.title;
            mileGoal.appendChild(o);
        });
        mileGoal.value = (_milestone && _milestone.goal_id) || "";
        mileLabel.value = (_milestone && _milestone.source === "custom"
            && _milestone.label) || "";
        mileDate.value = (_milestone && _milestone.date) || "";
        mileLabel.disabled = !!mileGoal.value;
        mileForm.style.display = "";
        mileGoal.focus();
    }

    function closeMilestoneForm() { mileForm.style.display = "none"; }

    async function saveMilestone() {
        var body = { target_date: mileDate.value || "" };
        if (mileGoal.value) {
            body.goal_id = mileGoal.value;
        } else {
            body.label = mileLabel.value || "";
        }
        try {
            var m = await window.apiFetch("/api/reflection/milestone", {
                method: "PUT",
                body: JSON.stringify(body),
            });
            renderMilestone(m);
            closeMilestoneForm();
        } catch (e) {
            mileResult.textContent = "Couldn't save: " + (e.message || e);
            mileResult.classList.add("utility-result-err");
        }
    }

    async function clearMilestone() {
        if (!window.confirm("Clear the milestone?")) return;
        try {
            await window.apiFetch("/api/reflection/milestone", { method: "DELETE" });
        } catch (e) { /* fall through — re-render from the server below */ }
        await loadMilestone();
        closeMilestoneForm();
    }

    async function loadMilestone() {
        try {
            var m = await window.apiFetch("/api/reflection/milestone");
            renderMilestone(m);
        } catch (e) {
            // A milestone is a bonus, never a blocker — leave the header
            // as-is rather than throwing an error at someone who just
            // wants to write a reflection.
            mileWrap.style.display = "none";
        }
    }

    /** #325: "Last reflection — <opening words>", so you can see where
     *  you left off without opening History. */
    async function loadLastReflection() {
        try {
            var data = await window.apiFetch("/api/reflection");
            var rows = (data && data.reflections) || [];
            if (!rows.length) return;
            var r = rows[0];
            var text = (r.transcript || "").trim();
            if (!text) return;
            if (text.length > 160) text = text.slice(0, 160).trim() + "…";
            lastWeekText.textContent = text;
            lastWeekWrap.style.display = "";
        } catch (e) { /* non-essential */ }
    }

    if (mileEditBtn) {
        mileEditBtn.addEventListener("click", function () {
            if (mileForm.style.display === "none") openMilestoneForm();
            else closeMilestoneForm();
        });
        document.getElementById("reflMilestoneSave")
            .addEventListener("click", saveMilestone);
        document.getElementById("reflMilestoneCancel")
            .addEventListener("click", closeMilestoneForm);
        document.getElementById("reflMilestoneClear")
            .addEventListener("click", clearMilestone);
        // Picking a goal means the name comes from it — make that visible
        // rather than leaving a stale typed name in a disabled-looking box.
        mileGoal.addEventListener("change", function () {
            mileLabel.disabled = !!mileGoal.value;
            if (mileGoal.value) {
                var sel = mileGoal.options[mileGoal.selectedIndex];
                mileLabel.value = sel ? sel.textContent : "";
            }
        });
    }

    // ---- recovered audio (#327) --------------------------------------
    // If a tab died mid-recording, its chunks are still on disk. Offer
    // them back rather than transcribing silently (that costs money) or
    // binning them silently (that's the bug this fixes).

    async function offerRecoveredAudio() {
        if (!AB) return;
        try {
            // Retention sweep FIRST — an expired orphan is never offered,
            // it's deleted. "Temporary" has to mean something.
            await AB.purgeExpired();
            var segs = await AB.listSegments();
            if (!segs.length) return;
            var seg = segs[0];
            var what = AB.describeOrphan(seg, 32000);
            var banner = document.getElementById("reflRecoverBanner");
            var text = document.getElementById("reflRecoverText");
            if (!banner || !text) return;
            text.textContent = "Unsent recording found from an interrupted "
                + "session — " + what + ".";
            banner.style.display = "";

            document.getElementById("reflRecoverUse").onclick = async function () {
                var blob = await AB.assembleSegment(seg.segmentId);
                if (!blob) {
                    text.textContent = "That recording couldn't be read.";
                    return;
                }
                banner.style.display = "none";
                selectMode("voice");
                showVoiceSubState("transcribing");
                currentSegmentId = seg.segmentId;
                uploadSegment(blob, seg.mime || "audio/webm");
            };
            document.getElementById("reflRecoverDiscard").onclick = async function () {
                if (!window.confirm("Discard the unsent recording?")) return;
                await AB.dropSegment(seg.segmentId);
                banner.style.display = "none";
            };
        } catch (e) { /* insurance, never a dependency */ }
    }

    // ---- init ----
    selectMode("type");
    showState("input");
    loadHistory();
    restoreDraft();
    loadMilestone();
    loadLastReflection();
    offerRecoveredAudio();
})();
