"""JSON API for the weekly planner.

Endpoints:
    POST /api/planner/weekly
        Body: optional ``{"start_date": "YYYY-MM-DD"}``. Defaults to
        next Monday from today (per user workflow — plan ahead).
        Returns the structured plan from
        ``weekly_planner_service.compute_weekly_plan``.

    POST /api/planner/ignore/<task_id>
        Body: ``{"ignore": true | false}`` — toggles ``Task.planner_ignore``.
        Routes through models directly (not task_service.update_task)
        because update_task RESETS planner_ignore as a side effect of
        any meaningful field change. Setting the flag explicitly via
        this dedicated endpoint avoids that reset loop.

Mutations from accepted suggestions go through PATCH /api/tasks/<id>
in the existing tasks_api — same canonical surface as #PR88
auto-categorize.

Rate-limited 5/min like other LLM endpoints (per #124).
"""
from __future__ import annotations

import uuid
from datetime import date

from flask import Blueprint, jsonify, request

from auth import login_required
from models import Task, db
from rate_limit import limiter
from weekly_planner_service import compute_weekly_plan

bp = Blueprint("planner_api", __name__, url_prefix="/api/planner")


@bp.post("/weekly")
@login_required
@limiter.limit("5 per minute")
def weekly(email: str):  # noqa: ARG001
    """Generate a Mon–Sun plan for the requested week."""
    body = request.get_json(silent=True) or {}
    raw_start = body.get("start_date")
    start_date: date | None = None
    if raw_start:
        if not isinstance(raw_start, str):
            return jsonify({"error": "start_date must be an ISO date string"}), 422
        try:
            start_date = date.fromisoformat(raw_start)
        except ValueError:
            return jsonify({"error": f"start_date is not ISO format: {raw_start!r}"}), 422
        if start_date.weekday() != 0:
            return jsonify({
                "error": "start_date must be a Monday — plans cover Mon–Sun"
            }), 422

    try:
        plan = compute_weekly_plan(start_date=start_date)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify(plan)


@bp.post("/ignore/<uuid:task_id>")
@login_required
def toggle_ignore(email: str, task_id: uuid.UUID):  # noqa: ARG001
    """Set or clear ``Task.planner_ignore`` without touching other fields."""
    body = request.get_json(silent=True) or {}
    if "ignore" not in body:
        return jsonify({"error": "body must include 'ignore' boolean"}), 400
    flag = bool(body["ignore"])

    task = db.session.get(Task, task_id)
    if task is None:
        return jsonify({"error": "task not found"}), 404
    task.planner_ignore = flag
    db.session.commit()
    return jsonify({"task_id": str(task.id), "planner_ignore": task.planner_ignore})
