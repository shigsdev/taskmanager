"""Shared pytest fixtures."""
from __future__ import annotations

import pytest

import auth
from app import create_app
from models import db as _db
from rate_limit import limiter as _limiter

# PR 9 (2026-05-21): rate limiting is a prod concern, exercised in prod
# — never in unit tests. The per-route `@limiter.limit` decorators are
# enforced under the test client even though `limiter.init_app` is
# skipped for TESTING apps (the decorator's own check fires regardless),
# AND the `RATELIMIT_ENABLED` config key is only consulted during
# `init_app` — which is skipped — so it can't disable enforcement here.
# Flipping the Limiter instance's `enabled` flag off is the one switch
# that the decorator path actually honours. Set once at import; the
# test process never wants live rate limiting. Without this a test
# class with more calls to one endpoint than its per-route limit
# flakes with a 429 (PR 9's tight "5 per minute" transcript limit hit
# this — TestTranscriptUploadAPI makes 7 calls).
_limiter.enabled = False


@pytest.fixture(autouse=True)
def _reset_digest_heartbeat():
    """Isolate the process-global digest heartbeat file.

    ``health.HEARTBEAT_PATH`` lives in the system temp dir, and several
    tests write a live-job heartbeat into it. Under ``pytest-randomly``'s
    per-run ordering, a file leaked by one test makes ``check_digest``'s
    heartbeat-fallback return a stale result for an unrelated later test
    (the digest check flaked on different tests across runs). Remove it
    before AND after every test so ordering can't cause contamination.
    The ``suppress(OSError)`` tolerates the Windows/OneDrive temp-unlink
    ``PermissionError`` documented in CLAUDE.md.
    """
    import contextlib

    import health

    with contextlib.suppress(OSError):
        health.HEARTBEAT_PATH.unlink(missing_ok=True)
    yield
    with contextlib.suppress(OSError):
        health.HEARTBEAT_PATH.unlink(missing_ok=True)


@pytest.fixture
def app(monkeypatch):
    # Dummy OAuth credentials so flask-dance registers cleanly; the real OAuth
    # flow is never executed in tests (we monkeypatch get_current_user_email).
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("OAUTHLIB_INSECURE_TRANSPORT", "1")
    monkeypatch.setenv("FLASK_ENV", "development")

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "AUTHORIZED_EMAIL": "me@example.com",
            "SESSION_COOKIE_SECURE": False,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        }
    )
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    return _db


@pytest.fixture
def authed_client(client, monkeypatch):
    """Client pre-authenticated as the authorized user."""
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
    return client
