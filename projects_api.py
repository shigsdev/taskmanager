"""JSON API for projects. All routes require single-user auth."""
from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request

from auth import login_required
from models import Project
from project_service import (
    ValidationError,
    create_project,
    delete_project,
    get_project,
    list_projects,
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
        "goal_id": str(project.goal_id) if project.goal_id else None,
        "is_active": project.is_active,
        "sort_order": project.sort_order,
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

    projects = list_projects(is_active=is_active)
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


@bp.post("/seed")
@login_required
def seed(email: str):  # noqa: ARG001
    projects = seed_default_projects()
    return jsonify([_serialize(p) for p in projects]), 200
