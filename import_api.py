"""JSON API for the import feature.

Endpoints:
    POST /api/import/tasks/parse    — parse OneNote text, return candidates
    POST /api/import/tasks/upload   — parse OneNote .docx file, return candidates
    POST /api/import/tasks/confirm  — confirm task candidates, create in Inbox
    POST /api/import/goals/parse    — parse Excel file, return goal candidates
    POST /api/import/goals/confirm  — confirm goal candidates, create goals
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from auth import login_required
from import_service import (
    create_goals_from_import,
    create_tasks_from_import,
    find_duplicate_goals,
    find_duplicate_tasks,
    parse_excel_goals,
    parse_onenote_docx,
    parse_onenote_text,
)

bp = Blueprint("import_api", __name__, url_prefix="/api/import")

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


# --- OneNote tasks -----------------------------------------------------------


@bp.post("/tasks/parse")
@login_required
def parse_tasks(email: str):  # noqa: ARG001
    """Parse pasted OneNote text into task candidates.

    Expects JSON body: {"text": "...pasted OneNote content..."}
    Returns candidates with duplicate flags.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    text = data.get("text", "")
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "text field is required"}), 400

    candidates = parse_onenote_text(text)

    # Flag duplicates
    titles = [c["title"] for c in candidates]
    duplicates = set(t.lower() for t in find_duplicate_tasks(titles))
    for c in candidates:
        c["duplicate"] = c["title"].lower() in duplicates

    return jsonify({"candidates": candidates, "total": len(candidates)})


@bp.post("/tasks/upload")
@login_required
def upload_tasks(email: str):  # noqa: ARG001
    """Parse an uploaded OneNote .docx file into task candidates.

    Accepts multipart/form-data with a 'file' field (.docx).
    Returns candidates with duplicate flags.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No filename"}), 400

    if not file.filename.lower().endswith(".docx"):
        return jsonify({"error": "Only .docx files are supported"}), 422

    file_bytes = file.read()

    if len(file_bytes) > MAX_FILE_SIZE:
        return jsonify({"error": "File too large (max 5MB)"}), 413

    if not file_bytes:
        return jsonify({"error": "Empty file"}), 400

    try:
        candidates = parse_onenote_docx(file_bytes)
    except ValueError as e:
        return jsonify({"error": str(e)}), 422

    # Flag duplicates
    titles = [c["title"] for c in candidates]
    duplicates = set(t.lower() for t in find_duplicate_tasks(titles))
    for c in candidates:
        c["duplicate"] = c["title"].lower() in duplicates

    return jsonify({"candidates": candidates, "total": len(candidates)})


@bp.post("/tasks/confirm")
@login_required
def confirm_tasks(email: str):  # noqa: ARG001
    """Confirm task candidates and create them in Inbox.

    Expects JSON body:
    {
        "candidates": [{"title": "...", "type": "work", "included": true}, ...],
        "source": "onenote_2026_04_06"
    }
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    candidates = data.get("candidates", [])
    if not isinstance(candidates, list):
        return jsonify({"error": "candidates must be a list"}), 422

    source = data.get("source", "onenote_import")
    tasks = create_tasks_from_import(candidates, source=source)

    return jsonify({
        "created": len(tasks),
        "tasks": [
            {"id": str(t.id), "title": t.title, "tier": t.tier.value}
            for t in tasks
        ],
    }), 201


# --- Excel goals -------------------------------------------------------------


@bp.post("/goals/parse")
@login_required
def parse_goals(email: str):  # noqa: ARG001
    """Parse uploaded Excel file into goal candidates.

    Accepts multipart/form-data with a 'file' field (.xlsx).
    Returns goal candidates with duplicate flags.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No filename"}), 400

    if not file.filename.lower().endswith(".xlsx"):
        return jsonify({"error": "Only .xlsx files are supported"}), 422

    file_bytes = file.read()

    if len(file_bytes) > MAX_FILE_SIZE:
        return jsonify({"error": "File too large (max 5MB)"}), 413

    if not file_bytes:
        return jsonify({"error": "Empty file"}), 400

    try:
        candidates = parse_excel_goals(file_bytes)
    except ValueError as e:
        return jsonify({"error": str(e)}), 422

    # Flag duplicates
    titles = [c["title"] for c in candidates]
    duplicates = set(t.lower() for t in find_duplicate_goals(titles))
    for c in candidates:
        c["duplicate"] = c["title"].lower() in duplicates

    return jsonify({"candidates": candidates, "total": len(candidates)})


@bp.post("/goals/confirm")
@login_required
def confirm_goals(email: str):  # noqa: ARG001
    """Confirm goal candidates and create them.

    Expects JSON body:
    {
        "candidates": [{"title": "...", "category": "work", ...}, ...],
        "source": "excel_goals_2026_04_06"
    }
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    candidates = data.get("candidates", [])
    if not isinstance(candidates, list):
        return jsonify({"error": "candidates must be a list"}), 422

    source = data.get("source", "excel_goals_import")
    goals = create_goals_from_import(candidates, source=source)

    return jsonify({
        "created": len(goals),
        "goals": [
            {"id": str(g.id), "title": g.title, "category": g.category.value}
            for g in goals
        ],
    }), 201
