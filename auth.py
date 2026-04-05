"""Authentication helpers: single-user Google OAuth lockdown.

Every data route must go through ``login_required``. The decorator rejects
anyone whose Google email does not match the configured ``AUTHORIZED_EMAIL``.
"""
from __future__ import annotations

from functools import wraps

from flask import current_app, redirect, render_template, session, url_for
from flask_dance.contrib.google import google


def get_current_user_email() -> str | None:
    """Return the authenticated user's Google email, or None if not signed in.

    Kept as a module-level function so tests can monkeypatch it without
    needing a real OAuth flow.
    """
    if not google.authorized:
        return None
    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        return None
    return resp.json().get("email")


def login_required(view):
    """Enforce sign-in AND single-user lockdown on a Flask view."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        email = get_current_user_email()
        if email is None:
            return redirect(url_for("google.login"))
        authorized = (current_app.config.get("AUTHORIZED_EMAIL") or "").strip().lower()
        if not authorized or email.strip().lower() != authorized:
            session.clear()
            return render_template("unauthorized.html"), 403
        return view(*args, email=email, **kwargs)

    return wrapped
