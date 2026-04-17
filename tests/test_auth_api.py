"""Tests for /api/auth/status — the post-deploy validation preflight endpoint."""
from __future__ import annotations

import auth


def test_auth_status_unauthenticated_returns_401(client, monkeypatch):
    """No session → 401 with {authenticated: false} — lets the validator
    script distinguish 'cookie expired' from 'deploy broken'."""
    monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
    resp = client.get("/api/auth/status")
    assert resp.status_code == 401
    data = resp.get_json()
    assert data == {"authenticated": False}


def test_auth_status_authorized_returns_200(client, monkeypatch):
    """Valid session for the authorized email → 200 with email echoed back."""
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["authenticated"] is True
    assert data["email"] == "me@example.com"
    assert data["bypass"] is False


def test_auth_status_wrong_email_returns_401(client, monkeypatch):
    """Valid Google session but wrong email → 401. Prevents a valid
    Google user from using this endpoint to confirm they *could* log
    into our app (single-user lockdown is preserved)."""
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "intruder@example.com")
    resp = client.get("/api/auth/status")
    assert resp.status_code == 401
    data = resp.get_json()
    assert data == {"authenticated": False}


def test_auth_status_email_casing_normalized(client, monkeypatch):
    """Same casing rules as login_required — mixed-case Google response
    must still match the configured AUTHORIZED_EMAIL."""
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "ME@Example.COM")
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200


def test_auth_status_empty_authorized_email_rejects_everyone(app, client, monkeypatch):
    """Misconfigured AUTHORIZED_EMAIL='' must refuse all logins even if
    Google reports a valid user — matches login_required behavior."""
    app.config["AUTHORIZED_EMAIL"] = ""
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
    resp = client.get("/api/auth/status")
    assert resp.status_code == 401


def test_auth_status_bypass_mode_reports_bypass_true(client, monkeypatch):
    """When the local dev bypass is active, report it explicitly so the
    validator / test harness can assert tripwires fired correctly."""
    monkeypatch.setattr(auth, "_dev_bypass_active", lambda: True)
    monkeypatch.setenv("AUTHORIZED_EMAIL", "bypass-user@example.com")
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["authenticated"] is True
    assert data["email"] == "bypass-user@example.com"
    assert data["bypass"] is True


def test_auth_status_is_json_content_type(client, monkeypatch):
    """Validator parses JSON — verify both success and failure responses
    are JSON, not HTML error pages."""
    monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
    resp = client.get("/api/auth/status")
    assert resp.content_type.startswith("application/json")

    monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
    resp = client.get("/api/auth/status")
    assert resp.content_type.startswith("application/json")
