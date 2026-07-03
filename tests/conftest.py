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
def _reset_digest_heartbeat(monkeypatch, tmp_path):
    """Isolate the two process-global digest-check inputs per test.

    ``check_digest`` reads two module globals that several tests mutate:
      * ``health.HEARTBEAT_PATH`` — by default a SINGLE file in the shared
        system temp dir. Multiple tests writing/deleting it caused
        cross-test pollution under ``pytest-randomly`` AND intermittent
        Windows/OneDrive unlink/replace races. Point it at a UNIQUE
        per-test ``tmp_path`` file so no two tests ever touch the same
        heartbeat and there's no shared-file contention.
      * ``health._scheduler`` — set to a mock by scheduler tests; the
        heartbeat-fallback tests need it back at ``None``.
    Both are reset before AND after every test so ordering can't
    contaminate. (``monkeypatch.setattr`` auto-reverts HEARTBEAT_PATH.)
    """
    import health

    monkeypatch.setattr(health, "HEARTBEAT_PATH", tmp_path / "digest_heartbeat.json")
    health._scheduler = None
    yield
    health._scheduler = None


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
