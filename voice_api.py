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
from scan_service import (
    create_tasks_from_candidates,
    parse_tasks_from_text,
    parse_voice_memo_to_tasks,
)
from utils import validate_upload
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
    audio_bytes, content_type, err = validate_upload(
        request,
        field_name="audio",
        allowed_mime=ALLOWED_AUDIO_TYPES,
        max_bytes=WHISPER_MAX_UPLOAD_BYTES,
    )
    if err:
        body, status = err
        if status == 422:
            logger.warning("voice memo upload rejected: %s", body.get("error"))
        return jsonify(body), status

    logger.info(
        "voice memo upload received: content_type=%s size=%d",
        content_type, len(audio_bytes),
    )

    # Step 1: transcribe via Whisper
    try:
        result = transcribe_audio(audio_bytes, content_type)
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

    # Step 2: parse into structured task candidates via Claude (#36).
    # The new parser returns dicts with inferred type/tier/due_date;
    # falls back to an empty list on malformed Claude output (which
    # the normalisation pass in scan_service handles). If the Claude
    # call itself raises, we fall through to the old title-only path
    # as a best-effort recovery.
    try:
        structured = parse_voice_memo_to_tasks(transcript)
    except RuntimeError as e:
        logger.warning("Voice memo structured parsing failed: %s", e)
        return jsonify({
            "transcript": transcript,
            "duration_seconds": result["duration_seconds"],
            "cost_usd": result["cost_usd"],
            "candidates": [],
            "error": f"Parsing failed: {e}",
        }), 422
    except Exception:
        logger.exception("Voice memo structured parsing crashed; "
                         "falling back to title-only extraction")
        try:
            titles = parse_tasks_from_text(transcript)
            structured = [
                {"title": t, "type": "personal", "tier": "inbox",
                 "due_date": None}
                for t in titles
            ]
        except Exception:
            logger.exception("Title-only fallback also crashed")
            return jsonify({
                "transcript": transcript,
                "duration_seconds": result["duration_seconds"],
                "cost_usd": result["cost_usd"],
                "candidates": [],
                "error": "Parsing failed (unexpected)",
            }), 500

    # Wire the inferred fields into the candidate shape the UI renders.
    # `included` starts true for every candidate (user unchecks to drop).
    # #67 (2026-04-26): classify each candidate as task/goal/project via
    # the keyword router. UI shows the route badge; user can override.
    from voice_service import classify_voice_candidate
    candidates_out = []
    for c in structured:
        route, cleaned = classify_voice_candidate(c["title"])
        candidates_out.append({
            "title": cleaned,
            "type": c["type"],
            "tier": c["tier"],
            "due_date": c["due_date"],
            "route": route,
            "included": True,
        })

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

    # #67 (2026-04-26): split candidates by route. Tasks go to the
    # existing voice creator; goals route through the import-goals
    # creator (already supports voice as a source). Projects bulk-
    # creation is queued for #80 — for now they're created as tasks
    # with "(project) " prefix so the user doesn't lose data, and a
    # warning is included in the response.
    task_candidates = []
    goal_candidates = []
    project_fallback_count = 0
    for c in candidates:
        if not isinstance(c, dict):
            continue
        route = c.get("route") or "task"
        if route == "goal":
            goal_candidates.append({
                "title": c.get("title"),
                "category": c.get("type") if c.get("type") in (
                    "health", "personal_growth", "relationships", "work", "bau",
                ) else "work",
                "priority": c.get("priority") or "should",
                "included": c.get("included", True),
            })
        elif route == "project":
            # Defer project creation until #80 ships the bulk endpoint.
            project_fallback_count += 1
            task_candidates.append({
                **c,
                "title": "(project) " + (c.get("title") or ""),
            })
        else:
            task_candidates.append(c)

    tasks = create_tasks_from_candidates(task_candidates, source_prefix="voice")

    goals_created = []
    if goal_candidates:
        from import_service import create_goals_from_import
        goals_created = create_goals_from_import(goal_candidates, source="voice_goal")

    response = {
        "created": len(tasks) + len(goals_created),
        "tasks": [
            {"id": str(t.id), "title": t.title, "tier": t.tier.value}
            for t in tasks
        ],
        "goals": [
            {"id": str(g.id), "title": g.title, "category": g.category.value}
            for g in goals_created
        ],
    }
    if project_fallback_count > 0:
        response["warning"] = (
            f"{project_fallback_count} project candidate(s) created as tasks "
            f"with '(project) ' prefix — bulk project creation lands with #80."
        )
    return jsonify(response), 201
