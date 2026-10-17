"""JSON API for the settings page.

Endpoints:
    GET /api/settings/status     — external service config status
    GET /api/settings/stats      — app-wide statistics
    GET /api/settings/imports    — import history log
    GET/POST /api/settings/voice-tokens, POST …/<jti>/revoke
                                 — #499 Siri voice-review token
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify

import voice_token_service
from auth import login_required
from rate_limit import VOICE_MINT_LIMIT, VOICE_MINT_LIMIT_MESSAGE, limiter
from settings_service import get_app_stats, get_import_history, get_service_status
from utils import ValidationError, optional_json_body

bp = Blueprint("settings_api", __name__, url_prefix="/api/settings")


@bp.get("/status")
@login_required
def status(email: str):  # noqa: ARG001
    """Return which external services are configured.

    Never reveals actual API key values — only whether they are set.
    """
    return jsonify(get_service_status())


@bp.get("/stats")
@login_required
def stats(email: str):  # noqa: ARG001
    """Return app-wide statistics (task/goal/recurring counts)."""
    return jsonify(get_app_stats())


@bp.get("/imports")
@login_required
def imports(email: str):  # noqa: ARG001
    """Return the import history log, newest first."""
    return jsonify(get_import_history())


# --- #499: the Siri voice-review token, made and revoked on the phone --------
# All three are @login_required. The validator cookie authenticates GET only
# (it can read the id list — ids and dates, never a token) and a voice-action
# bearer is never inspected by login_required, so neither can mint or revoke:
# minting a mutation credential needs a real Google sign-in (ADR-042).


@bp.get("/voice-tokens")
@login_required
def voice_tokens(email: str):  # noqa: ARG001
    """Tokens made on this page that haven't expired. Never the token."""
    return jsonify({"tokens": voice_token_service.list_tokens()})


@bp.post("/voice-tokens")
@login_required
@limiter.limit(VOICE_MINT_LIMIT, error_message=VOICE_MINT_LIMIT_MESSAGE)
@optional_json_body
def voice_token_mint(email: str):  # noqa: ARG001
    """Mint a voice-action token. The answer is the only time the token
    exists outside the Shortcut: not stored, not logged, not cached."""
    try:
        made = voice_token_service.mint_token(g.json_body.get("days"))
    except ValidationError as e:
        return jsonify({"error": str(e), "field": e.field}), 422
    resp = jsonify(made)
    resp.status_code = 201
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.post("/voice-tokens/<jti>/revoke")
@login_required
@limiter.limit("20 per minute")
def voice_token_revoke(email: str, jti: str):  # noqa: ARG001
    """Revoke one token by id — a listed one or a CLI-made one."""
    try:
        return jsonify(voice_token_service.revoke_token(jti))
    except ValidationError as e:
        return jsonify({"error": str(e), "field": e.field}), 422
