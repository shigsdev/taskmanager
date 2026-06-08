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
    """Log a completed workout (dated today).

    Body ``{plan_type}`` logs a bare session (quick-log). An optional
    ``sets`` array — ``[{exercise_id, name, set_number, reps, resistance}]``
    — logs per-set detail (#287). Both paths are dated today.
    """
    data = request.get_json(silent=True) or {}
    plan_type = (data.get("plan_type") or "").strip()
    sets = data.get("sets")
    try:
        if isinstance(sets, list) and sets:
            session = svc.log_detailed_session(plan_type, sets)
        else:
            session = svc.log_session(plan_type)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    return jsonify(svc.serialize(session)), 201


@bp.get("/sessions/<uuid:session_id>")
@login_required
def get_session(email: str, session_id: uuid.UUID):  # noqa: ARG001
    """A single logged session plus its per-set detail."""
    detail = svc.session_detail(session_id)
    if detail is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(detail)


@bp.delete("/sessions/<uuid:session_id>")
@login_required
def remove_session(email: str, session_id: uuid.UUID):  # noqa: ARG001
    """Undo a logged workout."""
    if not svc.delete_session(session_id):
        return jsonify({"error": "not found"}), 404
    return "", 204


# --- Flare-up tracking (Phase B.2) ------------------------------------
@bp.get("/flare")
@login_required
def get_flare(email: str):  # noqa: ARG001
    """Current flare state (active episode + phase + day, or inactive)."""
    return jsonify(svc.flare_summary())


@bp.post("/flare")
@login_required
def start_flare(email: str):  # noqa: ARG001
    """Begin tracking a new flare (422 if one is already active)."""
    try:
        svc.start_flare()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    return jsonify(svc.flare_summary()), 201


@bp.patch("/flare")
@login_required
def update_flare(email: str):  # noqa: ARG001
    """Move the active flare to a protocol phase (body: {"phase": ...})."""
    data = request.get_json(silent=True) or {}
    phase = (data.get("phase") or "").strip()
    try:
        svc.set_flare_phase(phase)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    return jsonify(svc.flare_summary())


@bp.delete("/flare")
@login_required
def end_flare(email: str):  # noqa: ARG001
    """Mark the active flare resolved (404 if none active)."""
    if not svc.end_flare():
        return jsonify({"error": "no active flare"}), 404
    return "", 204
