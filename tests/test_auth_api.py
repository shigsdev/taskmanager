"""Tests for /api/auth/status — the post-deploy validation preflight endpoint.

Refreshed by #506 (2026-10-18, flagged stale by the tech-debt audit):
every test below was re-checked against ``auth_api.auth_status`` and still
describes it. ``scripts/validate_deploy.py`` reads exactly this contract —
200 with ``authenticated`` + ``email`` is green, 401 means "cookie
expired". The validator-cookie branch (``"via": "validator_cookie"``) is
covered in ``tests/test_validator_cookie.py``. Added: the Siri voice token
(ADR-034 / ADR-043) is NOT a sign-in here, and the route is read-only.
"""
from __future__ import annotations

import auth
import voice_action_token


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


def test_auth_status_ignores_the_voice_token(client, monkeypatch):
    """#506: the Siri voice token (ADR-034 / ADR-043) works only on
    /api/voice-review/*. A valid one must not make this endpoint report a
    sign-in, or a leaked token would look like a session."""
    monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
    token = voice_action_token.mint(secret_key="test-secret", email="me@example.com", days=90)
    resp = client.get("/api/auth/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.get_json() == {"authenticated": False}


def test_auth_status_is_read_only(client, monkeypatch):
    """#506: safe to poll — only GET is routed; a POST is refused."""
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
    assert client.post("/api/auth/status").status_code == 405
