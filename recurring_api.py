"""JSON API for recurring task templates.

Recurring tasks are templates that define tasks which should be auto-created
on certain days. This API manages the templates themselves (CRUD), plus
two special actions:

- **seed** — populates the default system recurring tasks (morning routine, etc.)
- **spawn** — creates actual Task records in Today tier from today's templates

Endpoints:
    GET    /api/recurring        — list all active recurring templates
    POST   /api/recurring        — create a new recurring template
    GET    /api/recurring/<id>   — get a single template
    PATCH  /api/recurring/<id>   — update a template
    DELETE /api/recurring/<id>   — disable (soft-delete) a template
    POST   /api/recurring/seed   — populate system defaults
    POST   /api/recurring/spawn  — create today's tasks from templates
"""
from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request

from auth import login_required
from models import RecurringTask
from recurring_service import (
    ValidationError,
    create_recurring,
    delete_recurring,
    get_recurring,
    list_recurring,
    seed_defaults,
    spawn_today_tasks,
    update_recurring,
)

bp = Blueprint("recurring_api", __name__, url_prefix="/api/recurring")


def _serialize(rt: RecurringTask) -> dict:
    return {
        "id": str(rt.id),
        "title": rt.title,
        "frequency": rt.frequency.value,
        "day_of_week": rt.day_of_week,
        "day_of_month": rt.day_of_month,
        "week_of_month": rt.week_of_month,
        "type": rt.type.value,
        "project_id": str(rt.project_id) if rt.project_id else None,
        "goal_id": str(rt.goal_id) if rt.goal_id else None,
        "notes": rt.notes,
        "checklist": rt.checklist or [],
        "url": rt.url,
        "subtasks_snapshot": rt.subtasks_snapshot or [],
        "is_active": rt.is_active,
        "created_at": rt.created_at.isoformat(),
    }


@bp.get("")
@login_required
def index(email: str):  # noqa: ARG001
    active_only = request.args.get("all") != "1"
    return jsonify([_serialize(rt) for rt in list_recurring(active_only=active_only)])


@bp.post("")
@login_required
def create(email: str):  # noqa: ARG001
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    try:
        rt = create_recurring(data)
    except ValidationError as e:
        return jsonify({"error": str(e), "field": e.field}), 422
    return jsonify(_serialize(rt)), 201


@bp.get("/<uuid:rt_id>")
@login_required
def show(email: str, rt_id: uuid.UUID):  # noqa: ARG001
    rt = get_recurring(rt_id)
    if rt is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize(rt))


@bp.patch("/<uuid:rt_id>")
@login_required
def patch(email: str, rt_id: uuid.UUID):  # noqa: ARG001
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    try:
        rt = update_recurring(rt_id, data)
    except ValidationError as e:
        return jsonify({"error": str(e), "field": e.field}), 422
    if rt is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize(rt))


@bp.delete("/<uuid:rt_id>")
@login_required
def destroy(email: str, rt_id: uuid.UUID):  # noqa: ARG001
    if not delete_recurring(rt_id):
        return jsonify({"error": "not found"}), 404
    return "", 204


@bp.post("/seed")
@login_required
def seed(email: str):  # noqa: ARG001
    """Populate system default recurring tasks."""
    created = seed_defaults()
    return jsonify({
        "created": len(created),
        "items": [_serialize(rt) for rt in created],
    }), 201


@bp.post("/spawn")
@login_required
def spawn(email: str):  # noqa: ARG001
    """Create today's tasks from recurring templates."""
    tasks = spawn_today_tasks()
    return jsonify({
        "spawned": len(tasks),
        "tasks": [
            {"id": str(t.id), "title": t.title, "tier": t.tier.value}
            for t in tasks
        ],
    }), 201
