"""JSON API for projects. All routes require single-user auth."""
from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request

from auth import login_required
from models import Project, ProjectStatus, ProjectType  # noqa: F401
from project_service import (
    ValidationError,
    bulk_delete_projects,
    bulk_update_projects,
    create_project,
    delete_project,
    get_project,
    list_projects,
    reorder_projects,
    seed_default_projects,
    update_project,
)

bp = Blueprint("projects_api", __name__, url_prefix="/api/projects")


def _serialize(project: Project) -> dict:
    return {
        "id": str(project.id),
        "name": project.name,
        "type": project.type.value,
        "color": project.color,
        "target_quarter": project.target_quarter,
        "actions": project.actions,
        "notes": project.notes,
        "status": project.status.value,
        "goal_id": str(project.goal_id) if project.goal_id else None,
        "is_active": project.is_active,
        "priority_order": project.priority_order,
        "priority": project.priority.value if project.priority else None,
        "created_at": project.created_at.isoformat(),
    }


@bp.get("")
@login_required
def index(email: str):  # noqa: ARG001
    active_arg = request.args.get("is_active")
    if active_arg == "all":
        is_active = None
    elif active_arg is not None:
        is_active = active_arg.lower() in ("true", "1", "yes")
    else:
        is_active = True

    type_arg = request.args.get("type")
    project_type = None
    if type_arg is not None:
        try:
            project_type = ProjectType(type_arg)
        except ValueError:
            return jsonify({"error": f"invalid type: {type_arg}"}), 422

    projects = list_projects(is_active=is_active, project_type=project_type)
    return jsonify([_serialize(p) for p in projects])


@bp.post("")
@login_required
def create(email: str):  # noqa: ARG001
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    try:
        project = create_project(data)
    except ValidationError as e:
        return jsonify({"error": str(e), "field": e.field}), 422
    return jsonify(_serialize(project)), 201


@bp.get("/<uuid:project_id>")
@login_required
def show(email: str, project_id: uuid.UUID):  # noqa: ARG001
    project = get_project(project_id)
    if project is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize(project))


@bp.patch("/<uuid:project_id>")
@login_required
def patch(email: str, project_id: uuid.UUID):  # noqa: ARG001
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    try:
        project = update_project(project_id, data)
    except ValidationError as e:
        return jsonify({"error": str(e), "field": e.field}), 422
    if project is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize(project))


@bp.delete("/<uuid:project_id>")
@login_required
def destroy(email: str, project_id: uuid.UUID):  # noqa: ARG001
    if not delete_project(project_id):
        return jsonify({"error": "not found"}), 404
    return "", 204


@bp.post("/reorder")
@login_required
def reorder(email: str):  # noqa: ARG001
    """Bulk-update priority_order from a drag-and-drop reorder.

    Body: {"ordered_ids": ["uuid1", "uuid2", ...]} — full list within a
    single type group (work or personal), in the new top-to-bottom order.
    Each id gets `priority_order = index`. Other type's projects untouched.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    ids = data.get("ordered_ids")
    if not isinstance(ids, list):
        return jsonify({"error": "ordered_ids must be a list", "field": "ordered_ids"}), 422
    try:
        parsed = [uuid.UUID(s) for s in ids]
    except (TypeError, ValueError):
        return jsonify({
            "error": "every entry in ordered_ids must be a UUID",
            "field": "ordered_ids",
        }), 422
    updated = reorder_projects(parsed)
    return jsonify({"updated": updated}), 200


@bp.patch("/bulk")
@login_required
def bulk_update(email: str):  # noqa: ARG001
    """#90 (PR35): apply the same `updates` to multiple projects in
    one call. Mirrors /api/tasks/bulk semantics.

    Body: ``{"project_ids": [uuid, ...], "updates": {...}}``.
    Returns ``{"updated": N, "not_found": [...], "errors": [...]}``.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    ids_raw = data.get("project_ids")
    updates = data.get("updates")
    if not isinstance(ids_raw, list) or not ids_raw:
        return jsonify({"error": "project_ids must be a non-empty list"}), 422
    if not isinstance(updates, dict) or not updates:
        return jsonify({"error": "updates must be a non-empty dict"}), 422
    if len(ids_raw) > 200:
        return jsonify({
            "error": f"too many project_ids ({len(ids_raw)}); max 200 per call",
        }), 422
    parsed: list[uuid.UUID] = []
    for raw in ids_raw:
        try:
            parsed.append(uuid.UUID(str(raw)))
        except (ValueError, AttributeError):
            return jsonify({"error": f"invalid project_id: {raw!r}"}), 422
    return jsonify(bulk_update_projects(parsed, updates))


@bp.delete("/bulk")
@login_required
def bulk_delete(email: str):  # noqa: ARG001
    """#90 (PR35): bulk-archive (soft-delete) projects."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    ids_raw = data.get("project_ids")
    if not isinstance(ids_raw, list) or not ids_raw:
        return jsonify({"error": "project_ids must be a non-empty list"}), 422
    if len(ids_raw) > 200:
        return jsonify({
            "error": f"too many project_ids ({len(ids_raw)}); max 200 per call",
        }), 422
    parsed: list[uuid.UUID] = []
    for raw in ids_raw:
        try:
            parsed.append(uuid.UUID(str(raw)))
        except (ValueError, AttributeError):
            return jsonify({"error": f"invalid project_id: {raw!r}"}), 422
    return jsonify(bulk_delete_projects(parsed))


@bp.post("/seed")
@login_required
def seed(email: str):  # noqa: ARG001
    projects = seed_default_projects()
    return jsonify([_serialize(p) for p in projects]), 200
