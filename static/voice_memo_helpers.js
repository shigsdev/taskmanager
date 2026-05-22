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

if (typeof module !== "undefined" && module.exports) {
    module.exports = { mimeTypeToExt };
} else if (typeof window !== "undefined") {
    window.voiceMemoHelpers = { mimeTypeToExt };
}
