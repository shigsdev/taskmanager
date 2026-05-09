"""JSON API for the Weekly Focus panel (Feature 1, 2026-05-09).

Endpoints:
    GET    /api/weekly-focus
        Returns the focus rows the panel should display today plus
        ``slot_count``. Carry-forward from the most recent past week
        when the current week has no rows yet.

    PATCH  /api/weekly-focus/<int:slot_order>
        Body: {"text": str, "goal_id": str | null}
        Upserts the slot for the current ISO week. Past weeks' rows
        are immutable — this endpoint only writes to the current week.

    DELETE /api/weekly-focus/<int:slot_order>
        Soft-clears the slot for the current ISO week (is_active=False).

    PATCH  /api/weekly-focus/settings/slot-count
        Body: {"slot_count": int}  (clamped to [1, 7])

    POST   /api/weekly-focus/<int:slot_order>/plan
        Runs Claude to propose changes (promote/demote/create_new) that
        align tasks with the slot's focus statement. Returns the
        validated change list — the client review modal applies them
        via existing PATCH /api/tasks/<id> + POST /api/tasks endpoints.
        Rate-limited (5/min, same as inbox-categorize / scan).

Mutations to TASKS are NEVER exposed here — the review modal routes
back through the canonical task surface so all the existing cascade
rules (auto-promote tier on due-today, etc.) still fire.
"""
from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request

from auth import login_required
from rate_limit import limiter
from weekly_focus_service import (
    clear_slot,
    get_displayed_focus,
    plan_for_focus,
    set_slot_count,
    upsert_slot,
)

bp = Blueprint("weekly_focus_api", __name__, url_prefix="/api/weekly-focus")


@bp.get("")
@login_required
def index(email: str):  # noqa: ARG001
    """Return the current displayed focus + slot count."""
    return jsonify(get_displayed_focus())


@bp.patch("/<int:slot_order>")
@login_required
def upsert(slot_order: int, email: str):  # noqa: ARG001
    """Upsert the text + optional goal link for a slot."""
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    goal_id_raw = data.get("goal_id")
    goal_id: uuid.UUID | None = None
    if goal_id_raw:
        try:
            goal_id = uuid.UUID(str(goal_id_raw))
        except (TypeError, ValueError):
            return jsonify({"error": "goal_id is not a valid UUID"}), 422
    try:
        upsert_slot(slot_order=slot_order, text=text or "", goal_id=goal_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    return jsonify(get_displayed_focus())


@bp.delete("/<int:slot_order>")
@login_required
def clear(slot_order: int, email: str):  # noqa: ARG001
    """Soft-clear the slot for the current ISO week."""
    cleared = clear_slot(slot_order)
    return jsonify({"cleared": cleared, **get_displayed_focus()})


@bp.patch("/settings/slot-count")
@login_required
def set_slots(email: str):  # noqa: ARG001
    """Update the configurable slot count (1-7)."""
    data = request.get_json(silent=True) or {}
    raw = data.get("slot_count")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return jsonify({"error": "slot_count must be an integer"}), 422
    n = set_slot_count(n)
    return jsonify({"slot_count": n})


@bp.post("/<int:slot_order>/plan")
@login_required
@limiter.limit("5 per minute")
def plan(slot_order: int, email: str):  # noqa: ARG001
    """Run the AI planner for this slot's focus statement.

    Returns ``{focus, linked_goal, changes: [...]}``. Mutations are NOT
    applied here — the client review modal commits via existing
    PATCH /api/tasks/<id> + POST /api/tasks endpoints.
    """
    try:
        result = plan_for_focus(slot_order)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify(result)
