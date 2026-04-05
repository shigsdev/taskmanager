"""Shared pytest fixtures."""
from __future__ import annotations

import pytest

import auth
from app import create_app
from models import db as _db


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
