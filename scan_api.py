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
    create_tasks_from_candidates,
    extract_text_from_image,
    parse_tasks_from_text,
)

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
            "candidates": [],
            "message": "No text detected in image",
        })

    # Step 2: Parse into task candidates via Claude
    try:
        candidates = parse_tasks_from_text(ocr_text)
    except RuntimeError as e:
        logger.warning("Task parsing failed: %s", e)
        return jsonify({"error": f"Task parsing failed: {e}"}), 422
    except Exception:
        logger.exception("Task parsing crashed unexpectedly")
        return jsonify({"error": "Task parsing failed (unexpected)"}), 500

    return jsonify({
        "ocr_text": ocr_text,
        "candidates": [
            {"title": title, "type": "work", "included": True}
            for title in candidates
        ],
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

    tasks = create_tasks_from_candidates(candidates)
    return jsonify({
        "created": len(tasks),
        "tasks": [
            {"id": str(t.id), "title": t.title, "tier": t.tier.value}
            for t in tasks
        ],
    }), 201
