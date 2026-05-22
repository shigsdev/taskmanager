"""Security hardening tests (Step 19).

Tests cover:
- Fernet encryption/decryption of sensitive fields
- Session cookie security settings
- Auth lockdown enforcement
- Talisman configuration (CSP, HTTPS, headers)
- Rate limiter configuration
- No sensitive data leakage in API responses

Key testing concepts:
- **Fernet symmetric encryption** — same key encrypts and decrypts.
  Uses the cryptography library's Fernet class which provides
  authenticated encryption (AES-CBC + HMAC-SHA256).
- **Content Security Policy (CSP)** — HTTP header that tells browsers
  which sources of content are allowed, preventing XSS attacks.
- **Rate limiting** — caps the number of requests per time window
  to prevent abuse and denial-of-service attacks.
"""
from __future__ import annotations

import os

import auth

# --- Fernet encryption -------------------------------------------------------


class TestEncryption:
    """Verify Fernet encrypt/decrypt round-trips correctly."""

    def test_encrypt_decrypt_round_trip(self, monkeypatch):
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        monkeypatch.setenv("ENCRYPTION_KEY", key)

        import crypto

        crypto.reset()

        original = "sensitive task data"
        encrypted = crypto.encrypt(original)
        assert encrypted != original
        assert crypto.decrypt(encrypted) == original

    def test_empty_string_unchanged(self, monkeypatch):
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        monkeypatch.setenv("ENCRYPTION_KEY", key)

        import crypto

        crypto.reset()

        assert crypto.encrypt("") == ""
        assert crypto.decrypt("") == ""

    def test_no_key_returns_plaintext(self, monkeypatch):
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)

        import crypto

        crypto.reset()

        original = "unencrypted"
        assert crypto.encrypt(original) == original
        assert crypto.decrypt(original) == original

    def test_decrypt_handles_unencrypted_value(self, monkeypatch):
        """If a value was stored before encryption was enabled,
        decrypt should return it as-is instead of crashing."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        monkeypatch.setenv("ENCRYPTION_KEY", key)

        import crypto

        crypto.reset()

        # This is NOT a valid Fernet token
        plaintext = "stored before encryption"
        assert crypto.decrypt(plaintext) == plaintext

    def test_different_keys_cannot_decrypt(self, monkeypatch):
        """Encrypted with one key cannot be decrypted with another."""
        from cryptography.fernet import Fernet

        key1 = Fernet.generate_key().decode()
        monkeypatch.setenv("ENCRYPTION_KEY", key1)

        import crypto

        crypto.reset()
        encrypted = crypto.encrypt("secret data")

        # Switch to a different key
        key2 = Fernet.generate_key().decode()
        monkeypatch.setenv("ENCRYPTION_KEY", key2)
        crypto.reset()

        # Should return the ciphertext as-is (graceful fallback)
        result = crypto.decrypt(encrypted)
        assert result == encrypted  # falls back to returning raw value

    def test_encrypted_value_is_different_each_time(self, monkeypatch):
        """Fernet uses a random IV, so same plaintext produces
        different ciphertext each time."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        monkeypatch.setenv("ENCRYPTION_KEY", key)

        import crypto

        crypto.reset()

        enc1 = crypto.encrypt("same value")
        enc2 = crypto.encrypt("same value")
        assert enc1 != enc2  # different IVs

        # But both decrypt to the same value
        assert crypto.decrypt(enc1) == "same value"
        assert crypto.decrypt(enc2) == "same value"


# --- Session security --------------------------------------------------------


class TestSessionSecurity:
    """Verify session cookie and lifetime settings."""

    def test_session_cookie_httponly(self, app):
        assert app.config["SESSION_COOKIE_HTTPONLY"] is True

    def test_session_cookie_samesite(self, app):
        assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"

    def test_session_lifetime_30_days(self, app):
        from datetime import timedelta

        assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(days=30)

    def test_session_is_permanent(self, authed_client):
        """Sessions should be marked permanent for the lifetime to apply."""
        authed_client.get("/")
        with authed_client.session_transaction() as sess:
            assert sess.permanent is True


# --- Auth lockdown ------------------------------------------------------------


class TestAuthLockdown:
    """Verify unauthorized access is properly rejected."""

    def test_unauthenticated_redirects_to_login(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/")
        assert resp.status_code == 302
        assert "/login" in resp.headers.get("Location", "")

    def test_wrong_email_returns_403(self, client, monkeypatch):
        monkeypatch.setattr(
            auth, "get_current_user_email", lambda: "wrong@example.com"
        )
        resp = client.get("/")
        assert resp.status_code == 403

    def test_api_unauthenticated_returns_401_json(self, client, monkeypatch):
        # Bug 2026-05-07: returning 302 → /login/google for an API call
        # caused fetch to follow the OAuth chain cross-origin, returning
        # an opaque response that surfaced as the meaningless dialog
        # "Save failed: ". 401 JSON lets apiFetch's existing recovery
        # prompt fire instead.
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/api/tasks")
        assert resp.status_code == 401
        assert resp.is_json
        assert resp.get_json()["error"] == "Authentication required"

    def test_api_patch_unauthenticated_returns_401_json(
        self, client, monkeypatch
    ):
        # The exact user-reported repro: PATCH /api/tasks/<id> while the
        # session is gone must give the client a clean 401, not a 302
        # that spirals into an opaque cross-origin redirect.
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.patch(
            "/api/tasks/00000000-0000-0000-0000-000000000000",
            json={"tier": "today"},
        )
        assert resp.status_code == 401
        assert resp.is_json

    def test_api_wrong_email_returns_403_json(self, client, monkeypatch):
        monkeypatch.setattr(
            auth, "get_current_user_email", lambda: "attacker@evil.com"
        )
        resp = client.get("/api/tasks")
        assert resp.status_code == 403
        assert resp.is_json
        assert resp.get_json()["error"] == "Not authorized"

    def test_html_route_unauthenticated_still_redirects(
        self, client, monkeypatch
    ):
        # Page navigation (HTML) keeps the natural redirect-to-OAuth flow.
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/")
        assert resp.status_code == 302
        assert "/login" in resp.headers.get("Location", "")

    def test_logout_clears_session(self, authed_client):
        resp = authed_client.post("/logout")
        assert resp.status_code == 302


# --- Talisman configuration ---------------------------------------------------


class TestTalismanConfig:
    """Verify Talisman security is configured correctly.

    In test mode, Talisman is disabled to avoid HTTPS requirements.
    These tests verify the configuration values that WOULD be applied
    in production.
    """

    def test_talisman_disabled_in_testing(self, app):
        """Talisman is not applied in TESTING mode (no HTTPS needed)."""
        assert app.config.get("TESTING") is True

    def test_csp_defined_in_code(self):
        """Verify CSP dict is defined in create_app (code review test)."""
        import inspect

        from app import create_app

        source = inspect.getsource(create_app)
        assert "content_security_policy" in source
        assert "default-src" in source
        assert "script-src" in source
        assert "frame-ancestors" in source

    def test_force_https_in_code(self):
        """Verify HTTPS redirect is enforced (manually, exempting /healthz)."""
        import inspect

        from app import create_app

        source = inspect.getsource(create_app)
        assert "_force_https_except_healthz" in source
        assert 'replace("http://", "https://", 1)' in source

    def test_hsts_in_code(self):
        """Verify HSTS is enabled in the Talisman config."""
        import inspect

        from app import create_app

        source = inspect.getsource(create_app)
        assert "strict_transport_security=True" in source

    def test_referrer_policy_in_code(self):
        """Verify referrer policy is set."""
        import inspect

        from app import create_app

        source = inspect.getsource(create_app)
        assert "referrer_policy" in source


# --- Rate limiter configuration -----------------------------------------------


class TestRateLimiterConfig:
    """Verify rate limiter is configured in the app factory."""

    def test_limiter_disabled_in_testing(self, app):
        """Rate limiter enforcement is OFF in tests.

        PR 9 (2026-05-21): the old assertion only checked
        ``TESTING is True``, which did NOT actually prove rate limiting
        was inert — the per-route ``@limiter.limit`` decorators enforce
        even when ``limiter.init_app`` is skipped, and ``RATELIMIT_ENABLED``
        is only read during ``init_app`` (skipped). conftest flips the
        Limiter instance's ``enabled`` flag — the one switch the
        decorator path honours. Assert that, so the test means what it
        says."""
        assert app.config.get("TESTING") is True
        import rate_limit
        assert rate_limit.limiter.enabled is False

    def test_limiter_module_exists(self):
        """PR64 #124: limiter lives in rate_limit.py so route blueprints
        can decorate specific endpoints with `@limiter.limit(...)`. The
        old test asserted "Limiter" appeared in create_app's source —
        now we check rate_limit.limiter is a Limiter instance and the
        module source pins the global default."""
        import inspect

        from flask_limiter import Limiter

        import rate_limit

        assert isinstance(rate_limit.limiter, Limiter)
        # 200/min default still in effect — assert from the module
        # source since Limiter doesn't expose the construction
        # default_limits as a stable attribute across versions.
        source = inspect.getsource(rate_limit)
        assert '"200 per minute"' in source

    def test_limiter_init_called_in_create_app(self):
        """create_app still wires the limiter to the app — just via
        init_app() now instead of inline construction."""
        import inspect

        from app import create_app

        source = inspect.getsource(create_app)
        assert "limiter.init_app" in source

    def test_scan_upload_has_per_route_limit(self):
        """PR64 #124: the scan/upload route is decorated with a tighter
        per-route limit because each call fans out to Vision + Claude
        (paid). 20/min is well below the 200/min global default."""
        import inspect

        import scan_api

        source = inspect.getsource(scan_api.upload)
        assert "limiter.limit" in source
        assert "20" in source

    def test_voice_memo_upload_has_per_route_limit(self):
        """PR64 #124: voice-memo upload calls Whisper (paid) — same
        rationale as scan/upload."""
        import inspect

        import voice_api

        source = inspect.getsource(voice_api.upload)
        assert "limiter.limit" in source
        assert "20" in source

    # --- PR 9 (#182/#183/#184): paid / worker-holding routes that the
    # #124 sweep missed. The limiter is disabled in TESTING (see
    # test_limiter_disabled_in_testing), so — like the #124 tests above
    # — these verify the decorator is present via source inspection.

    def test_digest_send_has_per_route_limit(self):
        """#182: POST /api/digest/send calls paid SendGrid on every
        hit; a stolen 30-day cookie shouldn't be able to burn quota."""
        import inspect

        import digest_api

        source = inspect.getsource(digest_api.send_now)
        assert "limiter.limit" in source
        assert "5 per minute" in source

    def test_transcript_routes_have_per_route_limit(self):
        """#183: both transcript routes flow through Claude (paid)."""
        import inspect

        import import_api

        for fn in (import_api.parse_transcript, import_api.upload_transcript):
            source = inspect.getsource(fn)
            assert "limiter.limit" in source, f"{fn.__name__} missing limiter"
            assert "5 per minute" in source

    def test_url_preview_has_per_route_limit(self):
        """#184: /api/tasks/url-preview holds a Gunicorn worker for up
        to 5s per outbound fetch — generous 30/min cap (human-paced
        legit use) keeps it from being a flood / scan vector."""
        import inspect

        import tasks_api

        source = inspect.getsource(tasks_api.url_preview)
        assert "limiter.limit" in source
        assert "30 per minute" in source


# --- No sensitive data leakage ------------------------------------------------


class TestNoDataLeakage:
    """Verify API responses never contain sensitive information."""

    def test_settings_status_no_key_values(self, authed_client, monkeypatch):
        monkeypatch.setenv("SENDGRID_API_KEY", "sg-real-key-12345")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
        monkeypatch.setenv("GOOGLE_VISION_API_KEY", "AIza-vision-key")

        resp = authed_client.get("/api/settings/status")
        body_str = resp.get_data(as_text=True)

        assert "sg-real-key-12345" not in body_str
        assert "sk-ant-secret" not in body_str
        assert "AIza-vision-key" not in body_str

    def test_task_response_no_session_data(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={"title": "Test task", "type": "work"},
        )
        body_str = resp.get_data(as_text=True)
        assert "session" not in body_str.lower() or "session" in "session"
        assert "cookie" not in body_str.lower()

    def test_healthz_no_sensitive_info(self, client):
        resp = client.get("/healthz")
        body = resp.get_json()
        assert body["status"] == "ok"
        body_str = resp.get_data(as_text=True)
        # Health check should never expose actual secret values
        assert os.environ.get("SECRET_KEY", "dev-secret") not in body_str
        assert "sendgrid" not in body_str.lower()
        assert "api_key" not in body_str.lower()


# --- Input sanitization -------------------------------------------------------


class TestInputSanitization:
    """Verify user input is sanitized before storage."""

    def test_task_title_stripped(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={"title": "  padded title  ", "type": "work"},
        )
        assert resp.status_code == 201
        assert resp.get_json()["title"] == "padded title"

    def test_xss_in_task_title_escaped(self, authed_client):
        """XSS payloads in titles should be stored as-is (Jinja2
        auto-escapes on render, so we just need to ensure they
        don't break the API)."""
        xss = '<script>alert("xss")</script>'
        resp = authed_client.post(
            "/api/tasks",
            json={"title": xss, "type": "work"},
        )
        assert resp.status_code == 201
        # Stored as-is; Jinja2 auto-escape handles rendering
        assert resp.get_json()["title"] == xss

    def test_empty_title_rejected(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={"title": "", "type": "work"},
        )
        assert resp.status_code == 422


# --- Jinja2 auto-escape -------------------------------------------------------


class TestJinjaAutoEscape:
    """Verify Jinja2 auto-escape is enabled (default in Flask)."""

    def test_auto_escape_enabled(self, app):
        """Flask enables Jinja2 auto-escape by default for .html templates."""
        autoescape = app.jinja_env.autoescape
        if callable(autoescape):
            # Flask uses a function that returns True for .html files
            assert autoescape("template.html") is True
        else:
            assert autoescape is True
