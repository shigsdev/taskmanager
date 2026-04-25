"""Global error handlers for the Flask app (#50).

Why this module exists
----------------------
Each route in the codebase catches the specific exceptions it expects
(``ValidationError``, "not found", JSON parse errors) and returns a
JSON response with a meaningful message. Anything outside that
expected set escapes the route, hits Flask's default exception
handling, and the user sees an opaque 500 with no JSON body — leaving
the frontend's ``apiFetch`` to fall back to an empty ``statusText``.
That's how bug #52 surfaced as "Save failed:" with a blank message
when the real error was ``psycopg.errors.InvalidTextRepresentation``,
and how bug #47 originally surfaced as a hardcoded "check
SENDGRID_API_KEY" string regardless of what SendGrid actually returned.

This module registers global Flask error handlers so EVERY uncaught
exception lands as a JSON response with:

- A useful (sanitized) error message
- The request_id so the user can correlate with server logs
- An appropriate HTTP status code

Specific exception types get specific handling. Unknown exceptions get
the safe-default 500 path.

Cross-reference ADR-031.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from flask import jsonify, request
from werkzeug.exceptions import HTTPException

if TYPE_CHECKING:
    from flask import Flask

logger = logging.getLogger(__name__)


def _request_id() -> str:
    """Pull the request_id stamped by logging_service onto the request
    context. Used as a correlation token in error responses so the user
    can find the matching server log row."""
    try:
        return getattr(request, "request_id", "") or ""
    except RuntimeError:
        # No active request context (shouldn't happen in handlers).
        return ""


def _is_api(path: str) -> bool:
    """Only API paths get JSON responses. HTML pages keep Flask's
    default error rendering — wrapping every HTML 500 in JSON would
    break the browser's default error page."""
    return path.startswith("/api/")


def register_error_handlers(app: Flask) -> None:
    """Wire all the handlers onto the app. Call from create_app() AFTER
    blueprints are registered so route-specific error handlers (if any)
    take precedence."""

    @app.errorhandler(HTTPException)
    def handle_http_exception(e: HTTPException) -> Any:
        """Werkzeug's HTTPException covers 4xx/5xx that the framework
        raises (404 for unknown routes, 405 for wrong method, 413 for
        oversize body, etc.). Preserve the original status; just shape
        the body as JSON for /api/ paths."""
        if not _is_api(request.path):
            return e  # default HTML page
        return jsonify({
            "error": e.description or e.name,
            "status": e.code,
            "request_id": _request_id(),
        }), e.code or 500

    @app.errorhandler(Exception)
    def handle_uncaught(e: Exception) -> Any:
        """Catch-all for everything else. Logs the full exception (with
        traceback) and returns a sanitized 500. The user sees something
        like "Server error: invalid value for enum projecttype: PERSONAL"
        instead of a blank message — bug #52's failure mode is gone."""
        # Log first, before deciding the user-facing message — this is
        # the source of truth for engineers debugging the failure.
        logger.exception("Unhandled exception in request")

        if not _is_api(request.path):
            # Let Flask's default 500 page render for HTML routes.
            # Re-raising would loop into this handler again; instead
            # return the canned HTTPException(500).
            from werkzeug.exceptions import InternalServerError
            return InternalServerError()

        # Distinguish a few common upstream causes by walking the
        # exception's class chain. Keeps the user-facing message useful
        # without leaking sensitive detail.
        msg = _shape_message(e)
        status = _classify_status(e)
        return jsonify({
            "error": msg,
            "type": type(e).__name__,
            "request_id": _request_id(),
        }), status


# --- Helpers ---------------------------------------------------------------


def _shape_message(e: Exception) -> str:
    """Produce a user-facing message for the given exception. The full
    traceback is already logged; this string is what the user sees in
    the alert / toast / dev-tools network tab.

    Specific types we know about:

    - ``EgressError`` (egress.safe_call_api wrapper): the message is
      already vendor + status + sanitized detail. Pass through.
    - ``sqlalchemy.exc.DataError``: usually wraps a Postgres data-type
      failure (e.g. invalid enum value — bug #52). Strip the SQL-context
      noise; surface the underlying psycopg message.
    - Anything else: ``"<TypeName>: <safe excerpt>"``. We do NOT include
      the full str(e) because it can include SQL fragments, file paths,
      or vendor query strings.
    """
    # EgressError already produces a clean message — pass through.
    type_name = type(e).__name__
    if type_name == "EgressError":
        return str(e)

    # SQLAlchemy DataError / IntegrityError / ProgrammingError — surface
    # the orig (the underlying psycopg error message), trimmed.
    orig = getattr(e, "orig", None)
    if orig is not None:
        # SQLAlchemy wraps the psycopg exception in `e.orig`. The
        # diagnostic message is usually the first line.
        first_line = str(orig).split("\n", 1)[0].strip()
        return f"Database error: {first_line[:200]}"

    # Default: short class + first 200 chars of message
    msg = str(e).split("\n", 1)[0].strip()[:200]
    if msg:
        return f"Server error: {msg}"
    return f"Server error ({type_name})"


def _classify_status(e: Exception) -> int:
    """Pick an HTTP status for the exception. Defaults to 500."""
    type_name = type(e).__name__

    # External-service failures map to 502 Bad Gateway — the request
    # was valid but a dependency we called failed.
    if type_name == "EgressError":
        return 502

    # SQLAlchemy data errors (invalid enum, constraint violations the
    # caller could have avoided) → 422 Unprocessable Entity.
    if type_name in {"DataError", "IntegrityError"}:
        return 422

    return 500
