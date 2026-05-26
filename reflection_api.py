"""JSON API for the Weekly Reflection feature.

Endpoints:
    POST /api/reflection                       — submit a reflection (typed
        JSON {"text": ...} OR multipart audio field "audio"); transcribes
        if audio, persists the Reflection, returns AI-proposed actions
    POST /api/reflection/transcribe-segment    — transcribe ONE audio
        segment (#232 pause+resume). No Reflection row, no Claude call —
        just audio→text. Frontend appends the text to its textarea and
        eventually POSTs the merged content to the main endpoint above.
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

from flask import Blueprint, g, jsonify, request

from auth import login_required
from models import ReflectionInputMode
from rate_limit import PAID_API, limiter
from reflection_service import (
    analyze_reflection,
    apply_selected_actions,
    attach_analysis,
    get_reflection,
    list_reflections,
    save_reflection,
)
from utils import validate_json_body, validate_upload
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
        # #237 (2026-05-26): raw per-segment Whisper transcripts from
        # the #232 pause/resume flow. Empty list for typed reflections
        # and for pre-#237 voice reflections.
        "raw_segments": reflection.raw_segments or [],
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
@limiter.limit(PAID_API)  # paid: Whisper (audio) + Claude
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

    # #237 (2026-05-26): the JSON path also carries `raw_segments` —
    # the per-segment Whisper transcripts the user accumulated via
    # the #232 pause/resume flow. Persisted alongside the final
    # (possibly edited) `transcript` so an edit doesn't lose the
    # original spoken words. Only the JSON path has this — the
    # audio-upload path is a single-shot recording with no segments
    # (kept for back-compat / direct one-shot voice memos).
    raw_segments: list | None = None
    if audio_file is None:
        rs = data.get("raw_segments") if isinstance(data, dict) else None
        if isinstance(rs, list):
            raw_segments = rs
            # If raw_segments were sent, this came from the #232
            # pause/resume flow — mark as VOICE input even though the
            # final POST is JSON (the textarea content was assembled
            # from voice transcripts).
            if rs:
                input_mode = ReflectionInputMode.VOICE

    # Persist the transcript FIRST, before the paid + failure-prone
    # Claude call. #165 requires every transcript persisted forever;
    # the original order (analyze → save) discarded the reflection on
    # any Claude failure — worst case losing a voice memo that already
    # cost a Whisper transcription. proposed_actions starts empty and
    # gets attached on analysis success.
    reflection = save_reflection(
        transcript=transcript,
        input_mode=input_mode,
        proposed={"explicit": [], "suggested": []},
        audio_duration_seconds=duration,
        audio_cost_usd=audio_cost,
        ai_cost_usd=None,
        raw_segments=raw_segments,  # #237
    )

    # Analyze with Claude (proposes create/update/delete actions). On
    # failure the reflection is ALREADY saved — return its id + the
    # error so the client shows "saved, analysis failed — retry" and
    # the transcript is visible in the history list, NOT lost.
    try:
        analysis = analyze_reflection(transcript)
    except RuntimeError as e:
        logger.warning(
            "Reflection analysis failed (transcript %s saved): %s",
            reflection.id, e,
        )
        return jsonify({
            "error": f"Analysis failed: {e}",
            "reflection_id": str(reflection.id),
            "saved": True,
        }), 422
    except Exception:
        logger.exception(
            "Reflection analysis crashed unexpectedly "
            "(transcript %s saved)", reflection.id,
        )
        return jsonify({
            "error": "Analysis failed (unexpected)",
            "reflection_id": str(reflection.id),
            "saved": True,
        }), 500

    reflection = attach_analysis(
        reflection,
        proposed={
            "explicit": analysis["explicit"],
            "suggested": analysis["suggested"],
        },
        ai_cost_usd=analysis["ai_cost_usd"],
    )

    return jsonify(_serialize(reflection)), 201


@bp.post("/transcribe-segment")
@login_required
@limiter.limit(PAID_API)  # paid: Whisper
def transcribe_segment(email: str):  # noqa: ARG001
    """Transcribe ONE audio segment for the #232 pause+resume flow.

    Accepts multipart/form-data with an 'audio' file field (same MIME
    whitelist + size cap as ``POST /api/reflection``). Returns just the
    raw transcription — no Reflection row is saved, no Claude analysis
    is run. The frontend appends the returned text to its shared
    ``#reflText`` textarea; when the user clicks Done it POSTs the full
    merged content to ``POST /api/reflection`` (text path), which runs
    the persist + Claude steps exactly as before.

    This decoupling keeps cost predictable (one Whisper call per
    segment, one Claude call per finalized reflection) and bounds the
    blast radius of a network blip: if one segment fails the
    frontend retries that segment only; prior segments' text is already
    in the textarea and unaffected.

    Returns JSON::

        {
            "transcript": "...",
            "duration_seconds": 12.5,
            "cost_usd": 0.0012
        }
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
            logger.warning(
                "reflection segment rejected: %s", body.get("error"),
            )
        return jsonify(body), status

    try:
        result = transcribe_audio(audio_bytes, content_type)
    except RuntimeError as e:
        logger.warning("Reflection segment transcription failed: %s", e)
        return jsonify({"error": f"Transcription failed: {e}"}), 422
    except Exception:
        logger.exception("Reflection segment transcription crashed")
        return jsonify(
            {"error": "Transcription failed (unexpected)"}
        ), 500

    return jsonify({
        "transcript": result["transcript"],
        "duration_seconds": result["duration_seconds"],
        "cost_usd": result["cost_usd"],
    })


@bp.post("/<uuid:reflection_id>/confirm")
@login_required
@validate_json_body
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

    data = g.json_body
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
        # #174 (2026-05-21): apply_selected_actions is now exception-safe
        # — every step captures its own failure in summary["errors"] and
        # the function always returns a summary. This catch-all is a
        # genuine last resort (e.g. a bug in the summary-building itself)
        # and should almost never fire.
        logger.exception("Reflection apply crashed unexpectedly")
        return jsonify({"error": "Apply failed (unexpected)"}), 500

    # #174: surface partial success. apply_selected_actions records
    # per-step failures in summary["errors"] rather than aborting — so
    # a non-empty errors list means SOME actions landed and some did
    # not. Return 207 Multi-Status in that case so the client (and any
    # future automation) can tell "fully applied" from "partially
    # applied" without diffing the counts. `applied_at` is None when the
    # final audit-record commit itself failed — guard the .isoformat().
    status = 207 if summary.get("errors") else 200
    return jsonify({
        "id": str(reflection.id),
        "summary": summary,
        "applied_at": (
            reflection.applied_at.isoformat()
            if reflection.applied_at is not None
            else None
        ),
    }), status


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
