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

    // --- Parse hashtags and @project ---

    function parseCapture(text) {
        const result = { title: text, tier: "inbox" };

        // Tier shortcuts: #today #week #backlog
        const tierMap = {
            "#today": "today",
            "#week": "this_week",
            "#backlog": "backlog",
            "#freezer": "freezer",
        };
        for (const [tag, tier] of Object.entries(tierMap)) {
            if (text.toLowerCase().includes(tag)) {
                result.tier = tier;
                result.title = result.title.replace(new RegExp(tag, "gi"), "").trim();
            }
        }

        // Type shortcuts: #work #personal
        if (text.toLowerCase().includes("#work")) {
            result.type = "work";
            result.title = result.title.replace(/#work/gi, "").trim();
        } else if (text.toLowerCase().includes("#personal")) {
            result.type = "personal";
            result.title = result.title.replace(/#personal/gi, "").trim();
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
