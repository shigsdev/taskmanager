/**
 * voice_input.js — reusable voice-to-text helper for any text input or
 * textarea. Used by capture.js (the quick-add bar) and detail panels
 * (task / project / goal — #116 PR54).
 *
 * Browser API: Web Speech API (SpeechRecognition / webkitSpeechRecognition).
 * Works on Chrome desktop, Chrome Android, Safari iOS 15+. Silently
 * degrades to "voice button hidden" when unavailable.
 *
 * Pattern matches parse_capture.js / filter_helpers.js / api_helpers.js:
 * dual-export so Node/Jest can test the pure logic + browser uses
 * the global window.voiceInput.
 *
 * Pure helpers (testable):
 *   - voiceSupported() → bool
 *   - appendTranscript(currentValue, transcript) → newValue
 * DOM-touching helpers (browser-only side-effects):
 *   - attachVoiceButton(button, targetField)
 */
"use strict";

function voiceSupported() {
    if (typeof window === "undefined") return false;
    return "webkitSpeechRecognition" in window || "SpeechRecognition" in window;
}

/**
 * Compute the new field value when a transcript chunk arrives.
 * - Empty current value → just the transcript.
 * - Non-empty current value → space-separated append.
 * - Empty transcript → unchanged.
 * Pure: returns the new string, doesn't mutate.
 */
function appendTranscript(currentValue, transcript) {
    const t = (transcript || "").trim();
    if (!t) return currentValue || "";
    if (!currentValue) return t;
    // Don't double-space if current already ends with whitespace.
    return currentValue.replace(/\s+$/, "") + " " + t;
}

/**
 * Wire a button to a target text field. Clicking the button starts
 * Web Speech recognition; the result is appended to the field.
 *
 * Browser-only — no-op on Node. Defensive: if Speech API is missing,
 * hides the button instead of throwing.
 *
 * Returns a cleanup function or null if unsupported.
 */
function attachVoiceButton(button, targetField) {
    if (typeof window === "undefined") return null;
    if (!button || !targetField) return null;
    if (!voiceSupported()) {
        button.style.display = "none";
        return null;
    }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SR();
    recognition.continuous = false;
    recognition.lang = "en-US";
    recognition.maxAlternatives = 1;
    // iOS Safari interim-results are unreliable in PWA standalone.
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
    recognition.interimResults = !isIOS;

    let listening = false;
    let pendingTranscript = "";
    let appliedFinal = false;

    function setListening() {
        listening = true;
        pendingTranscript = "";
        appliedFinal = false;
        button.textContent = "⏹";
        button.classList.add("voice-listening");
        button.title = "Listening… tap to stop";
    }
    function setIdle() {
        listening = false;
        button.textContent = "🎤";
        button.classList.remove("voice-listening");
        button.title = "Voice input";
    }
    function apply(text) {
        if (!text) return;
        targetField.value = appendTranscript(targetField.value, text);
        targetField.dispatchEvent(new Event("input", { bubbles: true }));
        targetField.focus();
    }

    function onClick() {
        if (listening) { recognition.stop(); return; }
        try {
            recognition.start();
            setListening();
        } catch (_) {
            alert("Could not start voice input. Check microphone permissions.");
        }
    }

    function onResult(e) {
        let finalText = "";
        let interimText = "";
        for (let i = 0; i < e.results.length; i++) {
            const transcript = e.results[i][0].transcript;
            if (e.results[i].isFinal) finalText += transcript;
            else interimText += transcript;
        }
        if (finalText) {
            apply(finalText);
            appliedFinal = true;
            pendingTranscript = "";
        } else {
            pendingTranscript = interimText;
        }
    }

    function onEnd() {
        if (!appliedFinal && pendingTranscript) {
            apply(pendingTranscript);
            pendingTranscript = "";
        }
        setIdle();
    }

    function onError(e) {
        setIdle();
        if (e.error === "not-allowed") {
            alert("Microphone access denied. Allow microphone permissions in your browser settings.");
        } else if (e.error === "no-speech") {
            // silent
        } else {
            alert("Voice input error: " + e.error);
        }
    }

    button.addEventListener("click", onClick);
    recognition.addEventListener("result", onResult);
    recognition.addEventListener("end", onEnd);
    recognition.addEventListener("error", onError);

    return function cleanup() {
        button.removeEventListener("click", onClick);
        recognition.removeEventListener("result", onResult);
        recognition.removeEventListener("end", onEnd);
        recognition.removeEventListener("error", onError);
        if (listening) recognition.stop();
    };
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = { voiceSupported, appendTranscript, attachVoiceButton };
} else if (typeof window !== "undefined") {
    window.voiceInput = { voiceSupported, appendTranscript, attachVoiceButton };
}
