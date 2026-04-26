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
    compute_previews_in_range,
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
        "days_of_week": rt.days_of_week,
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


@bp.patch("/bulk")
@login_required
def bulk_patch(email: str):  # noqa: ARG001
    """#63 (2026-04-26): bulk-update multiple recurring templates.

    Body: ``{"template_ids": [uuid, ...], "updates": {field: value, ...}}``

    Allowed updates: type, frequency, project_id, goal_id, is_active,
    days_of_week (#75). Per-template `update_recurring` enforces the
    same validation as the single-PATCH endpoint, so a bad value on
    any template returns the SAME error and aborts the whole batch
    (caller is making a deliberate same-value-everywhere change).

    Returns ``{"updated": N, "errors": [{"id": uuid, "error": ...}]}``.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    ids = data.get("template_ids")
    updates = data.get("updates")
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "template_ids must be a non-empty list"}), 422
    if not isinstance(updates, dict) or not updates:
        return jsonify({"error": "updates must be a non-empty dict"}), 422
    try:
        parsed_ids = [uuid.UUID(s) for s in ids]
    except (TypeError, ValueError):
        return jsonify({"error": "every entry in template_ids must be a UUID"}), 422

    updated = 0
    errors: list[dict] = []
    for rid in parsed_ids:
        try:
            rt = update_recurring(rid, dict(updates))
            if rt is None:
                errors.append({"id": str(rid), "error": "not found"})
            else:
                updated += 1
        except ValidationError as e:
            errors.append({"id": str(rid), "error": str(e), "field": e.field})
    return jsonify({"updated": updated, "errors": errors}), 200


@bp.delete("/bulk")
@login_required
def bulk_delete(email: str):  # noqa: ARG001
    """#63: bulk-delete (soft) recurring templates."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    ids = data.get("template_ids")
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "template_ids must be a non-empty list"}), 422
    try:
        parsed_ids = [uuid.UUID(s) for s in ids]
    except (TypeError, ValueError):
        return jsonify({"error": "every entry in template_ids must be a UUID"}), 422
    deleted = 0
    not_found = 0
    for rid in parsed_ids:
        if delete_recurring(rid):
            deleted += 1
        else:
            not_found += 1
    return jsonify({"deleted": deleted, "not_found": not_found}), 200


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


@bp.get("/previews")
@login_required
def previews(email: str):  # noqa: ARG001
    """Return per-day preview instances for active templates firing in
    a date range (backlog #32).

    Query params (both required, ISO YYYY-MM-DD):
      - ``start``: inclusive first day of the range
      - ``end``:   inclusive last day of the range

    The client uses this to render "upcoming" cards inside the This
    Week / Next Week panels alongside real Tasks. Preview cards do
    NOT have a Task row yet — they're computed on the fly here and
    materialised only when ``spawn_today_tasks`` runs on the fire day.

    Response shape: ``[{template_id, title, type, frequency,
    project_id, goal_id, fire_date, notes, url}, ...]`` —
    newest-fire-date first within each day is stable-sorted because
    the service iterates days in order.
    """
    from datetime import date as _date

    start_raw = request.args.get("start")
    end_raw = request.args.get("end")
    if not start_raw or not end_raw:
        return jsonify({"error": "start and end query params required"}), 400
    try:
        start_d = _date.fromisoformat(start_raw)
        end_d = _date.fromisoformat(end_raw)
    except ValueError:
        return jsonify({"error": "start/end must be YYYY-MM-DD"}), 400

    # Cap range to 31 days so nobody requests a year-long sweep.
    if (end_d - start_d).days > 31:
        return jsonify({"error": "range cannot exceed 31 days"}), 400

    return jsonify(compute_previews_in_range(start=start_d, end=end_d))
