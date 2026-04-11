"""JSON API for the image scan to tasks feature.

Endpoints:
    POST /api/scan/upload   — upload image, get OCR text + task candidates
    POST /api/scan/confirm  — confirm candidates, create tasks in inbox
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from auth import login_required
from scan_service import (
    create_goals_from_candidates,
    create_tasks_from_candidates,
    extract_text_from_image,
    parse_goals_from_text,
    parse_tasks_from_text,
)

# Scan modes. Clients pass ``parse_as`` in the upload form-data and
# ``kind`` in the confirm JSON. We accept plural or singular for both
# so the UI can use whichever reads more naturally.
_VALID_KINDS = {"tasks", "task", "goals", "goal"}


def _normalize_kind(raw: str | None) -> str:
    """Return canonical 'tasks' or 'goals'. Defaults to 'tasks'."""
    if not raw:
        return "tasks"
    raw = raw.strip().lower()
    if raw in ("goal", "goals"):
        return "goals"
    return "tasks"

logger = logging.getLogger(__name__)

bp = Blueprint("scan_api", __name__, url_prefix="/api/scan")

# Maximum upload size: 10MB
MAX_IMAGE_SIZE = 10 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


@bp.post("/upload")
@login_required
def upload(email: str):  # noqa: ARG001
    """Upload an image and get task candidates.

    Accepts multipart/form-data with an 'image' file field.
    Returns the raw OCR text and parsed task candidates.

    The image is processed entirely in memory — it is never
    written to disk or stored in the database.
    """
    # parse_as selects whether Claude extracts tasks or goals from the
    # OCR text. Invalid values fall back to "tasks" silently — the
    # frontend toggle is the source of truth.
    kind = _normalize_kind(request.form.get("parse_as"))

    if "image" not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    file = request.files["image"]
    if not file.filename:
        return jsonify({"error": "No filename"}), 400

    # Validate content type. Log the rejected type so we can see if iOS is
    # sending unexpected MIME types (e.g. image/heic, application/octet-stream).
    if file.content_type not in ALLOWED_TYPES:
        logger.warning(
            "scan upload rejected: unsupported content_type=%r filename_ext=%r",
            file.content_type,
            (file.filename or "").rsplit(".", 1)[-1].lower(),
        )
        return jsonify({
            "error": f"Unsupported image type: {file.content_type}",
            "allowed": list(ALLOWED_TYPES),
        }), 422

    # Read image bytes (in memory only — never written to disk)
    image_bytes = file.read()

    if len(image_bytes) > MAX_IMAGE_SIZE:
        return jsonify({"error": "Image too large (max 10MB)"}), 413

    if not image_bytes:
        return jsonify({"error": "Empty file"}), 400

    logger.info(
        "scan upload received: content_type=%s size=%d",
        file.content_type, len(image_bytes),
    )

    # Step 1: OCR via Google Vision
    try:
        ocr_text = extract_text_from_image(image_bytes)
    except RuntimeError as e:
        # Known/expected failure — surface details (already sanitized by
        # scan_service to never include the API key).
        logger.warning("OCR failed: %s", e)
        return jsonify({"error": f"OCR failed: {e}"}), 422
    except Exception:
        # Unexpected — log full traceback so we can actually see what broke.
        logger.exception("OCR processing crashed unexpectedly")
        return jsonify({"error": "OCR processing failed (unexpected)"}), 500

    if not ocr_text.strip():
        return jsonify({
            "ocr_text": "",
            "kind": kind,
            "candidates": [],
            "message": "No text detected in image",
        })

    # Step 2: Parse into candidates via Claude — either tasks or goals
    # depending on the kind the user selected. Each branch returns the
    # full candidate dict shape the review UI will render.
    try:
        if kind == "goals":
            goal_dicts = parse_goals_from_text(ocr_text)
            candidates_out = [
                {
                    "title": (g.get("title") or "").strip(),
                    "category": g.get("category") or "personal_growth",
                    "priority": g.get("priority") or "need_more_info",
                    "target_quarter": g.get("target_quarter") or "",
                    "actions": g.get("actions") or "",
                    "included": True,
                }
                for g in goal_dicts
                if (g.get("title") or "").strip()
            ]
        else:
            task_titles = parse_tasks_from_text(ocr_text)
            candidates_out = [
                {"title": title, "type": "work", "included": True}
                for title in task_titles
            ]
    except RuntimeError as e:
        logger.warning("%s parsing failed: %s", kind.capitalize(), e)
        return jsonify({"error": f"{kind.capitalize()} parsing failed: {e}"}), 422
    except Exception:
        logger.exception("%s parsing crashed unexpectedly", kind.capitalize())
        return jsonify(
            {"error": f"{kind.capitalize()} parsing failed (unexpected)"}
        ), 500

    return jsonify({
        "ocr_text": ocr_text,
        "kind": kind,
        "candidates": candidates_out,
    })


@bp.post("/confirm")
@login_required
def confirm(email: str):  # noqa: ARG001
    """Confirm task candidates and create them in the inbox.

    Expects JSON body:
    {
        "candidates": [
            {"title": "Task text", "type": "work", "included": true},
            {"title": "Skipped", "type": "personal", "included": false}
        ]
    }
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    candidates = data.get("candidates", [])
    if not isinstance(candidates, list):
        return jsonify({"error": "candidates must be a list"}), 422

    kind = _normalize_kind(data.get("kind"))

    if kind == "goals":
        goals = create_goals_from_candidates(candidates)
        return jsonify({
            "kind": "goals",
            "created": len(goals),
            "goals": [
                {
                    "id": str(g.id),
                    "title": g.title,
                    "category": g.category.value,
                    "priority": g.priority.value,
                }
                for g in goals
            ],
        }), 201

    tasks = create_tasks_from_candidates(candidates)
    return jsonify({
        "kind": "tasks",
        "created": len(tasks),
        "tasks": [
            {"id": str(t.id), "title": t.title, "tier": t.tier.value}
            for t in tasks
        ],
    }), 201
