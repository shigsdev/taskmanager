"""JSON API for triage suggestions (#12).

Endpoints:
    GET /api/triage/suggestions  — heuristic-based stale-task suggestions

Mutations are NOT exposed here on purpose — the user accepts a
suggestion by routing through the existing tier-change / delete
endpoints (PATCH /api/tasks/<id> or DELETE /api/tasks/<id>). That
keeps the audit trail unified and avoids a second mutation surface
that could drift from the canonical task-mutation rules.
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from auth import login_required
from triage_service import compute_triage_suggestions

bp = Blueprint("triage_api", __name__, url_prefix="/api/triage")


@bp.get("/suggestions")
@login_required
def suggestions(email: str):  # noqa: ARG001
    """Return heuristic triage suggestions for all active tasks."""
    return jsonify(compute_triage_suggestions())
