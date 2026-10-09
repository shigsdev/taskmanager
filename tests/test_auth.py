"""Tests for Google OAuth single-user lockdown."""
from __future__ import annotations

import pytest
from flask import session
from oauthlib.oauth2.rfc6749.errors import TokenExpiredError

import auth


class _FakeResp:
    def __init__(self, ok, payload):
        self.ok = ok
        self._payload = payload

    def json(self):
        return self._payload


class TestGetCurrentUserEmailSessionCache:
    """Regression for the 2026-05-17 "logged out every 10-15 min" bug.

    The old code called Google's userinfo endpoint on EVERY request;
    the first call after Google's short-lived access token expired
    raised TokenExpiredError -> session.clear() -> forced re-login.
    The fix caches the verified email in the signed session and never
    re-hits Google for the life of the 30-day cookie.
    """

    def test_first_lookup_hits_google_and_caches(self, app, monkeypatch):
        calls = {"n": 0}

        class G:
            authorized = True

            def get(self, _path):
                calls["n"] += 1
                return _FakeResp(True, {"email": "me@example.com"})

        monkeypatch.setattr(auth, "google", G())
        with app.test_request_context("/"):
            assert auth.get_current_user_email() == "me@example.com"
            assert session[auth._SESSION_EMAIL_KEY] == "me@example.com"
        assert calls["n"] == 1

    def test_cached_email_short_circuits_without_calling_google(
        self, app, monkeypatch
    ):
        class G:
            authorized = True

            def get(self, _path):  # pragma: no cover - must NOT run
                raise AssertionError("Google must not be called when cached")

        monkeypatch.setattr(auth, "google", G())
        with app.test_request_context("/"):
            session[auth._SESSION_EMAIL_KEY] = "me@example.com"
            assert auth.get_current_user_email() == "me@example.com"

    def test_expired_token_with_cache_does_NOT_log_out(self, app, monkeypatch):
        """The actual bug: an expired Google token used to clear the
        session. With a cached email it must NOT — the user stays in."""

        class G:
            authorized = True

            def get(self, _path):  # pragma: no cover - must NOT run
                raise TokenExpiredError()

        monkeypatch.setattr(auth, "google", G())
        with app.test_request_context("/"):
            session[auth._SESSION_EMAIL_KEY] = "me@example.com"
            assert auth.get_current_user_email() == "me@example.com"
            assert auth._SESSION_EMAIL_KEY in session  # not cleared

    def test_expired_token_without_cache_clears_session(self, app, monkeypatch):
        class G:
            authorized = True

            def get(self, _path):
                raise TokenExpiredError()

        monkeypatch.setattr(auth, "google", G())
        with app.test_request_context("/"):
            session["something"] = "x"
            assert auth.get_current_user_email() is None
            assert "something" not in session  # session.clear() ran

    def test_unauthorized_when_not_signed_in_and_no_cache(
        self, app, monkeypatch
    ):
        class G:
            authorized = False

        monkeypatch.setattr(auth, "google", G())
        with app.test_request_context("/"):
            assert auth.get_current_user_email() is None


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


@pytest.mark.parametrize(
    "tier",
    ["inbox", "today", "tomorrow", "this_week", "next_week", "backlog", "freezer"],
)
def test_tier_detail_page_renders_for_each_valid_tier(client, monkeypatch, tier):
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
    resp = client.get(f"/tier/{tier}")
    assert resp.status_code == 200
    labels = {
        "inbox": b"Inbox",
        "today": b"Today",
        "tomorrow": b"Tomorrow",
        "this_week": b"This Week",
        "next_week": b"Next Week",
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
    # #185 (2026-05-21): logout is POST-only now.
    resp = client.post("/logout")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
    with client.session_transaction() as sess:
        assert "something" not in sess


def test_logout_get_is_rejected(client):
    """#185: a GET /logout must NOT clear the session — it was a
    state-mutating-GET CSRF surface (<img src=.../logout> logs you
    out). POST-only now → 405 Method Not Allowed."""
    resp = client.get("/logout")
    assert resp.status_code == 405


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

    @pytest.fixture(autouse=True)
    def _fresh_process(self, monkeypatch):
        """Each test starts as a newly booted server: no bypass request
        logged yet. monkeypatch restores the flag afterwards."""
        monkeypatch.setattr(auth, "_bypass_first_request_logged", False)

    @staticmethod
    def _served(records, level):
        return [
            r for r in records
            if r.levelno == level and "LOCAL_DEV_BYPASS_AUTH served" in r.getMessage()
        ]

    def test_first_bypass_request_logs_one_warning_with_audit_fields(
        self, client, monkeypatch, caplog
    ):
        """#384: the first bypass-served request in a process is the audit
        row (method + path + email), persisted at WARNING."""
        import logging

        self._enable_bypass(monkeypatch)
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        with caplog.at_level(logging.DEBUG, logger="taskmanager.auth"):
            client.get("/")
        warnings = self._served(caplog.records, logging.WARNING)
        assert len(warnings) == 1
        msg = warnings[0].getMessage()
        assert "GET /" in msg
        assert "me@example.com" in msg
        assert "DEBUG" in msg, "the row must say where the rest of the trail went"

    def test_later_bypass_requests_log_at_debug_only(
        self, client, monkeypatch, caplog
    ):
        """#384: every request after the first logs at DEBUG — below the
        DB handler's WARNING level — so a test run no longer writes a
        SQLite row per request (976 of 1,041 rows in one gate run)."""
        import logging

        self._enable_bypass(monkeypatch)
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        with caplog.at_level(logging.DEBUG, logger="taskmanager.auth"):
            client.get("/")
            client.get("/goals")
            client.get("/projects")
        assert len(self._served(caplog.records, logging.WARNING)) == 1
        debug = [r.getMessage() for r in self._served(caplog.records, logging.DEBUG)]
        assert any("GET /goals" in m for m in debug)
        assert any("GET /projects" in m for m in debug)

    def test_a_new_process_logs_its_first_request_again(
        self, client, monkeypatch, caplog
    ):
        """The flag is per process: a restarted server (flag back to False)
        records its first served request again."""
        import logging

        self._enable_bypass(monkeypatch)
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        with caplog.at_level(logging.DEBUG, logger="taskmanager.auth"):
            client.get("/")
            monkeypatch.setattr(auth, "_bypass_first_request_logged", False)
            client.get("/goals")
        warnings = self._served(caplog.records, logging.WARNING)
        assert [w.getMessage().split(" as ")[0] for w in warnings] == [
            "LOCAL_DEV_BYPASS_AUTH served GET /",
            "LOCAL_DEV_BYPASS_AUTH served GET /goals",
        ]

    def test_only_one_served_row_reaches_app_logs(self, app, client, monkeypatch):
        """End to end through a real DBLogHandler (WARNING, the default
        APP_LOG_LEVEL): three bypass-served requests persist ONE row."""
        import logging

        from logging_service import DBLogHandler, RequestContextFilter
        from models import AppLog

        self._enable_bypass(monkeypatch)
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        handler = DBLogHandler(app, level=logging.WARNING)
        handler.addFilter(RequestContextFilter())
        auth_logger = logging.getLogger("taskmanager.auth")
        auth_logger.addHandler(handler)
        old_level = auth_logger.level
        auth_logger.setLevel(logging.DEBUG)
        try:
            for path in ("/", "/goals", "/projects"):
                assert client.get(path).status_code == 200
        finally:
            auth_logger.removeHandler(handler)
            auth_logger.setLevel(old_level)
        with app.app_context():
            rows = AppLog.query.filter(
                AppLog.message.like("LOCAL_DEV_BYPASS_AUTH served%")
            ).all()
        assert len(rows) == 1
        assert rows[0].level == "WARNING"

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

    @staticmethod
    def _load_script_past_the_gates(monkeypatch, tmp_path):
        """Load run_dev_bypass.py with every startup gate satisfied, the real
        .env kept out, and every variable main() sets restored afterwards."""
        import importlib.util
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        script_path = repo_root / "scripts" / "run_dev_bypass.py"
        spec = importlib.util.spec_from_file_location("run_dev_bypass", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for var in ("RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_SERVICE_ID"):
            monkeypatch.delenv(var, raising=False)
        bypass_file = tmp_path / ".env.dev-bypass"
        bypass_file.write_text("LOCAL_DEV_BYPASS_AUTH=1\n", encoding="utf-8")
        monkeypatch.setattr(module, "BYPASS_ENV_FILE", bypass_file)
        monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
        monkeypatch.setenv("LOCAL_DEV_BYPASS_AUTH", "0")
        monkeypatch.setenv("FLASK_ENV", "testing")
        return module

    def test_script_turns_rate_limiting_off_before_the_server_starts(
        self, monkeypatch, tmp_path,
    ):
        """#385: the local bypass server is a test fixture every Playwright
        test shares from one IP, so prod's per-route limits (200/min default)
        tripped 429s once the suite ran ~2x faster. The script switches the
        shared limiter off before the app is imported and served (#403:
        by waitress, no longer `flask run`); prod is untouched (the app's own
        init path never runs this script)."""
        from rate_limit import limiter

        module = self._load_script_past_the_gates(monkeypatch, tmp_path)
        monkeypatch.setattr(limiter, "enabled", True)
        seen = {}
        monkeypatch.setattr(
            module, "_serve",
            lambda port: seen.update(enabled=limiter.enabled, port=port),
        )

        assert module.main(["--port", "5123"]) == 0
        assert seen == {"enabled": False, "port": 5123}

    def test_port_defaults_to_5111(self, monkeypatch, tmp_path):
        """`.claude/launch.json` starts the script with no arguments."""
        module = self._load_script_past_the_gates(monkeypatch, tmp_path)
        seen = {}
        monkeypatch.setattr(module, "_serve", lambda port: seen.update(port=port))

        assert module.main([]) == 0
        assert seen == {"port": 5111}

    def test_unknown_argument_is_refused_before_serving(self, monkeypatch, tmp_path):
        """#403: `flask run` accepted flags like --debug or --host; the
        waitress launcher does not, so it must say so instead of ignoring
        them (a silently ignored --host would bind somewhere unexpected)."""
        import pytest

        module = self._load_script_past_the_gates(monkeypatch, tmp_path)
        served = []
        monkeypatch.setattr(module, "_serve", lambda port: served.append(port))

        with pytest.raises(SystemExit) as exc:
            module.main(["--debug"])
        assert exc.value.code == 2
        assert served == []

    def test_server_reuses_one_connection_for_many_requests(self, monkeypatch, tmp_path):
        """#403: the whole point. Werkzeug's dev server closed every
        connection, so each request burned a loopback port into TIME_WAIT and
        8 Playwright lanes ran Windows out of ports (#402). The script's own
        server factory must serve back-to-back requests over ONE socket for
        the kinds of response the app sends: a page, JSON, a static file.
        (waitress does close after a chunked no-Content-Length response;
        nothing in this app streams, so Flask always sets the length.)"""
        import http.client
        import threading

        from flask import Flask, jsonify

        module = self._load_script_past_the_gates(monkeypatch, tmp_path)

        static = tmp_path / "static"
        static.mkdir()
        (static / "app.js").write_bytes(b"console.log(1);\n")
        flask_app = Flask(__name__, static_folder=str(static))
        flask_app.add_url_rule("/page", "page", lambda: "<h1>page</h1>")
        flask_app.add_url_rule("/api", "api", lambda: jsonify(ok=True))

        server = module._create_server(flask_app, port=0)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection(
                "127.0.0.1", server.effective_port, timeout=10,
            )
            conn.request("GET", "/page")
            assert conn.getresponse().read() == b"<h1>page</h1>"
            sock = conn.sock
            assert sock is not None, "server closed the connection after one request"
            for path, body in (
                ("/api", b'{"ok":true}\n'),
                ("/static/app.js", b"console.log(1);\n"),
                ("/page", b"<h1>page</h1>"),
            ):
                conn.request("GET", path)
                assert conn.getresponse().read() == body
                assert conn.sock is sock, f"{path} needed a new connection"
            conn.close()
        finally:
            server.close()
            thread.join(timeout=10)

    def test_server_binds_loopback_only(self, monkeypatch, tmp_path):
        """Same exposure as `flask run`'s default: never 0.0.0.0."""
        module = self._load_script_past_the_gates(monkeypatch, tmp_path)
        server = module._create_server(lambda e, s: [], port=0)
        try:
            assert server.effective_host == "127.0.0.1"
        finally:
            server.close()

    def test_rate_limit_switch_works_from_a_real_launch(self, tmp_path):
        """A real `python scripts/run_dev_bypass.py` has scripts/ — not the
        repo root — on sys.path, so `import rate_limit` failed there even
        though the in-process test above passed. Run the helper in a fresh
        interpreter from an unrelated cwd to cover that."""
        import subprocess
        import sys
        from pathlib import Path

        script_path = (
            Path(__file__).resolve().parent.parent / "scripts" / "run_dev_bypass.py"
        )
        code = (
            "import importlib.util, sys\n"
            f"spec = importlib.util.spec_from_file_location('rdb', {str(script_path)!r})\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "m._disable_rate_limiting()\n"
            "import rate_limit; print(rate_limit.limiter.enabled)\n"
        )
        env = {k: v for k, v in __import__("os").environ.items() if k != "PYTHONPATH"}
        result = subprocess.run(  # noqa: S603 — fixed interpreter + literal code
            [sys.executable, "-c", code],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "False"
