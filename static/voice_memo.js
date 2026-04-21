/**
 * Voice memo to tasks — record, upload, review, confirm flow.
 *
 * State machine:
 *   idle → recording → processing → review → done
 *                                         ↘ error (recoverable to idle)
 *
 * MediaRecorder API outputs webm/opus on Chrome/Android, mp4 on Safari.
 * Both are accepted by the server-side Whisper call; we don't normalize
 * client-side because that would require shipping ffmpeg.wasm or similar.
 *
 * Recording is hard-capped at 10 minutes — we auto-stop and submit when
 * MAX_RECORDING_MS elapses, matching the server's per-memo policy.
 */

(function () {
    "use strict";

    // --- Config --------------------------------------------------------------

    const UPLOAD_API = "/api/voice-memo";
    const CONFIRM_API = "/api/voice-memo/confirm";

    const MAX_RECORDING_MS = 10 * 60 * 1000;       // 10 min hard cap

    // --- DOM refs ------------------------------------------------------------

    const states = {
        idle: document.getElementById("voiceStateIdle"),
        recording: document.getElementById("voiceStateRecording"),
        processing: document.getElementById("voiceStateProcessing"),
        review: document.getElementById("voiceStateReview"),
        done: document.getElementById("voiceStateDone"),
        error: document.getElementById("voiceStateError"),
    };

    const recordBtn = document.getElementById("voiceRecordBtn");
    const stopBtn = document.getElementById("voiceStopBtn");
    const cancelBtn = document.getElementById("voiceCancelBtn");
    const timerEl = document.getElementById("voiceTimer");

    const stepUpload = document.getElementById("voiceStepUpload");
    const stepTranscribe = document.getElementById("voiceStepTranscribe");
    const stepParse = document.getElementById("voiceStepParse");

    const candidatesEl = document.getElementById("voiceCandidates");
    const costHintEl = document.getElementById("voiceCostHint");
    const transcriptEl = document.getElementById("voiceTranscript");
    const confirmAllBtn = document.getElementById("voiceConfirmAll");
    const confirmSelectedBtn = document.getElementById("voiceConfirmSelected");
    const recordAgainBtn = document.getElementById("voiceRecordAgain");

    const doneMessage = document.getElementById("voiceDoneMessage");
    const recordAnotherBtn = document.getElementById("voiceRecordAnother");

    const errorMessage = document.getElementById("voiceErrorMessage");
    const errorTranscriptWrap = document.getElementById("voiceErrorTranscriptWrap");
    const errorTranscript = document.getElementById("voiceErrorTranscript");
    const retryBtn = document.getElementById("voiceRetry");

    // --- State ---------------------------------------------------------------

    let mediaRecorder = null;
    let mediaStream = null;
    let chunks = [];
    let recordStartMs = 0;
    let recordTimerId = null;
    let recordCapTimeoutId = null;
    let currentCandidates = [];
    // Backlog #37: projects + goals loaded once per page so the voice
    // review dropdowns can show the user's actual options instead of
    // just the hint text. Fetched during init; empty list is fine if
    // the API call fails — dropdowns just show "(no project)".
    let availableProjects = [];
    let availableGoals = [];

    async function loadProjectsAndGoalsForReview() {
        try {
            const [projects, goals] = await Promise.all([
                fetch("/api/projects").then((r) => r.json()),
                fetch("/api/goals").then((r) => r.json()),
            ]);
            availableProjects = Array.isArray(projects) ? projects : [];
            availableGoals = Array.isArray(goals) ? goals : [];
        } catch (err) {
            // Non-fatal — the review screen still works without
            // project/goal dropdowns.
            console.warn("Could not load projects/goals:", err);
        }
    }

    // Kick off the fetch immediately so projects/goals are ready by
    // the time the user finishes their voice memo.
    loadProjectsAndGoalsForReview();

    // --- State management ---------------------------------------------------

    function showState(name) {
        Object.keys(states).forEach((k) => {
            if (states[k]) states[k].style.display = (k === name) ? "" : "none";
        });
    }

    function showError(message, transcript) {
        errorMessage.textContent = message || "Unknown error.";
        if (transcript) {
            errorTranscript.textContent = transcript;
            errorTranscriptWrap.style.display = "";
        } else {
            errorTranscriptWrap.style.display = "none";
        }
        showState("error");
    }

    // --- Recording -----------------------------------------------------------

    async function startRecording() {
        // Re-check at click time — feature might be disabled in prod for
        // some browsers (iOS PWA standalone has a known MediaRecorder
        // bug across versions).
        if (!navigator.mediaDevices || !window.MediaRecorder) {
            showError(
                "This browser doesn't support audio recording. Try Chrome on Android, " +
                "Safari on iOS in a browser tab (not PWA standalone), or desktop Chrome/Firefox.",
            );
            return;
        }

        try {
            mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (err) {
            // Permission denied is the most common failure here.
            const msg = (err && err.name === "NotAllowedError")
                ? "Microphone access was blocked. Allow microphone in your browser settings and try again."
                : "Couldn't access the microphone: " + (err && err.message ? err.message : err);
            showError(msg);
            return;
        }

        chunks = [];
        try {
            mediaRecorder = new MediaRecorder(mediaStream);
        } catch (err) {
            stopMediaStream();
            showError("MediaRecorder failed to initialize: " + err.message);
            return;
        }

        mediaRecorder.ondataavailable = function (e) {
            if (e.data && e.data.size > 0) chunks.push(e.data);
        };

        mediaRecorder.onstop = function () {
            stopMediaStream();
            // Hand off to the upload pipeline. mediaRecorder.mimeType is
            // the actual codec/container the browser captured (more
            // accurate than the user-agent default).
            uploadAndProcess(chunks, mediaRecorder.mimeType || "audio/webm");
        };

        mediaRecorder.onerror = function (e) {
            // CRITICAL: detach onstop before it fires. On Android WebView
            // (and some Chrome versions) MediaRecorder fires `stop` after
            // an error. Without this guard, onstop kicks off the upload
            // pipeline, overwriting our error UI with the processing
            // spinner — and then failing again on the partial audio.
            // See docs/adr/005-voice-memo-error-handling.md.
            mediaRecorder.onstop = null;
            if (recordCapTimeoutId) {
                clearTimeout(recordCapTimeoutId);
                recordCapTimeoutId = null;
            }
            stopTimer();
            stopMediaStream();
            showError("Recording error: " + (e.error && e.error.message || "unknown"));
        };

        recordStartMs = Date.now();
        startTimer();
        recordCapTimeoutId = setTimeout(stopRecording, MAX_RECORDING_MS);
        mediaRecorder.start();
        showState("recording");
    }

    // iOS Safari (and most mobile browsers) freeze setTimeout when the
    // tab is backgrounded, so the 10-min auto-stop above never fires if
    // the user locks their phone or switches apps mid-recording. When
    // the tab returns to foreground, check if we're past the cap and
    // stop immediately so the user doesn't end up with a 30-minute
    // recording that then bounces off the 25 MB Whisper upload limit.
    document.addEventListener("visibilitychange", function () {
        if (document.visibilityState !== "visible") return;
        if (!mediaRecorder || mediaRecorder.state !== "recording") return;
        if (Date.now() - recordStartMs >= MAX_RECORDING_MS) {
            stopRecording();
        }
    });

    function stopRecording() {
        if (recordCapTimeoutId) {
            clearTimeout(recordCapTimeoutId);
            recordCapTimeoutId = null;
        }
        stopTimer();
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            mediaRecorder.stop();
        }
    }

    function cancelRecording() {
        if (recordCapTimeoutId) {
            clearTimeout(recordCapTimeoutId);
            recordCapTimeoutId = null;
        }
        stopTimer();
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            // Detach handlers so onstop doesn't trigger the upload path.
            mediaRecorder.onstop = null;
            mediaRecorder.stop();
        }
        stopMediaStream();
        chunks = [];
        showState("idle");
    }

    function stopMediaStream() {
        if (mediaStream) {
            mediaStream.getTracks().forEach((t) => t.stop());
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
        const elapsed = Date.now() - recordStartMs;
        const totalSec = Math.floor(elapsed / 1000);
        const min = Math.floor(totalSec / 60);
        const sec = totalSec % 60;
        timerEl.textContent = min + ":" + (sec < 10 ? "0" : "") + sec;
    }

    // --- Upload pipeline -----------------------------------------------------

    async function uploadAndProcess(audioChunks, mimeType) {
        showState("processing");
        markStep(stepUpload, "running");
        markStep(stepTranscribe, "pending");
        markStep(stepParse, "pending");

        const blob = new Blob(audioChunks, { type: mimeType });
        if (blob.size === 0) {
            showError("No audio captured (recording was empty).");
            return;
        }

        const formData = new FormData();
        // Filename matters less than content_type but we set both so the
        // server can log meaningful info.
        const ext = mimeTypeToExt(mimeType);
        formData.append("audio", blob, "memo." + ext);

        let resp, data;
        try {
            markStep(stepUpload, "running");
            resp = await fetch(UPLOAD_API, {
                method: "POST",
                body: formData,
                credentials: "same-origin",
            });
        } catch (err) {
            showError("Upload failed (network error): " + err.message);
            return;
        }
        markStep(stepUpload, "done");
        markStep(stepTranscribe, "running");

        try {
            data = await resp.json();
        } catch (err) {
            showError("Server returned non-JSON response (HTTP " + resp.status + ").");
            return;
        }

        if (!resp.ok) {
            // Server may have transcribed but failed to parse — surface
            // the transcript if present so user can recover manually.
            showError(
                (data && data.error) || ("Upload failed (HTTP " + resp.status + ")"),
                data && data.transcript,
            );
            return;
        }

        markStep(stepTranscribe, "done");
        markStep(stepParse, "done");

        currentCandidates = data.candidates || [];
        renderReview(data);
    }

    function markStep(el, state) {
        if (!el) return;
        const prefix = state === "done" ? "✓ "
                     : state === "running" ? "⏳ "
                     : "○ ";
        // Strip any existing prefix and replace.
        const text = el.textContent.replace(/^[^\s]+\s/, "");
        el.textContent = prefix + text;
    }

    function mimeTypeToExt(mimeType) {
        const mt = (mimeType || "").toLowerCase().split(";")[0];
        if (mt.indexOf("mp4") !== -1) return "mp4";
        if (mt.indexOf("mpeg") !== -1) return "mp3";
        if (mt.indexOf("ogg") !== -1) return "ogg";
        if (mt.indexOf("wav") !== -1) return "wav";
        return "webm";
    }

    // --- Review -------------------------------------------------------------

    function renderReview(data) {
        candidatesEl.innerHTML = "";

        // #37: split candidates into actionable tasks vs reflections
        // (is_task === false). Tasks render inline as before;
        // reflections go into a collapsed section below — unchecked
        // by default so they don't accidentally become tasks, and
        // the user can toggle them back to "is_task" by promoting.
        const tasks = [];
        const reflections = [];
        currentCandidates.forEach((c, idx) => {
            if (c.is_task === false) {
                // Start reflections unchecked so they're dropped by
                // default; user explicitly checks to promote.
                if (c.included === undefined) c.included = false;
                reflections.push(idx);
            } else {
                tasks.push(idx);
            }
        });

        tasks.forEach((idx) => {
            candidatesEl.appendChild(renderCandidate(
                currentCandidates[idx], idx,
            ));
        });

        if (reflections.length > 0) {
            const details = document.createElement("details");
            details.className = "voice-reflections";
            const summary = document.createElement("summary");
            summary.textContent = "Reflections / non-tasks (" +
                reflections.length + ") — usually kept OUT of your task list";
            details.appendChild(summary);
            const hint = document.createElement("p");
            hint.className = "voice-reflections-hint";
            hint.textContent = "These were flagged as observations, not " +
                "actions. Check any you actually want as tasks, then use " +
                "'Add Selected'. Leave unchecked to drop them.";
            details.appendChild(hint);
            reflections.forEach((idx) => {
                details.appendChild(renderCandidate(
                    currentCandidates[idx], idx,
                ));
            });
            candidatesEl.appendChild(details);
        }

        const cents = (data.cost_usd || 0) * 100;
        const dur = data.duration_seconds || 0;
        costHintEl.textContent =
            "Transcribed " + dur.toFixed(1) + "s of audio for $" +
            (data.cost_usd || 0).toFixed(4) +
            " (~" + cents.toFixed(2) + " cents).";

        transcriptEl.textContent = data.transcript || "(no transcript)";

        if (currentCandidates.length === 0) {
            candidatesEl.innerHTML =
                '<p class="voice-empty">No tasks extracted from the transcript. ' +
                'Open the transcript below to copy text manually.</p>';
            confirmAllBtn.disabled = true;
            confirmSelectedBtn.disabled = true;
        } else {
            confirmAllBtn.disabled = false;
            confirmSelectedBtn.disabled = false;
        }

        showState("review");
    }

    function renderCandidate(candidate, idx) {
        const row = document.createElement("div");
        row.className = "voice-candidate";

        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = candidate.included !== false;
        cb.dataset.idx = String(idx);
        cb.addEventListener("change", function () {
            currentCandidates[idx].included = cb.checked;
        });
        row.appendChild(cb);

        const titleInput = document.createElement("input");
        titleInput.type = "text";
        titleInput.value = candidate.title || "";
        titleInput.className = "voice-candidate-title";
        titleInput.addEventListener("input", function () {
            currentCandidates[idx].title = titleInput.value;
        });
        row.appendChild(titleInput);

        const typeSel = document.createElement("select");
        typeSel.className = "voice-candidate-type";
        ["work", "personal"].forEach((v) => {
            const opt = document.createElement("option");
            opt.value = v;
            opt.textContent = v;
            if (candidate.type === v) opt.selected = true;
            typeSel.appendChild(opt);
        });
        typeSel.addEventListener("change", function () {
            currentCandidates[idx].type = typeSel.value;
        });
        row.appendChild(typeSel);

        // #36: tier dropdown. Options mirror _VOICE_VALID_TIERS on the
        // backend (inbox / today / tomorrow / this_week). Anything else
        // would have been coerced to "inbox" server-side.
        const tierSel = document.createElement("select");
        tierSel.className = "voice-candidate-tier";
        [
            ["inbox", "Inbox"],
            ["today", "Today"],
            ["tomorrow", "Tomorrow"],
            ["this_week", "This Week"],
        ].forEach(([v, label]) => {
            const opt = document.createElement("option");
            opt.value = v;
            opt.textContent = label;
            if (candidate.tier === v) opt.selected = true;
            tierSel.appendChild(opt);
        });
        tierSel.addEventListener("change", function () {
            currentCandidates[idx].tier = tierSel.value;
        });
        row.appendChild(tierSel);

        // #36: due-date input. Empty string means "no date set."
        // Native <input type="date"> on mobile gives the iOS wheel
        // picker for free.
        const dateInput = document.createElement("input");
        dateInput.type = "date";
        dateInput.className = "voice-candidate-date";
        dateInput.value = candidate.due_date || "";
        dateInput.addEventListener("input", function () {
            currentCandidates[idx].due_date = dateInput.value || null;
        });
        row.appendChild(dateInput);

        // #37: project dropdown. Options = "(no project)" + every
        // active project. Pre-selected to the inferred project_id
        // (resolved server-side from project_hint).
        const projSel = document.createElement("select");
        projSel.className = "voice-candidate-project";
        projSel.title = "Link to project";
        const noneOpt = document.createElement("option");
        noneOpt.value = "";
        noneOpt.textContent = "(no project)";
        projSel.appendChild(noneOpt);
        availableProjects.forEach((p) => {
            const opt = document.createElement("option");
            opt.value = p.id;
            opt.textContent = p.name;
            if (candidate.project_id === p.id) opt.selected = true;
            projSel.appendChild(opt);
        });
        projSel.addEventListener("change", function () {
            currentCandidates[idx].project_id = projSel.value || null;
        });
        row.appendChild(projSel);

        // #37: goal dropdown. Same pattern.
        const goalSel = document.createElement("select");
        goalSel.className = "voice-candidate-goal";
        goalSel.title = "Link to goal";
        const noGoalOpt = document.createElement("option");
        noGoalOpt.value = "";
        noGoalOpt.textContent = "(no goal)";
        goalSel.appendChild(noGoalOpt);
        availableGoals.forEach((g) => {
            const opt = document.createElement("option");
            opt.value = g.id;
            opt.textContent = g.title;
            if (candidate.goal_id === g.id) opt.selected = true;
            goalSel.appendChild(opt);
        });
        goalSel.addEventListener("change", function () {
            currentCandidates[idx].goal_id = goalSel.value || null;
        });
        row.appendChild(goalSel);

        // #37: unresolved-hint indicator. If Claude cited a project
        // or goal that doesn't match any of the user's actual
        // records, show the hint text as a small muted note so the
        // user can either (a) create that project/goal manually, or
        // (b) ignore and pick one from the dropdown.
        if (candidate.project_hint && !candidate.project_id) {
            const hint = document.createElement("div");
            hint.className = "voice-candidate-hint";
            hint.textContent = 'Heard project: "' + candidate.project_hint + '" (no match)';
            row.appendChild(hint);
        }
        if (candidate.goal_hint && !candidate.goal_id) {
            const hint = document.createElement("div");
            hint.className = "voice-candidate-hint";
            hint.textContent = 'Heard goal: "' + candidate.goal_hint + '" (no match)';
            row.appendChild(hint);
        }

        return row;
    }

    async function confirmCandidates(onlySelected) {
        const toSubmit = currentCandidates
            .filter((c) => onlySelected ? c.included !== false : true)
            // Sync UI-edited fields before sending. Include the #36
            // NLP-inferred tier + due_date AND the #37 project/goal
            // IDs so the server honours them via
            // create_tasks_from_candidates.
            .map((c) => ({
                title: (c.title || "").trim(),
                type: c.type || "personal",
                tier: c.tier || "inbox",
                due_date: c.due_date || null,
                project_id: c.project_id || null,
                goal_id: c.goal_id || null,
                included: true,
            }))
            .filter((c) => c.title);

        if (toSubmit.length === 0) {
            doneMessage.textContent = "Nothing to add.";
            showState("done");
            return;
        }

        let resp, data;
        try {
            resp = await fetch(CONFIRM_API, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ candidates: toSubmit }),
                credentials: "same-origin",
            });
        } catch (err) {
            showError("Confirm failed (network error): " + err.message);
            return;
        }

        try {
            data = await resp.json();
        } catch (err) {
            showError("Server returned non-JSON on confirm (HTTP " + resp.status + ").");
            return;
        }

        if (!resp.ok) {
            showError((data && data.error) || ("Confirm failed (HTTP " + resp.status + ")"));
            return;
        }

        const created = (data && data.created) || 0;
        doneMessage.textContent =
            created === 1 ? "1 task added to Inbox."
                          : created + " tasks added to Inbox.";
        showState("done");
    }

    // --- Wire-up -------------------------------------------------------------

    if (recordBtn) recordBtn.addEventListener("click", startRecording);
    if (stopBtn) stopBtn.addEventListener("click", stopRecording);
    if (cancelBtn) cancelBtn.addEventListener("click", cancelRecording);
    if (confirmAllBtn) confirmAllBtn.addEventListener("click", () => confirmCandidates(false));
    if (confirmSelectedBtn) confirmSelectedBtn.addEventListener("click", () => confirmCandidates(true));
    if (recordAgainBtn) recordAgainBtn.addEventListener("click", () => showState("idle"));
    if (recordAnotherBtn) recordAnotherBtn.addEventListener("click", () => showState("idle"));
    if (retryBtn) retryBtn.addEventListener("click", () => showState("idle"));

    // Initial state — tell the user up front if recording isn't possible
    // here, instead of letting them tap and then fail.
    if (!navigator.mediaDevices || !window.MediaRecorder) {
        showError(
            "This browser doesn't support audio recording. Try Chrome on Android, " +
            "Safari on iOS in a browser tab (not PWA standalone), or desktop Chrome/Firefox.",
        );
    } else {
        showState("idle");
    }
})();
