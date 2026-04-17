"""Auth status API — lightweight endpoint for post-deploy validation.

Exposes a single public route that reports whether the caller's session
cookie is valid. Intended for use by ``scripts/validate_deploy.py`` to
distinguish "session cookie expired — please refresh it" from "deploy
is broken". Also consumed by the authenticated Playwright prod smoke
tests as a preflight check.

Why this endpoint exists
------------------------
Every other protected route either:
- redirects unauthenticated callers to ``/login/google`` (302), which
  Playwright auto-follows into Google's real OAuth pages — producing
  confusing "element not found" test failures instead of a clear signal,
  or
- renders ``unauthorized.html`` (403) which is an HTML page, not JSON.

``/api/auth/status`` is intentionally:

- PUBLIC (no ``login_required`` decorator). The endpoint itself returns
  the auth state of the caller; it doesn't need to reject unauthenticated
  requests — it reports on them.
- JSON-only. Clear machine-readable response for the validator script.
- Read-only and side-effect-free. Safe to poll.
- Minimal info disclosure. An unauthenticated caller learns that "an
  auth system exists" (already obvious from ``/login``) and nothing else.
  An authenticated caller gets their own email back, which they already
  know.
"""
from __future__ import annotations

import os

from flask import Blueprint, current_app, jsonify

import auth

bp = Blueprint("auth_api", __name__, url_prefix="/api/auth")


@bp.get("/status")
def auth_status():
    """Return whether the caller's session cookie is valid.

    Response shapes:

    - 200 OK (authenticated)::
        {
            "authenticated": true,
            "email": "shigsdev@gmail.com",
            "bypass": false
        }

    - 401 Unauthorized (no session or session expired)::
        {
            "authenticated": false
        }

    The ``bypass`` field is true when the local dev bypass is active,
    which is useful to verify the tripwire fired correctly in testing.
    """
    # Local dev bypass short-circuit — matches login_required's behavior
    # so the validator sees a consistent picture across dev and prod.
    if auth._dev_bypass_active():
        return jsonify({
            "authenticated": True,
            "email": os.environ["AUTHORIZED_EMAIL"],
            "bypass": True,
        })

    email = auth.get_current_user_email()
    if email is None:
        return jsonify({"authenticated": False}), 401

    # Enforce the same single-user lockdown as login_required — a valid
    # OAuth session for a *different* email must not report as
    # authenticated. Otherwise an intruder could use this endpoint to
    # confirm their Google login works against our app.
    authorized = (current_app.config.get("AUTHORIZED_EMAIL") or "").strip().lower()
    if not authorized or email.strip().lower() != authorized:
        return jsonify({"authenticated": False}), 401

    return jsonify({
        "authenticated": True,
        "email": email,
        "bypass": False,
    })
