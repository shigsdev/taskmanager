"""Tests for Google OAuth single-user lockdown."""
from __future__ import annotations

import auth


def test_index_unauthenticated_redirects_to_google_login(client, monkeypatch):
    monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login/google" in resp.headers["Location"]


def test_index_wrong_email_is_forbidden(client, monkeypatch):
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "intruder@example.com")
    resp = client.get("/")
    assert resp.status_code == 403
    assert b"Not authorized" in resp.data


def test_index_authorized_email_ok(client, monkeypatch):
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"me@example.com" in resp.data


def test_index_email_casing_is_normalized(client, monkeypatch):
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "ME@Example.COM")
    resp = client.get("/")
    assert resp.status_code == 200


def test_index_email_with_surrounding_whitespace_is_trimmed(client, monkeypatch):
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "  me@example.com  ")
    resp = client.get("/")
    assert resp.status_code == 200


def test_empty_authorized_email_rejects_everyone(app, client, monkeypatch):
    app.config["AUTHORIZED_EMAIL"] = ""
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
    resp = client.get("/")
    assert resp.status_code == 403


def test_login_page_renders(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"Sign in with Google" in resp.data


def test_logout_clears_session_and_redirects(client):
    with client.session_transaction() as sess:
        sess["something"] = "value"
    resp = client.get("/logout")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
    with client.session_transaction() as sess:
        assert "something" not in sess


def test_healthz_is_public(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_get_current_user_email_returns_none_when_not_authorized(app, monkeypatch):
    with app.test_request_context("/"):
        # flask-dance's `google` proxy reports authorized=False without a token
        monkeypatch.setattr("auth.google", type("G", (), {"authorized": False})())
        assert auth.get_current_user_email() is None


def test_get_current_user_email_returns_none_on_api_failure(app, monkeypatch):
    class FakeResp:
        ok = False

    class FakeGoogle:
        authorized = True

        def get(self, _url):
            return FakeResp()

    with app.test_request_context("/"):
        monkeypatch.setattr("auth.google", FakeGoogle())
        assert auth.get_current_user_email() is None


def test_get_current_user_email_returns_email_on_success(app, monkeypatch):
    class FakeResp:
        ok = True

        def json(self):
            return {"email": "me@example.com"}

    class FakeGoogle:
        authorized = True

        def get(self, _url):
            return FakeResp()

    with app.test_request_context("/"):
        monkeypatch.setattr("auth.google", FakeGoogle())
        assert auth.get_current_user_email() == "me@example.com"
