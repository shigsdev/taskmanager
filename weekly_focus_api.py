"""JSON API for the Weekly Focus panel (Feature 1, 2026-05-09).

Endpoints:
    GET    /api/weekly-focus[?week_offset=0|1]
        Returns the focus rows the panel should display + slot_count.
        week_offset=0 (default) = this week (with carry-forward fallback);
        week_offset=1 = next week (no carry-forward — blank if no rows).

    PATCH  /api/weekly-focus/<int:slot_order>[?week_offset=0|1]
        Body: {"text": str, "goal_id": str | null}
        Upserts the slot for the chosen week. Past weeks' rows
        are immutable — this endpoint only writes to this or next.

    DELETE /api/weekly-focus/<int:slot_order>[?week_offset=0|1]
        Soft-clears the slot for the chosen week (is_active=False).

    PATCH  /api/weekly-focus/settings/slot-count
        Body: {"slot_count": int}  (clamped to [1, 7])

    POST   /api/weekly-focus/<int:slot_order>/plan[?week_offset=0|1]
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
from rate_limit import LLM_HEAVY, limiter
from weekly_focus_service import (
    clear_slot,
    get_displayed_focus,
    plan_for_focus,
    set_slot_count,
    upsert_slot,
)

bp = Blueprint("weekly_focus_api", __name__, url_prefix="/api/weekly-focus")


def _parse_week_offset() -> int:
    """Read + validate the ?week_offset=0|1 query param. Defaults to 0
    on missing or malformed input — the panel must always render."""
    raw = request.args.get("week_offset", "0")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 0
    if n not in (0, 1):
        return 0
    return n


@bp.get("")
@login_required
def index(email: str):  # noqa: ARG001
    """Return the displayed focus + slot count for the requested week."""
    return jsonify(get_displayed_focus(week_offset=_parse_week_offset()))


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
    week_offset = _parse_week_offset()
    try:
        upsert_slot(
            slot_order=slot_order, text=text or "",
            goal_id=goal_id, week_offset=week_offset,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    return jsonify(get_displayed_focus(week_offset=week_offset))


@bp.delete("/<int:slot_order>")
@login_required
def clear(slot_order: int, email: str):  # noqa: ARG001
    """Soft-clear the slot for the requested week."""
    week_offset = _parse_week_offset()
    cleared = clear_slot(slot_order, week_offset=week_offset)
    return jsonify({
        "cleared": cleared,
        **get_displayed_focus(week_offset=week_offset),
    })


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
@limiter.limit(LLM_HEAVY)
def plan(slot_order: int, email: str):  # noqa: ARG001
    """Run the AI planner for this slot's focus statement.

    Returns ``{focus, linked_goal, changes: [...]}``. Mutations are NOT
    applied here — the client review modal commits via existing
    PATCH /api/tasks/<id> + POST /api/tasks endpoints.
    """
    week_offset = _parse_week_offset()
    try:
        result = plan_for_focus(slot_order, week_offset=week_offset)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify(result)
