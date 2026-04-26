"""JSON API for the import feature.

Endpoints:
    POST /api/import/tasks/parse    — parse OneNote text, return candidates
    POST /api/import/tasks/upload   — parse OneNote .docx file, return candidates
    POST /api/import/tasks/confirm  — confirm task candidates, create in Inbox
    POST /api/import/goals/parse    — parse Excel file, return goal candidates
    POST /api/import/goals/confirm  — confirm goal candidates, create goals
    GET  /api/import/template/<kind>.xlsx — download a pre-built .xlsx
        template for each import mode (kinds: tasks, goals, projects)
"""
from __future__ import annotations

import io

from flask import Blueprint, abort, jsonify, request, send_file

from auth import login_required
from import_service import (
    create_goals_from_import,
    create_projects_from_import,
    create_tasks_from_import,
    find_duplicate_goals,
    find_duplicate_projects,
    find_duplicate_tasks,
    parse_excel_goals,
    parse_excel_projects,
    parse_excel_tasks,
    parse_onenote_docx,
    parse_onenote_text,
    parse_project_names_text,
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


@bp.post("/tasks/upload-xlsx")
@login_required
def upload_tasks_xlsx(email: str):  # noqa: ARG001
    """#89 (2026-04-26): parse an uploaded .xlsx of task rows.

    Accepts multipart/form-data with a 'file' field (.xlsx).
    Required header: title. Optional: type, tier, due_date, linked_goal,
    linked_project, notes, url. linked_* matched case-insensitively at
    create time.
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
        candidates = parse_excel_tasks(file_bytes)
    except ValueError as e:
        return jsonify({"error": str(e)}), 422

    titles = [c["title"] for c in candidates]
    duplicates = {t.lower() for t in find_duplicate_tasks(titles)}
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


# --- #80 (2026-04-26): Projects bulk-upload ---------------------------------


@bp.post("/projects/parse")
@login_required
def parse_projects(email: str):  # noqa: ARG001
    """Parse pasted text (one name per line) into project candidates."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "text" not in data:
        return jsonify({"error": "JSON body with 'text' required"}), 400

    text = data.get("text", "")
    if not isinstance(text, str):
        return jsonify({"error": "'text' must be a string"}), 422

    candidates = parse_project_names_text(text)

    names = [c["name"] for c in candidates]
    duplicates = {n.lower() for n in find_duplicate_projects(names)}
    for c in candidates:
        c["duplicate"] = c["name"].lower() in duplicates

    return jsonify({"candidates": candidates, "total": len(candidates)})


@bp.post("/projects/upload")
@login_required
def upload_projects(email: str):  # noqa: ARG001
    """Parse uploaded Excel file (.xlsx) into project candidates."""
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
        candidates = parse_excel_projects(file_bytes)
    except ValueError as e:
        return jsonify({"error": str(e)}), 422

    names = [c["name"] for c in candidates]
    duplicates = {n.lower() for n in find_duplicate_projects(names)}
    for c in candidates:
        c["duplicate"] = c["name"].lower() in duplicates

    return jsonify({"candidates": candidates, "total": len(candidates)})


@bp.post("/projects/confirm")
@login_required
def confirm_projects(email: str):  # noqa: ARG001
    """Confirm project candidates and create them."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    candidates = data.get("candidates", [])
    if not isinstance(candidates, list):
        return jsonify({"error": "candidates must be a list"}), 422

    source = data.get("source", "projects_import")
    projects = create_projects_from_import(candidates, source=source)

    return jsonify({
        "created": len(projects),
        "projects": [
            {"id": str(p.id), "name": p.name, "type": p.type.value}
            for p in projects
        ],
    }), 201


# --- Downloadable Excel templates (#91) -------------------------------------

# Header rows + 1-2 example rows for each import kind. Headers MUST stay
# in lockstep with the parsers in import_service.py — the docs section
# in templates/docs.html cites those source ranges. Update both together
# if columns ever change.
_TEMPLATE_SHEETS: dict[str, dict] = {
    "tasks": {
        "filename": "tasks_import_template.xlsx",
        "headers": [
            "title", "type", "tier", "due_date",
            "linked_goal", "linked_project", "notes", "url",
        ],
        "examples": [
            ["Draft Q3 plan", "work", "this_week", "2026-05-15",
             "Ship Q3 release", "Roadmap", "Outline scope first", ""],
            ["Buy birthday gift", "personal", "tomorrow", "",
             "", "", "Something handmade", "https://etsy.com"],
        ],
    },
    "goals": {
        "filename": "goals_import_template.xlsx",
        "headers": [
            "title", "category", "priority", "actions",
            "target_quarter", "status", "notes",
        ],
        "examples": [
            ["Run a half marathon", "health", "should",
             "Train 4x/week", "2026-Q3", "in_progress", "Knee feels good"],
            ["Read 20 books", "personal_growth", "could",
             "Pick from staff picks shelf", "2026-Q4", "not_started", ""],
        ],
    },
    "projects": {
        "filename": "projects_import_template.xlsx",
        "headers": [
            "name", "type", "target_quarter", "status",
            "color", "actions", "notes", "linked_goal",
        ],
        "examples": [
            ["Roadmap", "work", "2026-Q3", "in_progress",
             "#2563eb", "Draft + review", "Owner: me", "Ship Q3 release"],
            ["Garden cleanup", "personal", "2026-Q2", "not_started",
             "#16a34a", "Pull weeds, mulch beds", "", ""],
        ],
    },
}


@bp.get("/template/<kind>.xlsx")
@login_required
def download_template(email: str, kind: str):  # noqa: ARG001
    """#91 (2026-04-26): serve a pre-built .xlsx template for each import mode.

    Generated on the fly with openpyxl so headers always match the
    parsers in import_service.py. Each sheet has the header row in row 1
    plus 1-2 example rows the user can overwrite.
    """
    spec = _TEMPLATE_SHEETS.get(kind)
    if spec is None:
        abort(404)

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = kind.capitalize()
    ws.append(spec["headers"])
    for row in spec["examples"]:
        ws.append(row)

    # Best-effort column width — prevent truncation in Excel's preview.
    for col_idx, header in enumerate(spec["headers"], start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = max(
            14, len(header) + 2
        )

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=spec["filename"],
    )
