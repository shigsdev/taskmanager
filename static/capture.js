/* capture.js — Quick capture bar + voice input */
"use strict";

(function () {
    const input = document.getElementById("captureInput");
    const typeSelect = document.getElementById("captureType");
    const voiceBtn = document.getElementById("captureVoice");
    const submitBtn = document.getElementById("captureSubmit");

    if (!input) return;

    // --- Submit capture (shared by Enter key and submit button) ---

    async function submitCapture() {
        const raw = input.value.trim();
        if (!raw) return;

        const parsed = parseCapture(raw);
        parsed.type = parsed.type || typeSelect.value;

        // If a URL was detected, try to auto-fetch its title
        if (parsed.url && !parsed._titleProvided) {
            try {
                const preview = await apiFetch("/api/tasks/url-preview", {
                    method: "POST",
                    body: JSON.stringify({ url: parsed.url }),
                });
                if (preview && preview.title) {
                    parsed.title = preview.title;
                }
            } catch (_) {
                // Title fetch failed — proceed with raw text or URL as title
            }
        }

        try {
            await apiFetch("/api/tasks", {
                method: "POST",
                body: JSON.stringify(parsed),
            });
            input.value = "";
            await loadTasks();
        } catch (err) {
            alert("Capture failed: " + err.message);
        }
    }

    // --- Quick capture on Enter ---

    input.addEventListener("keydown", async (e) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        submitCapture();
    });

    // --- Submit button (for mobile / after voice input) ---

    if (submitBtn) {
        submitBtn.addEventListener("click", () => submitCapture());
    }

    // --- Parse hashtags, @project, and URLs ---
    // parseCapture() lives in parse_capture.js (loaded before this file
    // via a <script> tag in base.html).  This keeps capture.js focused on
    // DOM wiring while the pure parsing logic is importable by Jest.

    // --- Voice input (Web Speech API) ---

    if ("webkitSpeechRecognition" in window || "SpeechRecognition" in window) {
        const SpeechRecognition =
            window.SpeechRecognition || window.webkitSpeechRecognition;
        const recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.lang = "en-US";
        recognition.maxAlternatives = 1;

        // iOS Safari (especially PWA standalone) is unreliable with
        // interimResults — it may never fire result events at all, or
        // fire them without ever marking isFinal.  Disable interim on
        // iOS so we get a single, reliable final result instead.
        const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
        recognition.interimResults = !isIOS;

        let listening = false;
        let pendingTranscript = "";
        let appliedFinal = false;
        let gotAnyResult = false;

        function setVoiceListening() {
            listening = true;
            pendingTranscript = "";
            appliedFinal = false;
            gotAnyResult = false;
            voiceBtn.textContent = "⏹";
            voiceBtn.classList.add("voice-listening");
            voiceBtn.title = "Listening… tap to stop";
        }

        function setVoiceIdle() {
            listening = false;
            voiceBtn.textContent = "🎤";
            voiceBtn.classList.remove("voice-listening");
            voiceBtn.title = "Voice input";
        }

        function applyTranscript(text) {
            if (!text) return;
            const prefix = input.value ? input.value + " " : "";
            input.value = prefix + text;
            // Force iOS to acknowledge the value change
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.focus();
        }

        voiceBtn.addEventListener("click", () => {
            if (listening) {
                recognition.stop();
                return;
            }
            try {
                recognition.start();
                setVoiceListening();
            } catch (err) {
                alert("Could not start voice input. Check microphone permissions.");
            }
        });

        recognition.addEventListener("result", (e) => {
            gotAnyResult = true;
            let finalText = "";
            let interimText = "";
            for (let i = 0; i < e.results.length; i++) {
                const transcript = e.results[i][0].transcript;
                if (e.results[i].isFinal) {
                    finalText += transcript;
                } else {
                    interimText += transcript;
                }
            }
            if (finalText) {
                applyTranscript(finalText);
                appliedFinal = true;
                pendingTranscript = "";
            } else {
                pendingTranscript = interimText;
            }
        });

        recognition.addEventListener("end", () => {
            // On iOS Safari, manual stop() may skip the final result
            // event.  Apply any pending interim transcript so speech
            // isn't lost.
            if (!appliedFinal && pendingTranscript) {
                applyTranscript(pendingTranscript);
                pendingTranscript = "";
            }
            setVoiceIdle();
        });

        recognition.addEventListener("error", (e) => {
            setVoiceIdle();
            if (e.error === "not-allowed") {
                alert("Microphone access denied. Allow microphone " +
                      "permissions in your browser settings.");
            } else if (e.error === "no-speech") {
                // Silently reset — user just didn't speak
            } else {
                alert("Voice input error: " + e.error);
            }
        });
    } else {
        // Hide voice button if Speech API not available
        voiceBtn.style.display = "none";
    }
})();
