"""Tests for Google OAuth single-user lockdown."""
from __future__ import annotations

import pytest

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
    assert b"Task Manager" in resp.data


# --- /tier/<name> route (backlog #22) ----------------------------------------


@pytest.mark.parametrize("tier", ["inbox", "today", "this_week", "backlog", "freezer"])
def test_tier_detail_page_renders_for_each_valid_tier(client, monkeypatch, tier):
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
    resp = client.get(f"/tier/{tier}")
    assert resp.status_code == 200
    labels = {
        "inbox": b"Inbox",
        "today": b"Today",
        "this_week": b"This Week",
        "backlog": b"Backlog",
        "freezer": b"Freezer",
    }
    assert labels[tier] in resp.data


def test_tier_detail_page_404_for_invalid_tier(client, monkeypatch):
    """Unknown tier slug must 404 — prevents crafted URLs from reaching
    the template with an unsafe value."""
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
    resp = client.get("/tier/nonsense")
    assert resp.status_code == 404


def test_tier_detail_page_requires_login(client, monkeypatch):
    """Must go through login_required like every other data route."""
    monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
    resp = client.get("/tier/today")
    assert resp.status_code == 302
    assert "/login/google" in resp.headers.get("Location", "")


def test_tier_detail_page_validator_cookie_authenticates_get(app, client, monkeypatch):
    """Validator cookie (GET-only branch in login_required) should
    authenticate this page — it's a read-only render, no mutations."""
    import validator_cookie
    monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
    token = validator_cookie.mint(
        secret_key=app.config["SECRET_KEY"],
        email=app.config["AUTHORIZED_EMAIL"],
        days=30,
    )
    client.set_cookie(key=validator_cookie.COOKIE_NAME, value=token)
    resp = client.get("/tier/today")
    assert resp.status_code == 200


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
    assert resp.get_json()["status"] == "ok"


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


# --- Local dev bypass --------------------------------------------------------
#
# These tests verify the four-gate logic in auth._dev_bypass_active and
# the short-circuit at the top of login_required. Each gate is tested
# independently — the bypass must refuse to activate if ANY single gate
# fails. The Railway tripwire alone is checked three different ways
# (one test per RAILWAY_* var) so a future rename of one variable cannot
# silently regress the test coverage.


class TestDevBypassGates:
    """Verify _dev_bypass_active() respects all four gates."""

    def _set_all_gates_passing(self, monkeypatch):
        """Helper: set env so every gate passes; tests then break one gate."""
        monkeypatch.setenv("LOCAL_DEV_BYPASS_AUTH", "1")
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.setenv("AUTHORIZED_EMAIL", "me@example.com")
        for var in auth._RAILWAY_TRIPWIRE_VARS:
            monkeypatch.delenv(var, raising=False)

    def test_all_gates_pass_returns_true(self, monkeypatch):
        self._set_all_gates_passing(monkeypatch)
        assert auth._dev_bypass_active() is True

    def test_gate1_missing_opt_in_blocks(self, monkeypatch):
        self._set_all_gates_passing(monkeypatch)
        monkeypatch.delenv("LOCAL_DEV_BYPASS_AUTH", raising=False)
        assert auth._dev_bypass_active() is False

    def test_gate1_wrong_value_blocks(self, monkeypatch):
        """Only the literal string '1' enables the bypass — not 'true', 'yes', etc."""
        self._set_all_gates_passing(monkeypatch)
        for bad in ("0", "true", "yes", "True", " 1 ", ""):
            monkeypatch.setenv("LOCAL_DEV_BYPASS_AUTH", bad)
            assert auth._dev_bypass_active() is False, f"value {bad!r} should not enable"

    def test_gate2_flask_env_not_development_blocks(self, monkeypatch):
        self._set_all_gates_passing(monkeypatch)
        monkeypatch.setenv("FLASK_ENV", "production")
        assert auth._dev_bypass_active() is False

    def test_gate2_flask_env_unset_blocks(self, monkeypatch):
        self._set_all_gates_passing(monkeypatch)
        monkeypatch.delenv("FLASK_ENV", raising=False)
        assert auth._dev_bypass_active() is False

    def test_gate3_railway_project_id_blocks(self, monkeypatch):
        self._set_all_gates_passing(monkeypatch)
        monkeypatch.setenv("RAILWAY_PROJECT_ID", "abc123")
        assert auth._dev_bypass_active() is False

    def test_gate3_railway_environment_name_blocks(self, monkeypatch):
        self._set_all_gates_passing(monkeypatch)
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
        assert auth._dev_bypass_active() is False

    def test_gate3_railway_service_id_blocks(self, monkeypatch):
        self._set_all_gates_passing(monkeypatch)
        monkeypatch.setenv("RAILWAY_SERVICE_ID", "svc-xyz")
        assert auth._dev_bypass_active() is False

    def test_gate3_any_one_railway_var_is_enough(self, monkeypatch):
        """Even if only one tripwire is set, the bypass must refuse."""
        for var in auth._RAILWAY_TRIPWIRE_VARS:
            self._set_all_gates_passing(monkeypatch)
            monkeypatch.setenv(var, "anything")
            assert auth._dev_bypass_active() is False, f"{var} should trip"

    def test_gate4_authorized_email_unset_blocks(self, monkeypatch):
        self._set_all_gates_passing(monkeypatch)
        monkeypatch.delenv("AUTHORIZED_EMAIL", raising=False)
        assert auth._dev_bypass_active() is False


class TestDevBypassRequestFlow:
    """Verify the bypass short-circuit inside login_required works end-to-end."""

    def _enable_bypass(self, monkeypatch):
        monkeypatch.setenv("LOCAL_DEV_BYPASS_AUTH", "1")
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.setenv("AUTHORIZED_EMAIL", "me@example.com")
        for var in auth._RAILWAY_TRIPWIRE_VARS:
            monkeypatch.delenv(var, raising=False)

    def test_bypass_serves_protected_page_without_oauth(
        self, client, monkeypatch
    ):
        """When the bypass is active, protected pages render without an OAuth session."""
        self._enable_bypass(monkeypatch)
        # Force get_current_user_email to None — simulating "no OAuth session
        # at all". The bypass must serve the page anyway.
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Task Manager" in resp.data

    def test_bypass_inactive_falls_through_to_oauth(self, client, monkeypatch):
        """With the bypass disabled, login_required must redirect normally."""
        # Don't set the opt-in env var — bypass should NOT activate.
        monkeypatch.delenv("LOCAL_DEV_BYPASS_AUTH", raising=False)
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/")
        assert resp.status_code == 302
        assert "/login/google" in resp.headers["Location"]

    def test_bypass_emits_warning_log_per_request(
        self, client, monkeypatch, caplog
    ):
        """Every bypass-served request must log a WARNING for the audit trail."""
        import logging

        self._enable_bypass(monkeypatch)
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        with caplog.at_level(logging.WARNING, logger="taskmanager.auth"):
            client.get("/")
        # The exact message format is asserted to make sure the log row
        # captures method + path + email — those are the audit fields.
        bypass_logs = [
            r for r in caplog.records if "LOCAL_DEV_BYPASS_AUTH served" in r.message
        ]
        assert len(bypass_logs) >= 1
        assert "GET" in bypass_logs[0].message
        assert "me@example.com" in bypass_logs[0].message

    def test_bypass_does_not_leak_into_normal_session(
        self, client, monkeypatch
    ):
        """Disabling the bypass between requests must immediately re-lock the app."""
        # First request: bypass on
        self._enable_bypass(monkeypatch)
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/")
        assert resp.status_code == 200

        # Second request: bypass off — must redirect to OAuth
        monkeypatch.delenv("LOCAL_DEV_BYPASS_AUTH", raising=False)
        resp = client.get("/")
        assert resp.status_code == 302


class TestDevBypassStartupBanner:
    """Verify log_bypass_startup_banner prints loudly and writes to logs."""

    def test_no_banner_when_bypass_inactive(self, capsys, monkeypatch):
        monkeypatch.delenv("LOCAL_DEV_BYPASS_AUTH", raising=False)
        auth.log_bypass_startup_banner()
        captured = capsys.readouterr()
        assert "BYPASS" not in captured.err

    def test_banner_prints_when_bypass_active(self, capsys, monkeypatch):
        monkeypatch.setenv("LOCAL_DEV_BYPASS_AUTH", "1")
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.setenv("AUTHORIZED_EMAIL", "me@example.com")
        for var in auth._RAILWAY_TRIPWIRE_VARS:
            monkeypatch.delenv(var, raising=False)
        auth.log_bypass_startup_banner()
        captured = capsys.readouterr()
        assert "LOCAL_DEV_BYPASS_AUTH IS ACTIVE" in captured.err
        assert "me@example.com" in captured.err
        # All three tripwire names must be listed in the banner so the
        # user can see at-a-glance which checks passed.
        for var in auth._RAILWAY_TRIPWIRE_VARS:
            assert var in captured.err

    def test_banner_writes_warning_log(self, monkeypatch, caplog):
        import logging

        monkeypatch.setenv("LOCAL_DEV_BYPASS_AUTH", "1")
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.setenv("AUTHORIZED_EMAIL", "me@example.com")
        for var in auth._RAILWAY_TRIPWIRE_VARS:
            monkeypatch.delenv(var, raising=False)
        with caplog.at_level(logging.WARNING, logger="taskmanager.auth"):
            auth.log_bypass_startup_banner()
        startup_logs = [
            r for r in caplog.records
            if "startup banner" in r.message and "ACTIVE" in r.message
        ]
        assert len(startup_logs) == 1


class TestRunDevBypassScript:
    """Verify scripts/run_dev_bypass.py refuses to start in unsafe states."""

    def test_script_refuses_when_railway_var_set(self, monkeypatch, tmp_path):
        """Even if the user creates .env.dev-bypass on a Railway shell, refuse."""
        # Run the script's main() in-process. We can't use subprocess
        # because pytest-cov needs to track the run.
        import importlib.util

        script_path = (
            tmp_path.parent.parent.parent / "scripts" / "run_dev_bypass.py"
        )
        # Resolve relative to repo root for safety.
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        script_path = repo_root / "scripts" / "run_dev_bypass.py"
        spec = importlib.util.spec_from_file_location("run_dev_bypass", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        monkeypatch.setenv("RAILWAY_PROJECT_ID", "abc")
        result = module.main()
        assert result == 2

    def test_script_refuses_when_bypass_file_missing(self, monkeypatch, tmp_path):
        import importlib.util
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        script_path = repo_root / "scripts" / "run_dev_bypass.py"
        spec = importlib.util.spec_from_file_location("run_dev_bypass", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Clear all railway vars so we get past gate 1
        for var in ("RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_SERVICE_ID"):
            monkeypatch.delenv(var, raising=False)
        # Point the script at a non-existent file
        monkeypatch.setattr(module, "BYPASS_ENV_FILE", tmp_path / "nope.env")
        result = module.main()
        assert result == 2
