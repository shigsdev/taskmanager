"""JSON API for the email digest.

Endpoints:
    POST /api/digest/send    — send the digest email now (manual trigger)
    GET  /api/digest/preview — preview the digest content without sending
"""
from __future__ import annotations

import os

from flask import Blueprint, jsonify

from auth import login_required
from digest_service import build_digest, send_digest

bp = Blueprint("digest_api", __name__, url_prefix="/api/digest")


@bp.get("/preview")
@login_required
def preview(email: str):  # noqa: ARG001
    """Preview the digest content without sending an email.

    Returns the plain-text digest body so the user can see what
    would be sent before triggering a real send.
    """
    body = build_digest()
    return jsonify({"body": body})


@bp.post("/send")
@login_required
def send_now(email: str):  # noqa: ARG001
    """Send the digest email immediately.

    Uses DIGEST_TO_EMAIL env var as the recipient. This is the user's
    work email address where the daily digest is delivered.
    """
    to_email = os.environ.get("DIGEST_TO_EMAIL")
    if not to_email:
        return jsonify({"error": "DIGEST_TO_EMAIL not configured"}), 422

    body = build_digest()
    ok = send_digest(to_email=to_email, body=body)

    if ok:
        return jsonify({"status": "sent", "to": to_email})
    return jsonify({"error": "Failed to send — check SENDGRID_API_KEY"}), 500
