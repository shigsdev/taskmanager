"""JSON API for the weekly review flow.

Endpoints:
    GET  /api/review       — list all stale tasks needing review
    POST /api/review/<id>  — apply a review action (keep/freeze/delete/snooze)
"""
from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request

from auth import login_required
from models import Task
from review_service import review_task, stale_tasks
from task_service import ValidationError, serialize_task

bp = Blueprint("review_api", __name__, url_prefix="/api/review")


def _serialize(task: Task) -> dict:
    """Thin wrapper over the canonical serializer (#200).

    Kept as a 1-liner so this module's call sites and any test patching
    ``review_api._serialize`` stay unaffected by the consolidation.
    """
    return serialize_task(task, view="review")


@bp.get("")
@login_required
def index(email: str):  # noqa: ARG001
    """Return all stale tasks that need review."""
    tasks = stale_tasks()
    return jsonify([_serialize(t) for t in tasks])


@bp.post("/<uuid:task_id>")
@login_required
def act(email: str, task_id: uuid.UUID):  # noqa: ARG001
    """Apply a review action to a task.

    Expects JSON body: {"action": "keep" | "freeze" | "delete" | "snooze"}
    """
    from models import db

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    action = data.get("action")
    if action not in ("keep", "freeze", "delete", "snooze"):
        return jsonify({"error": f"invalid action: {action!r}"}), 422

    task = db.session.get(Task, task_id)
    if task is None:
        return jsonify({"error": "not found"}), 404

    try:
        review_task(task, action)
    except (ValidationError, ValueError) as e:
        return jsonify({"error": str(e)}), 422

    return jsonify({"action": action, "task": _serialize(task)})
