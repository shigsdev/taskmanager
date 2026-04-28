"""PR58 #121: OAuth MismatchingStateError → graceful redirect, not 500.

Background: Flask-Dance raises MismatchingStateError when the OAuth
callback's `state` doesn't match the session-stored state. Common
causes documented in errors.py.

Before PR58 the user got an "Internal Server Error" page with no
recovery path. Now they get a redirect to /login + a flash message
so the next click re-runs OAuth cleanly.
"""
from __future__ import annotations

from flask import Flask


def _make_test_app():
    """Spin up a minimal Flask app with the handlers registered.

    We don't go through create_app() because that boots the full DB +
    scheduler stack; we just need the error-handling layer.
    """
    from errors import register_error_handlers

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True

    # A canonical /login route the handler can url_for("login") to.
    @app.route("/login")
    def login():
        return "login page", 200

    # A route that always raises the OAuth state error — simulates
    # the Flask-Dance callback under a state-mismatch.
    @app.route("/trigger")
    def trigger():
        from oauthlib.oauth2.rfc6749.errors import MismatchingStateError
        raise MismatchingStateError()

    register_error_handlers(app)
    return app


def test_oauth_state_mismatch_redirects_to_login_not_500():
    app = _make_test_app()
    client = app.test_client()
    resp = client.get("/trigger")
    # Was 500, now 302 → /login. (302 because handler uses redirect().)
    assert resp.status_code == 302, (
        f"expected 302 redirect to /login, got {resp.status_code}"
    )
    assert "/login" in resp.headers["Location"]


def test_oauth_state_mismatch_does_not_leak_traceback():
    """Defense-in-depth: the redirect body must not contain the raw
    exception or traceback (sensitive context shouldn't end up in any
    response, even a 302's body)."""
    app = _make_test_app()
    client = app.test_client()
    resp = client.get("/trigger")
    body = resp.get_data(as_text=True)
    assert "MismatchingStateError" not in body
    assert "Traceback" not in body
    assert "oauthlib" not in body
