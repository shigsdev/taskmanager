"""JSON API for voice memo capture.

Endpoints:
    POST /api/voice-memo          — upload audio, transcribe, parse, return candidates
    POST /api/voice-memo/confirm  — create tasks from confirmed candidates

The confirm endpoint reuses the scan_service candidate-creation logic
with a "voice" source prefix so the recycle bin / undo flow can
distinguish voice batches from scan batches.

Audio is processed entirely in memory — never written to disk or DB.
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from auth import login_required
from scan_service import create_tasks_from_candidates, parse_tasks_from_text
from voice_service import (
    ALLOWED_AUDIO_TYPES,
    WHISPER_MAX_UPLOAD_BYTES,
    transcribe_audio,
)

logger = logging.getLogger(__name__)

bp = Blueprint("voice_api", __name__, url_prefix="/api/voice-memo")


@bp.post("")
@login_required
def upload(email: str):  # noqa: ARG001
    """Receive an audio file, transcribe it, parse into task candidates.

    Accepts multipart/form-data with an 'audio' file field.

    Returns JSON::

        {
            "transcript": "Need to call the dentist tomorrow ...",
            "duration_seconds": 47.3,
            "cost_usd": 0.0047,
            "candidates": [
                {"title": "Call dentist", "type": "work", "included": true},
                ...
            ]
        }

    On 422 the JSON body always includes ``error`` with a user-safe
    message (no API keys, no full stack traces).
    """
    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    file = request.files["audio"]
    if not file.filename:
        return jsonify({"error": "No filename"}), 400

    # Validate content type. Log the rejected type so we can see what
    # browsers send (Safari and Chrome differ on default codecs).
    if file.content_type not in ALLOWED_AUDIO_TYPES:
        logger.warning(
            "voice memo upload rejected: unsupported content_type=%r",
            file.content_type,
        )
        return jsonify({
            "error": f"Unsupported audio type: {file.content_type}",
            "allowed": sorted(ALLOWED_AUDIO_TYPES),
        }), 422

    # Read audio bytes (in memory only — never written to disk)
    audio_bytes = file.read()

    if len(audio_bytes) > WHISPER_MAX_UPLOAD_BYTES:
        return jsonify({
            "error": (
                f"Audio file too large "
                f"({len(audio_bytes) // 1024 // 1024} MB; max "
                f"{WHISPER_MAX_UPLOAD_BYTES // 1024 // 1024} MB)"
            ),
        }), 413

    if not audio_bytes:
        return jsonify({"error": "Empty file"}), 400

    logger.info(
        "voice memo upload received: content_type=%s size=%d",
        file.content_type, len(audio_bytes),
    )

    # Step 1: transcribe via Whisper
    try:
        result = transcribe_audio(audio_bytes, file.content_type)
    except RuntimeError as e:
        logger.warning("Whisper transcription failed: %s", e)
        return jsonify({"error": f"Transcription failed: {e}"}), 422
    except Exception:
        logger.exception("Whisper transcription crashed unexpectedly")
        return jsonify({
            "error": "Transcription failed (unexpected)",
        }), 500

    transcript = result["transcript"]
    if not transcript.strip():
        return jsonify({
            "transcript": "",
            "duration_seconds": result["duration_seconds"],
            "cost_usd": result["cost_usd"],
            "candidates": [],
            "message": "No speech detected in audio",
        })

    # Step 2: parse into task candidates via Claude (reuses scan_service)
    try:
        task_titles = parse_tasks_from_text(transcript)
    except RuntimeError as e:
        # Transcription succeeded but parsing failed — return the
        # transcript anyway so the user can recover (manual paste from
        # transcript into capture bar). Return 422 so the frontend
        # knows to show the transcript-with-error UI.
        logger.warning("Voice memo parsing failed: %s", e)
        return jsonify({
            "transcript": transcript,
            "duration_seconds": result["duration_seconds"],
            "cost_usd": result["cost_usd"],
            "candidates": [],
            "error": f"Parsing failed: {e}",
        }), 422
    except Exception:
        logger.exception("Voice memo parsing crashed unexpectedly")
        return jsonify({
            "transcript": transcript,
            "duration_seconds": result["duration_seconds"],
            "cost_usd": result["cost_usd"],
            "candidates": [],
            "error": "Parsing failed (unexpected)",
        }), 500

    candidates_out = [
        {"title": title, "type": "work", "included": True}
        for title in task_titles
    ]

    return jsonify({
        "transcript": transcript,
        "duration_seconds": result["duration_seconds"],
        "cost_usd": result["cost_usd"],
        "candidates": candidates_out,
    })


@bp.post("/confirm")
@login_required
def confirm(email: str):  # noqa: ARG001
    """Confirm task candidates and create them in the inbox.

    Expects JSON body::

        {
            "candidates": [
                {"title": "...", "type": "work", "included": true},
                ...
            ]
        }

    Records the batch in ImportLog with a "voice_..." source prefix so
    the recycle bin / undo flow can distinguish voice-memo batches.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    candidates = data.get("candidates", [])
    if not isinstance(candidates, list):
        return jsonify({"error": "candidates must be a list"}), 422

    tasks = create_tasks_from_candidates(candidates, source_prefix="voice")
    return jsonify({
        "created": len(tasks),
        "tasks": [
            {"id": str(t.id), "title": t.title, "tier": t.tier.value}
            for t in tasks
        ],
    }), 201
