"""Authentication helpers: single-user Google OAuth lockdown.

Every data route must go through ``login_required``. The decorator rejects
anyone whose Google email does not match the configured ``AUTHORIZED_EMAIL``.

Local dev bypass
----------------
The ``LOCAL_DEV_BYPASS_AUTH`` env var enables a short-circuit that lets the
agent (or a local browser) hit protected pages without completing real
Google OAuth — useful for headless preview testing of UI changes. The
bypass is gated by FOUR independent checks (see ``_dev_bypass_active``)
and refuses to activate if ANY of them fail. The Railway tripwire alone
checks three different RAILWAY_* variables, so a Railway env-var rename
cannot silently disarm it.

Every bypass-served request emits a WARNING log row to ``app_logs`` so
the developer can audit exactly which routes were touched while the
bypass was active. The startup banner (see ``log_bypass_startup_banner``)
prints to stderr on every Flask boot when the env var is set, so an
accidental "left it on in .env" mistake is impossible to miss.
"""
from __future__ import annotations

import logging
import os
import sys
from functools import wraps

from flask import current_app, redirect, render_template, request, session, url_for
from flask_dance.contrib.google import google
from oauthlib.oauth2.rfc6749.errors import TokenExpiredError

logger = logging.getLogger("taskmanager.auth")


# --- Local dev bypass --------------------------------------------------------
#
# Three independent Railway-injected variables that act as the "we are on
# Railway, refuse to bypass" tripwire. Listed individually so a Railway
# rename of any one of them cannot silently disarm the gate — they would
# have to rename all three at the same time.
_RAILWAY_TRIPWIRE_VARS = (
    "RAILWAY_PROJECT_ID",
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_SERVICE_ID",
)


def _dev_bypass_active() -> bool:
    """Return True if the local dev auth bypass is allowed to fire.

    All four gates must align — any single failure disables the bypass.
    Order matters only for clarity; every gate is independent.
    """
    # Gate 1: explicit opt-in env var. Must be exactly "1".
    if os.environ.get("LOCAL_DEV_BYPASS_AUTH") != "1":
        return False
    # Gate 2: Flask must be in development mode.
    if os.environ.get("FLASK_ENV") != "development":
        return False
    # Gate 3: refuse if ANY Railway-injected variable is present.
    if any(os.environ.get(var) for var in _RAILWAY_TRIPWIRE_VARS):
        return False
    # Gate 4: AUTHORIZED_EMAIL must be set so we know who to log in as.
    return bool(os.environ.get("AUTHORIZED_EMAIL"))


def log_bypass_startup_banner() -> None:
    """Print a loud banner to stderr if the bypass is active at startup.

    Called once from ``create_app`` after env vars are loaded. The banner
    is intentionally noisy — if you ever start Flask and see this when
    you didn't expect to, you have a misconfigured ``.env``.

    Also writes a WARNING row to the persistent app_logs table (if
    logging is configured by the time this runs) so the bypass start is
    recorded in the same audit trail as bypass-served requests.
    """
    if not _dev_bypass_active():
        return

    email = os.environ.get("AUTHORIZED_EMAIL", "(unset)")
    tripwire_status = "\n".join(
        f"    {var:25} {'set ✗' if os.environ.get(var) else 'not set ✓'}"
        for var in _RAILWAY_TRIPWIRE_VARS
    )
    banner = (
        "================================================================\n"
        "  ⚠  LOCAL_DEV_BYPASS_AUTH IS ACTIVE  ⚠\n"
        "  All auth checks are disabled. You are logged in as:\n"
        f"    {email}\n"
        "  This must NEVER be set on Railway. Tripwires verified:\n"
        f"{tripwire_status}\n"
        "  Bypass will remain active until this server stops.\n"
        "================================================================\n"
    )
    sys.stderr.write(banner)
    sys.stderr.flush()
    # Also persist to app_logs so the start of every bypass session is
    # captured in the same audit trail as the per-request bypass logs.
    logger.warning(
        "LOCAL_DEV_BYPASS_AUTH startup banner: bypass is ACTIVE for %s",
        email,
    )


def get_current_user_email() -> str | None:
    """Return the authenticated user's Google email, or None if not signed in.

    Kept as a module-level function so tests can monkeypatch it without
    needing a real OAuth flow.

    Returns None (triggering a login redirect) when the OAuth token has
    expired rather than letting the TokenExpiredError bubble up as a 500.
    """
    if not google.authorized:
        return None
    try:
        resp = google.get("/oauth2/v2/userinfo")
    except TokenExpiredError:
        session.clear()
        return None
    if not resp.ok:
        return None
    return resp.json().get("email")


# HTTP methods on which the validator cookie is allowed to authenticate.
# Keeping mutations (POST/PATCH/DELETE/PUT) behind real OAuth means a
# leaked validator cookie cannot create, modify, or delete user data —
# only read it. This is the security boundary that lets us widen the
# cookie's scope from "just /api/auth/status" to "all GET routes".
_VALIDATOR_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def login_required(view):
    """Enforce sign-in AND single-user lockdown on a Flask view.

    Authentication paths (in priority order):

    1. ``_dev_bypass_active()`` — local dev only, short-circuits all
       checks. See module docstring.
    2. Validator cookie (``validator_token``) on safe HTTP methods —
       authenticates GET/HEAD/OPTIONS so post-deploy automation can
       drive page-rendering smoke tests without an OAuth session.
       Mutation methods (POST/PATCH/DELETE/PUT) skip this path so a
       leaked validator cookie cannot modify data.
    3. Standard Google OAuth via Flask-Dance — the production user
       path; required for any non-safe method.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        # --- Local dev bypass short-circuit (see module docstring) ---
        if _dev_bypass_active():
            email = os.environ["AUTHORIZED_EMAIL"]
            try:
                method = request.method
                path = request.path
            except RuntimeError:
                method, path = "?", "?"
            logger.warning(
                "LOCAL_DEV_BYPASS_AUTH served %s %s as %s",
                method,
                path,
                email,
            )
            return view(*args, email=email, **kwargs)

        # --- Validator cookie path (read-only) ---
        # Imported here to avoid circular imports; validator_cookie
        # imports nothing from auth so a top-level import is also safe,
        # but the local import keeps the auth module's import surface
        # narrow.
        if request.method in _VALIDATOR_SAFE_METHODS:
            import validator_cookie

            authorized = (
                current_app.config.get("AUTHORIZED_EMAIL") or ""
            ).strip().lower()
            token = request.cookies.get(validator_cookie.COOKIE_NAME)
            if token and authorized:
                secret = current_app.config.get("SECRET_KEY") or ""
                validator_email = validator_cookie.parse(
                    secret_key=secret,
                    token=token,
                    authorized_email=authorized,
                )
                if validator_email:
                    # Audit: every validator-cookie-served request leaves
                    # a trace so a leaked cookie's usage is observable in
                    # /api/debug/logs. INFO level keeps it out of the
                    # default WARNING+ feed but available on demand.
                    logger.info(
                        "validator_cookie served %s %s as %s",
                        request.method,
                        request.path,
                        validator_email,
                    )
                    return view(*args, email=validator_email, **kwargs)

        email = get_current_user_email()
        if email is None:
            return redirect(url_for("google.login"))
        authorized = (current_app.config.get("AUTHORIZED_EMAIL") or "").strip().lower()
        if not authorized or email.strip().lower() != authorized:
            session.clear()
            return render_template("unauthorized.html"), 403
        return view(*args, email=email, **kwargs)

    return wrapped
