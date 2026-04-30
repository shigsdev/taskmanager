"""JSON API for the image scan to tasks feature.

Endpoints:
    POST /api/scan/upload   — upload image, get OCR text + task candidates
    POST /api/scan/confirm  — confirm candidates, create tasks in inbox
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from auth import login_required
from import_service import create_projects_from_import
from rate_limit import limiter
from scan_service import (
    create_goals_from_candidates,
    create_tasks_from_candidates,
    extract_text_from_image,
    parse_goals_from_text,
    parse_projects_from_text,
    parse_tasks_from_text,
)
from utils import validate_upload

# Scan modes. Clients pass ``parse_as`` in the upload form-data and
# ``kind`` in the confirm JSON. We accept plural or singular for both
# so the UI can use whichever reads more naturally.
_VALID_KINDS = {"tasks", "task", "goals", "goal", "projects", "project"}


def _normalize_kind(raw: str | None) -> str:
    """Return canonical 'tasks' / 'goals' / 'projects'. Defaults to 'tasks'."""
    if not raw:
        return "tasks"
    raw = raw.strip().lower()
    if raw in ("goal", "goals"):
        return "goals"
    if raw in ("project", "projects"):
        return "projects"
    return "tasks"

logger = logging.getLogger(__name__)

bp = Blueprint("scan_api", __name__, url_prefix="/api/scan")

# Maximum upload size: 10MB
MAX_IMAGE_SIZE = 10 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


@bp.post("/upload")
@login_required
@limiter.limit("20 per minute")  # PR64 #124: scan/upload calls Vision + Claude (paid)
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

    image_bytes, content_type, err = validate_upload(
        request,
        field_name="image",
        allowed_mime=ALLOWED_TYPES,
        max_bytes=MAX_IMAGE_SIZE,
    )
    if err:
        body, status = err
        if status == 422:
            logger.warning(
                "scan upload rejected: %s (filename ext was %r)",
                body.get("error"),
                ((request.files.get("image") and request.files["image"].filename)
                 or "").rsplit(".", 1)[-1].lower(),
            )
        return jsonify(body), status

    logger.info(
        "scan upload received: content_type=%s size=%d",
        content_type, len(image_bytes),
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
        elif kind == "projects":
            # #86 (2026-04-26): scan → projects. UI uses `title` for the
            # input even though projects are stored as `name`; we expose
            # both so the same renderer + confirm path works.
            proj_dicts = parse_projects_from_text(ocr_text)
            candidates_out = [
                {
                    "title": (p.get("name") or "").strip(),
                    "type": p.get("type") or "work",
                    "target_quarter": p.get("target_quarter") or "",
                    "included": True,
                }
                for p in proj_dicts
                if (p.get("name") or "").strip()
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

    if kind == "projects":
        # #86 (2026-04-26): re-use the import_service creator so the same
        # batch_id + ImportLog pattern applies (recycle-bin batch undo
        # works for scan-created projects).
        projects = create_projects_from_import(candidates, source="scan_projects")
        return jsonify({
            "kind": "projects",
            "created": len(projects),
            "projects": [
                {"id": str(p.id), "name": p.name, "type": p.type.value}
                for p in projects
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
