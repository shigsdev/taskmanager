# ADR-005: Voice memo error handling — defensively detach event handlers

Date: 2026-04-18
Status: ACCEPTED

## Context

The voice memo capture flow uses the browser MediaRecorder API.
On some platforms (especially Android WebView and Chrome under
specific failure modes), MediaRecorder fires both `error` AND `stop`
events when an error occurs — first `error`, then `stop` shortly
after.

The naive handler implementation has both:

```js
mediaRecorder.onerror = (e) => showError(e.error.message);
mediaRecorder.onstop = () => uploadAndProcess(chunks, mimeType);
```

In the dual-event case, the user sees:
1. Error UI appears (from `onerror`)
2. Processing spinner overwrites the error (from `onstop`)
3. Upload of partial audio fails on the server
4. Generic 422 error appears, no link to the original problem

The user is stuck in a loop with no clear recovery path.

## Decision

In `mediaRecorder.onerror`, explicitly null out `mediaRecorder.onstop`
before doing any cleanup. This guarantees that even if the platform
fires `stop` after `error`, no upload kicks off.

```js
mediaRecorder.onerror = function (e) {
    mediaRecorder.onstop = null;  // <-- THIS
    if (recordCapTimeoutId) {
        clearTimeout(recordCapTimeoutId);
        recordCapTimeoutId = null;
    }
    stopTimer();
    stopMediaStream();
    showError("Recording error: " + (e.error?.message || "unknown"));
};
```

Same defensive pattern was already in `cancelRecording()` for the
same reason (user-cancel shouldn't trigger upload).

## Consequences

**Easy:**
- Error state is stable on all platforms; no spurious "processing"
  state after an error
- Mirror of the existing pattern in cancelRecording — easy to read

**Hard:**
- Easy to forget when adding new error paths in the future. Tests
  for this are hard to write (require simulating MediaRecorder error
  events in headless browser, which doesn't always work). Mitigated
  by the comment block in voice_memo.js calling out this ADR.

## Alternatives considered

- **Set a "did_error" flag, check in `onstop`**: equivalent behavior,
  more state to track
- **Wrap in a state machine library**: overkill for one event flow
- **Ignore the issue (it only happens on some Android variants)**: the
  user explicitly tests on iPhone and iOS Safari has its own
  MediaRecorder bugs; better to handle the class of bug consistently
