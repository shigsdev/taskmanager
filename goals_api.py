"""JSON API for goals. All routes require single-user auth."""
from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request

from auth import login_required
from goal_service import (
    ValidationError,
    create_goal,
    delete_goal,
    get_goal,
    goal_progress,
    list_goals,
    update_goal,
)
from models import Goal, GoalCategory, GoalPriority, GoalStatus
from utils import enum_or_400 as _enum_or_400

bp = Blueprint("goals_api", __name__, url_prefix="/api/goals")


def _serialize(goal: Goal, *, include_progress: bool = True) -> dict:
    d = {
        "id": str(goal.id),
        "title": goal.title,
        "category": goal.category.value,
        "priority": goal.priority.value,
        "priority_rank": goal.priority_rank,
        "actions": goal.actions,
        "target_quarter": goal.target_quarter,
        "status": goal.status.value,
        "notes": goal.notes,
        "is_active": goal.is_active,
        "created_at": goal.created_at.isoformat(),
        "updated_at": goal.updated_at.isoformat(),
    }
    if include_progress:
        d["progress"] = goal_progress(goal.id)
    return d


@bp.get("")
@login_required
def index(email: str):  # noqa: ARG001
    category, err = _enum_or_400(GoalCategory, request.args.get("category"))
    if err:
        return err
    priority, err = _enum_or_400(GoalPriority, request.args.get("priority"))
    if err:
        return err
    status, err = _enum_or_400(GoalStatus, request.args.get("status"))
    if err:
        return err

    active_arg = request.args.get("is_active")
    if active_arg == "all":
        is_active = None
    elif active_arg is not None:
        is_active = active_arg.lower() in ("true", "1", "yes")
    else:
        is_active = True

    goals = list_goals(category=category, priority=priority, status=status, is_active=is_active)
    return jsonify([_serialize(g) for g in goals])


@bp.post("")
@login_required
def create(email: str):  # noqa: ARG001
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    try:
        goal = create_goal(data)
    except ValidationError as e:
        return jsonify({"error": str(e), "field": e.field}), 422
    return jsonify(_serialize(goal)), 201


@bp.get("/<uuid:goal_id>")
@login_required
def show(email: str, goal_id: uuid.UUID):  # noqa: ARG001
    goal = get_goal(goal_id)
    if goal is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize(goal))


@bp.patch("/<uuid:goal_id>")
@login_required
def patch(email: str, goal_id: uuid.UUID):  # noqa: ARG001
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    try:
        goal = update_goal(goal_id, data)
    except ValidationError as e:
        return jsonify({"error": str(e), "field": e.field}), 422
    if goal is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize(goal))


@bp.delete("/<uuid:goal_id>")
@login_required
def destroy(email: str, goal_id: uuid.UUID):  # noqa: ARG001
    if not delete_goal(goal_id):
        return jsonify({"error": "not found"}), 404
    return "", 204


@bp.get("/<uuid:goal_id>/progress")
@login_required
def progress(email: str, goal_id: uuid.UUID):  # noqa: ARG001
    goal = get_goal(goal_id)
    if goal is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(goal_progress(goal_id))
