"""Voice memo to tasks — audio transcription pipeline.

Pipeline:
1. Audio bytes (from MediaRecorder in browser) → OpenAI Whisper API → transcript
2. Transcript text → Claude (via existing scan_service.parse_tasks_from_text)
   → JSON array of task candidates
3. User reviews candidates → confirmed tasks created in Inbox
   (via existing scan_service.create_tasks_from_candidates with
   source_prefix="voice")

Security (per CLAUDE.md):
- Audio processed in memory only — never written to disk or DB
- Whisper API call is server-side only — browser never talks to OpenAI
- Audio bytes are garbage-collected after the API call
- Per-call cost is logged to AppLog so usage is auditable

Why no SDK dependency:
The codebase pattern is to call third-party APIs via raw ``requests``
rather than vendor SDKs (see scan_service for Google Vision and
Anthropic). Same pattern here for OpenAI — keeps the dependency
surface narrow and means we don't pull in the openai SDK just for one
endpoint.
"""
from __future__ import annotations

import io
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# OpenAI Whisper pricing as of 2026-04: $0.006 per minute. Keep this in
# code (not in a database table) because it changes only when OpenAI
# updates pricing — at which point we want a code review and a deploy.
WHISPER_USD_PER_MINUTE = 0.006

# Whisper API hard limit on uploaded file size: 25 MB. We surface this
# to the route layer so the UI can reject before uploading.
WHISPER_MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# Audio MIME types we'll accept from the browser. MediaRecorder produces
# webm/opus on Chrome/Android and mp4 on Safari. We accept both plus a
# few common fallbacks; Whisper handles all of these natively.
ALLOWED_AUDIO_TYPES = frozenset({
    "audio/webm",
    "audio/webm;codecs=opus",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/ogg;codecs=opus",
    "audio/wav",
    "audio/x-wav",
})


def transcribe_audio(audio_bytes: bytes, mime_type: str) -> dict[str, Any]:
    """Send audio to Whisper and return ``{transcript, duration_seconds, cost_usd}``.

    Args:
        audio_bytes: Raw audio file bytes.
        mime_type: The MIME type the browser said the audio was. Used
            only to pick a sensible filename extension for the multipart
            upload (Whisper looks at the file extension, not the
            client-declared MIME type).

    Returns:
        A dict with:
        - ``transcript`` (str): the transcribed text
        - ``duration_seconds`` (float): audio length per Whisper's response
        - ``cost_usd`` (float): computed from duration * WHISPER_USD_PER_MINUTE / 60

    Raises:
        RuntimeError: If the API key is missing or the API call fails.
            Message is safe to surface to the user (no key leakage).
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    return _call_whisper_api(api_key, audio_bytes, mime_type)


def _filename_for_mime(mime_type: str) -> str:
    """Whisper inspects the filename extension to detect the audio
    format. Browser-supplied MIME types don't always match (some
    browsers report ``audio/webm`` for opus-in-webm), so we map to the
    extension Whisper expects."""
    mt = (mime_type or "").lower().split(";")[0].strip()
    return {
        "audio/webm": "memo.webm",
        "audio/mp4": "memo.mp4",
        "audio/mpeg": "memo.mp3",
        "audio/ogg": "memo.ogg",
        "audio/wav": "memo.wav",
        "audio/x-wav": "memo.wav",
    }.get(mt, "memo.webm")


def _call_whisper_api(
    api_key: str,
    audio_bytes: bytes,
    mime_type: str,
) -> dict[str, Any]:
    """Make the actual OpenAI Whisper API call. Separated for testability.

    Wraps all failure modes (network, HTTP error, bad JSON, per-request
    API error) in RuntimeError with a useful message that's safe to
    surface to the user — the API key is never included.
    """
    import requests

    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}
    # response_format=verbose_json gives us the duration field we need
    # for cost calculation. Alternative would be to compute duration
    # client-side via Web Audio API, but server-authoritative is safer.
    files = {
        "file": (_filename_for_mime(mime_type), io.BytesIO(audio_bytes), mime_type),
    }
    data = {
        "model": "whisper-1",
        "response_format": "verbose_json",
    }

    try:
        resp = requests.post(
            url,
            headers=headers,
            files=files,
            data=data,
            timeout=120,
        )
    except requests.RequestException as e:
        raise RuntimeError(
            f"Whisper API network error: {type(e).__name__}"
        ) from e

    if not resp.ok:
        detail = ""
        try:
            body = resp.json()
            detail = body.get("error", {}).get("message") or ""
        except ValueError:
            detail = resp.text[:200]
        raise RuntimeError(
            f"Whisper API returned HTTP {resp.status_code}"
            + (f": {detail}" if detail else "")
        )

    try:
        data = resp.json()
    except ValueError as e:
        raise RuntimeError("Whisper API returned invalid JSON") from e

    transcript = (data.get("text") or "").strip()
    # Whisper rounds duration to a few decimals; treat missing as 0
    # (we'll log it but not block — the transcript is still useful).
    duration_seconds = float(data.get("duration") or 0.0)
    cost_usd = (duration_seconds / 60.0) * WHISPER_USD_PER_MINUTE

    logger.info(
        "voice_memo: whisper transcribed %.1fs of audio for $%.4f (%d transcript chars)",
        duration_seconds,
        cost_usd,
        len(transcript),
    )

    return {
        "transcript": transcript,
        "duration_seconds": duration_seconds,
        "cost_usd": cost_usd,
    }
