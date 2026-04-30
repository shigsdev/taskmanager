"""JSON API for the email digest.

Endpoints:
    POST /api/digest/send                   — send the digest email now
    GET  /api/digest/preview                — plain-text digest body (JSON)
    GET  /api/digest/preview?format=html    — rendered HTML digest (text/html)
"""
from __future__ import annotations

import os

from flask import Blueprint, Response, jsonify, request

from auth import login_required
from digest_service import build_digest, build_digest_html, send_digest

bp = Blueprint("digest_api", __name__, url_prefix="/api/digest")


@bp.get("/preview")
@login_required
def preview(email: str):  # noqa: ARG001
    """Preview the digest content without sending an email.

    Default returns the plain-text digest body as JSON. Pass
    ``?format=html`` to get the rendered HTML body served as
    ``text/html`` so it can be opened directly in a browser tab to
    QA the email layout before sending.
    """
    if request.args.get("format") == "html":
        return Response(build_digest_html(), mimetype="text/html")
    return jsonify({"body": build_digest()})


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

    # send_digest builds both HTML + plain-text bodies internally and
    # sends them as multipart/alternative. Raises EgressError on SendGrid
    # HTTP failure (#50, ADR-031) — the global error handler catches it
    # and returns JSON 502 with the actual SendGrid status + body.
    # Returns False only for the "no API key set" early-out path.
    ok = send_digest(to_email=to_email)
    if ok:
        return jsonify({"status": "sent"})
    return jsonify({
        "error": "SENDGRID_API_KEY env var is not set on this server",
    }), 422
