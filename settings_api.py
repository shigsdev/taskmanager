"""JSON API for the settings page.

Endpoints:
    GET /api/settings/status     — external service config status
    GET /api/settings/stats      — app-wide statistics
    GET /api/settings/imports    — import history log
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from auth import login_required
from settings_service import get_app_stats, get_import_history, get_service_status

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
