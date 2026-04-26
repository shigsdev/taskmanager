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
# webm/opus on Chrome/Android and mp4 on Safari. Browsers append codec
# parameters (e.g. "audio/mp4;codecs=mp4a.40.2") which voice_api strips
# before consulting this whitelist — keep the list to bare type/subtype.
ALLOWED_AUDIO_TYPES = frozenset({
    "audio/webm",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/x-wav",
})


# #67 (2026-04-26): voice memo intent router.
#
# Per scoping (a) "simple keyword router". Detects prefixes in a
# parsed candidate's title that signal it should become a goal or
# project instead of a task. Strips the prefix from the title.
#
# Order matters: check the more-specific phrases first (e.g.
# "create a project" before "create"), and longer prefixes before
# shorter ones to avoid greedy-shortest matching.
_GOAL_PREFIXES = (
    "create a goal:", "create a goal ",
    "new goal:", "new goal ",
    "add a goal:", "add a goal ",
    "goal:",
)
_PROJECT_PREFIXES = (
    "create a project:", "create a project ",
    "new project:", "new project ",
    "add a project:", "add a project ",
    "project:",
)


def classify_voice_candidate(title: str) -> tuple[str, str]:
    """Return ``(route, cleaned_title)`` for a single voice memo line.

    route ∈ {"task", "goal", "project"}. Default is "task".
    Prefix matching is case-insensitive; the prefix is stripped from
    the returned title and the leading whitespace is trimmed.
    """
    if not title:
        return "task", title or ""
    lowered = title.lstrip().lower()
    for prefix in _GOAL_PREFIXES:
        if lowered.startswith(prefix):
            return "goal", title.lstrip()[len(prefix):].strip()
    for prefix in _PROJECT_PREFIXES:
        if lowered.startswith(prefix):
            return "project", title.lstrip()[len(prefix):].strip()
    return "task", title


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
    extension Whisper expects.

    Accepts both ``;`` and ``:`` as parameter separators — iOS Safari
    has been observed sending the non-standard ``:`` form in some
    versions (e.g. ``audio/mp4:codecs-mp4a.40.2``).
    """
    import re
    mt = re.split(r"[;:]", (mime_type or "").lower(), maxsplit=1)[0].strip()
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

    Delegates the HTTP mechanics to ``egress.safe_call_api`` for
    consistent timeout + error handling across all third-party calls
    (see docs/adr/006). This wrapper keeps Whisper-specific shape
    (multipart file upload, duration parsing) and remains a stable
    monkeypatch target for tests.
    """
    from egress import EgressError, safe_call_api

    files = {
        "file": (_filename_for_mime(mime_type), io.BytesIO(audio_bytes), mime_type),
    }
    data = {
        "model": "whisper-1",
        # response_format=verbose_json gives us the duration field we
        # need for cost calculation. Alternative would be to compute
        # duration client-side via Web Audio API, but server-
        # authoritative is safer.
        "response_format": "verbose_json",
    }

    try:
        data = safe_call_api(
            url="https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files=files,
            data=data,
            timeout_sec=120,
            vendor="Whisper",
        )
    except EgressError as e:
        # Re-raise as RuntimeError to keep the existing public contract
        # of voice_service. Callers in voice_api.py catch RuntimeError.
        raise RuntimeError(str(e)) from e

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
