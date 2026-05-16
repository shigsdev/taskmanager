"""JSON API for the Weekly Reflection feature.

Endpoints:
    POST /api/reflection                       — submit a reflection (typed
        JSON {"text": ...} OR multipart audio field "audio"); transcribes
        if audio, persists the Reflection, returns AI-proposed actions
    POST /api/reflection/<id>/confirm          — apply the user-selected
        actions; returns an apply summary
    GET  /api/reflection                       — list past reflections
    GET  /api/reflection/<id>                  — one reflection + its
        proposed/applied actions (history detail)

The transcript is always persisted (the user explicitly wants every
reflection kept for future reference). Audio is processed in memory only
— never written to disk or the DB (handled by voice_service).
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from auth import login_required
from models import ReflectionInputMode
from rate_limit import limiter
from reflection_service import (
    analyze_reflection,
    apply_selected_actions,
    get_reflection,
    list_reflections,
    save_reflection,
)
from utils import validate_upload
from voice_service import (
    ALLOWED_AUDIO_TYPES,
    WHISPER_MAX_UPLOAD_BYTES,
    transcribe_audio,
)

logger = logging.getLogger(__name__)

bp = Blueprint("reflection_api", __name__, url_prefix="/api/reflection")


def _serialize(reflection) -> dict:
    proposed = reflection.proposed_actions or {}
    return {
        "id": str(reflection.id),
        "iso_week": reflection.iso_week,
        "input_mode": reflection.input_mode.value,
        "transcript": reflection.transcript,
        "audio_duration_seconds": reflection.audio_duration_seconds,
        "audio_cost_usd": reflection.audio_cost_usd,
        "ai_cost_usd": reflection.ai_cost_usd,
        "proposed_actions": {
            "explicit": proposed.get("explicit", []),
            "suggested": proposed.get("suggested", []),
        },
        "applied_actions": reflection.applied_actions,
        "applied_at": (
            reflection.applied_at.isoformat()
            if reflection.applied_at
            else None
        ),
        "created_at": reflection.created_at.isoformat(),
    }


@bp.post("")
@login_required
@limiter.limit("20 per minute")  # paid: Whisper (audio) + Claude
def submit(email: str):  # noqa: ARG001
    """Submit a reflection. Accepts EITHER multipart/form-data with an
    'audio' file field OR a JSON body ``{"text": "..."}``.

    Returns the persisted reflection id, transcript, and the AI's
    proposed actions (explicit + suggested buckets). Nothing is written
    to projects/goals/tasks until the /confirm endpoint runs.
    """
    audio_file = request.files.get("audio")
    duration = None
    audio_cost = None

    if audio_file is not None:
        audio_bytes, content_type, err = validate_upload(
            request,
            field_name="audio",
            allowed_mime=ALLOWED_AUDIO_TYPES,
            max_bytes=WHISPER_MAX_UPLOAD_BYTES,
        )
        if err:
            body, status = err
            if status == 422:
                logger.warning(
                    "reflection audio rejected: %s", body.get("error")
                )
            return jsonify(body), status
        try:
            result = transcribe_audio(audio_bytes, content_type)
        except RuntimeError as e:
            logger.warning("Reflection transcription failed: %s", e)
            return jsonify({"error": f"Transcription failed: {e}"}), 422
        except Exception:
            logger.exception("Reflection transcription crashed")
            return jsonify(
                {"error": "Transcription failed (unexpected)"}
            ), 500
        transcript = result["transcript"]
        duration = result["duration_seconds"]
        audio_cost = result["cost_usd"]
        input_mode = ReflectionInputMode.VOICE
    else:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "JSON body or audio file required"}), 400
        transcript = (data.get("text") or "").strip()
        input_mode = ReflectionInputMode.TYPED

    if not transcript or not transcript.strip():
        return jsonify({
            "error": "Reflection is empty — nothing to analyze",
        }), 422

    # Analyze with Claude (proposes create/update/delete actions).
    try:
        analysis = analyze_reflection(transcript)
    except RuntimeError as e:
        logger.warning("Reflection analysis failed: %s", e)
        return jsonify({"error": f"Analysis failed: {e}"}), 422
    except Exception:
        logger.exception("Reflection analysis crashed unexpectedly")
        return jsonify(
            {"error": "Analysis failed (unexpected)"}
        ), 500

    reflection = save_reflection(
        transcript=transcript,
        input_mode=input_mode,
        proposed={
            "explicit": analysis["explicit"],
            "suggested": analysis["suggested"],
        },
        audio_duration_seconds=duration,
        audio_cost_usd=audio_cost,
        ai_cost_usd=analysis["ai_cost_usd"],
    )

    return jsonify(_serialize(reflection)), 201


@bp.post("/<uuid:reflection_id>/confirm")
@login_required
def confirm(email: str, reflection_id):  # noqa: ARG001
    """Apply the user-confirmed actions for a reflection.

    Expects JSON ``{"actions": [ <normalized action>, ... ]}`` — the
    subset of proposed actions the user checked (optionally edited).
    Re-validated server-side through the service layer; creations are
    grouped for recycle-bin undo, deletes are soft.
    """
    reflection = get_reflection(reflection_id)
    if reflection is None:
        return jsonify({"error": "Reflection not found"}), 404

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    actions = data.get("actions", [])
    if not isinstance(actions, list):
        return jsonify({"error": "actions must be a list"}), 422

    if reflection.applied_at is not None:
        return jsonify({
            "error": "This reflection has already been applied",
        }), 409

    try:
        summary = apply_selected_actions(reflection, actions)
    except Exception:
        logger.exception("Reflection apply crashed unexpectedly")
        return jsonify({"error": "Apply failed (unexpected)"}), 500

    return jsonify({
        "id": str(reflection.id),
        "summary": summary,
        "applied_at": reflection.applied_at.isoformat(),
    }), 200


@bp.get("")
@login_required
def list_all(email: str):  # noqa: ARG001
    """List past reflections (newest first) for the history view."""
    reflections = list_reflections()
    return jsonify({
        "reflections": [_serialize(r) for r in reflections],
    })


@bp.get("/<uuid:reflection_id>")
@login_required
def detail(email: str, reflection_id):  # noqa: ARG001
    """One reflection with its transcript + proposed/applied actions."""
    reflection = get_reflection(reflection_id)
    if reflection is None:
        return jsonify({"error": "Reflection not found"}), 404
    return jsonify(_serialize(reflection))
