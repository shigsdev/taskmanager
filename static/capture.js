/* capture.js — Quick capture bar + voice input */
"use strict";

(function () {
    const input = document.getElementById("captureInput");
    const typeSelect = document.getElementById("captureType");
    const voiceBtn = document.getElementById("captureVoice");

    if (!input) return;

    // --- Quick capture on Enter ---

    input.addEventListener("keydown", async (e) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
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
    });

    // --- Parse hashtags, @project, and URLs ---

    function parseCapture(text) {
        const result = { title: text, tier: "inbox" };

        // Detect a URL anywhere in the text
        const urlMatch = text.match(/https?:\/\/\S+/i);
        if (urlMatch) {
            result.url = urlMatch[0];
            // Remove the URL from title; remaining text becomes the title
            const remaining = text.replace(urlMatch[0], "").trim();
            result.title = remaining || urlMatch[0]; // fall back to URL if nothing else
            result._titleProvided = remaining.length > 0; // true if user typed a title too
        }

        // Tier shortcuts: #today #week #backlog
        const tierMap = {
            "#today": "today",
            "#week": "this_week",
            "#backlog": "backlog",
            "#freezer": "freezer",
        };
        for (const [tag, tier] of Object.entries(tierMap)) {
            if (result.title.toLowerCase().includes(tag)) {
                result.tier = tier;
                result.title = result.title.replace(new RegExp(tag, "gi"), "").trim();
            }
        }

        // Type shortcuts: #work #personal
        if (result.title.toLowerCase().includes("#work")) {
            result.type = "work";
            result.title = result.title.replace(/#work/gi, "").trim();
        } else if (result.title.toLowerCase().includes("#personal")) {
            result.type = "personal";
            result.title = result.title.replace(/#personal/gi, "").trim();
        }

        // If title is now empty (e.g. user pasted only a URL), will be filled by url-preview
        if (!result.title && result.url) {
            result.title = result.url;
        }

        return result;
    }

    // --- Voice input (Web Speech API) ---

    if ("webkitSpeechRecognition" in window || "SpeechRecognition" in window) {
        const SpeechRecognition =
            window.SpeechRecognition || window.webkitSpeechRecognition;
        const recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = true;
        recognition.lang = "en-US";

        let listening = false;
        let pendingTranscript = "";

        function setVoiceListening() {
            listening = true;
            pendingTranscript = "";
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
            input.value = (input.value ? input.value + " " : "") + text;
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
            let finalText = "";
            let interimText = "";
            for (let i = 0; i < e.results.length; i++) {
                if (e.results[i].isFinal) {
                    finalText += e.results[i][0].transcript;
                } else {
                    interimText += e.results[i][0].transcript;
                }
            }
            if (finalText) {
                applyTranscript(finalText);
                pendingTranscript = "";
            } else {
                pendingTranscript = interimText;
            }
        });

        recognition.addEventListener("end", () => {
            // On iOS Safari, manual stop() skips the final result event.
            // Apply any pending interim transcript so speech isn't lost.
            if (pendingTranscript) {
                applyTranscript(pendingTranscript);
                pendingTranscript = "";
            }
            setVoiceIdle();
        });

        recognition.addEventListener("error", (e) => {
            setVoiceIdle();
            if (e.error === "not-allowed") {
                alert("Microphone access denied. Please allow microphone permissions in your browser settings.");
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
