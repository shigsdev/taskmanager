"""#282 Strength Forge — tracking API (Phase B.1: workout sessions).

All endpoints are ``@login_required`` (enforces ``AUTHORIZED_EMAIL``).
State-mutating routes are POST/DELETE only — never GET (a state-mutating
GET is a CSRF surface; SameSite=Lax doesn't block top-level GETs, #190).
Single-user app, so no per-user scoping.
"""
from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request

import strength_forge_service as svc
from auth import login_required

bp = Blueprint("strength_forge_api", __name__, url_prefix="/api/strength-forge")


@bp.get("/sessions")
@login_required
def list_sessions(email: str):  # noqa: ARG001
    """Recent logged workouts + this-week / all-time counts."""
    summary = svc.session_summary()
    summary["sessions"] = [svc.serialize(s) for s in svc.recent_sessions()]
    return jsonify(summary)


@bp.post("/sessions")
@login_required
def create_session(email: str):  # noqa: ARG001
    """Log a completed workout (dated today)."""
    data = request.get_json(silent=True) or {}
    plan_type = (data.get("plan_type") or "").strip()
    try:
        session = svc.log_session(plan_type)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    return jsonify(svc.serialize(session)), 201


@bp.delete("/sessions/<uuid:session_id>")
@login_required
def remove_session(email: str, session_id: uuid.UUID):  # noqa: ARG001
    """Undo a logged workout."""
    if not svc.delete_session(session_id):
        return jsonify({"error": "not found"}), 404
    return "", 204
