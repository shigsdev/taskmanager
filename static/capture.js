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
        recognition.interimResults = false;
        recognition.lang = "en-US";

        let listening = false;

        voiceBtn.addEventListener("click", () => {
            if (listening) {
                recognition.stop();
                return;
            }
            recognition.start();
            listening = true;
            voiceBtn.style.background = "#fee2e2";
            voiceBtn.title = "Listening… tap to stop";
        });

        recognition.addEventListener("result", (e) => {
            const transcript = e.results[0][0].transcript;
            input.value = (input.value ? input.value + " " : "") + transcript;
            input.focus();
        });

        recognition.addEventListener("end", () => {
            listening = false;
            voiceBtn.style.background = "";
            voiceBtn.title = "Voice input";
        });

        recognition.addEventListener("error", () => {
            listening = false;
            voiceBtn.style.background = "";
        });
    } else {
        // Hide voice button if Speech API not available
        voiceBtn.style.display = "none";
    }
})();
