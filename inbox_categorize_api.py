"""JSON API for one-click inbox auto-categorization.

Endpoint:
    POST /api/inbox/categorize
        Returns: {count, capped, suggestions: [...]}
        Cost:    ~$0.001 per call (Haiku)
        Cap:     50 inbox tasks per call (capped flag tells the UI to
                 prompt the user to run again if there's more)

Mutations are NOT exposed here — the user reviews the returned
suggestions and applies them by routing through the canonical
PATCH /api/tasks/<id> endpoint. Same pattern as #12 triage_api.

Heavily rate-limited (5/min) because each call hits the LLM. Same
budget as /api/scan/upload + /api/voice-memo (per #124).
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from auth import login_required
from inbox_categorize_service import categorize_inbox
from rate_limit import limiter

bp = Blueprint("inbox_categorize_api", __name__, url_prefix="/api/inbox")


@bp.post("/categorize")
@login_required
@limiter.limit("5 per minute")
def categorize(email: str):  # noqa: ARG001
    """Run the auto-categorize pass on the user's INBOX tasks."""
    try:
        result = categorize_inbox()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify(result)
