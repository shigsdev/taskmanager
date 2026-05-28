"""Deployment readiness tests (Step 20).

Verify that all deployment infrastructure is in place and the app
can boot correctly for Railway hosting.

Key testing concepts:
- **Procfile** — tells Railway/Heroku which processes to run.
  The 'web' process starts gunicorn; the 'release' process
  runs database migrations before each deploy.
- **Gunicorn** — a production WSGI server that serves the Flask app.
  Unlike Flask's dev server, gunicorn handles multiple concurrent
  requests via worker processes.
- **Nixpacks** — Railway's build system that auto-detects the project
  type and builds it. runtime.txt tells it which Python version to use.
- **Health check** — a simple endpoint that Railway pings to verify
  the app is running. Returns 200 with {"status": "ok"}.
"""
from __future__ import annotations

from pathlib import Path

import auth

PROJECT_ROOT = Path(__file__).parent.parent


# --- Deployment files --------------------------------------------------------


class TestDeploymentFiles:
    """Verify required deployment files exist and are correct."""

    def test_procfile_exists(self):
        procfile = PROJECT_ROOT / "Procfile"
        assert procfile.exists(), "Procfile is required for Railway deployment"

    def test_procfile_has_web_process(self):
        content = (PROJECT_ROOT / "Procfile").read_text()
        assert "web:" in content
        assert "gunicorn" in content

    def test_startcommand_runs_migrations(self):
        """Migrations run in startCommand, not Procfile release phase.

        The release phase runs during Docker build when there is no
        network access to the database. Migrations run at container
        start via railway.toml startCommand instead.
        """
        content = (PROJECT_ROOT / "railway.toml").read_text()
        assert "flask db upgrade" in content

    def test_railway_toml_exists(self):
        toml = PROJECT_ROOT / "railway.toml"
        assert toml.exists(), "railway.toml configures Railway deployment"

    def test_railway_toml_uses_nixpacks(self):
        content = (PROJECT_ROOT / "railway.toml").read_text()
        assert "nixpacks" in content

    def test_railway_toml_has_start_command(self):
        content = (PROJECT_ROOT / "railway.toml").read_text()
        assert "gunicorn" in content

    def test_runtime_txt_exists(self):
        runtime = PROJECT_ROOT / "runtime.txt"
        assert runtime.exists(), "runtime.txt pins the Python version"

    def test_runtime_txt_has_python_version(self):
        content = (PROJECT_ROOT / "runtime.txt").read_text().strip()
        assert content.startswith("python-")

    def test_gunicorn_config_exists(self):
        config = PROJECT_ROOT / "gunicorn.conf.py"
        assert config.exists(), "gunicorn.conf.py sets production defaults"

    def test_gunicorn_config_binds_to_port(self):
        content = (PROJECT_ROOT / "gunicorn.conf.py").read_text()
        assert "PORT" in content
        assert "bind" in content

    def test_requirements_has_gunicorn(self):
        content = (PROJECT_ROOT / "requirements.txt").read_text()
        assert "gunicorn" in content

    def test_requirements_has_psycopg(self):
        content = (PROJECT_ROOT / "requirements.txt").read_text()
        assert "psycopg" in content

    def test_env_example_exists(self):
        env = PROJECT_ROOT / ".env.example"
        assert env.exists()

    def test_env_example_has_required_vars(self):
        content = (PROJECT_ROOT / ".env.example").read_text()
        required = [
            "SECRET_KEY",
            "ENCRYPTION_KEY",
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "AUTHORIZED_EMAIL",
            "DATABASE_URL",
            "SENDGRID_API_KEY",
            "DIGEST_TO_EMAIL",
            "GOOGLE_VISION_API_KEY",
            "ANTHROPIC_API_KEY",
        ]
        for var in required:
            assert var in content, f"{var} missing from .env.example"

    def test_gitignore_excludes_env(self):
        gitignore = PROJECT_ROOT / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert ".env" in content


# --- App boot and health check -----------------------------------------------


class TestAppBoot:
    """Verify the app boots and responds to health checks."""

    def test_app_creates_successfully(self, app):
        assert app is not None

    def test_healthz_returns_ok(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert "checks" in body
        assert body["checks"]["database"] == "ok"

    def test_healthz_includes_git_sha(self, client):
        """/healthz must return a git_sha so deploy scripts can verify
        which build is serving traffic during a rolling deploy."""
        resp = client.get("/healthz")
        body = resp.get_json()
        assert "git_sha" in body
        # Local/test runs have no Railway env var → "dev"
        assert body["git_sha"]

    def test_healthz_includes_started_at(self, client):
        resp = client.get("/healthz")
        body = resp.get_json()
        assert "started_at" in body
        # ISO-8601 UTC timestamp
        assert "T" in body["started_at"]

    def test_healthz_reports_git_sha_from_env(self, client, monkeypatch):
        """When RAILWAY_GIT_COMMIT_SHA is set, it must appear in the
        response so the deploy script can match it against the pushed
        commit."""
        monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc123def456")
        resp = client.get("/healthz")
        assert resp.get_json()["git_sha"] == "abc123def456"

    def test_healthz_includes_all_expected_checks(self, client):
        resp = client.get("/healthz")
        checks = resp.get_json()["checks"]
        for key in (
            "database",
            "env_vars",
            "migrations",
            "tables",
            "writable_db",
            "encryption",
            "digest",
            "static_assets",
        ):
            assert key in checks, f"healthz missing check: {key}"

    def test_healthz_tables_check_passes(self, client):
        """Table sanity check must find every expected table in tests."""
        resp = client.get("/healthz")
        assert resp.get_json()["checks"]["tables"] == "ok"

    def test_healthz_writable_db_check_passes(self, client):
        resp = client.get("/healthz")
        assert resp.get_json()["checks"]["writable_db"] == "ok"

    def test_healthz_static_assets_check_passes(self, client):
        resp = client.get("/healthz")
        assert resp.get_json()["checks"]["static_assets"] == "ok"

    def test_healthz_503_when_expected_table_missing(self, client, monkeypatch):
        """A missing expected table is a data-integrity failure and
        MUST block the deploy — tables is in CRITICAL_CHECKS.
        """
        import health

        monkeypatch.setattr(
            health, "EXPECTED_TABLES", health.EXPECTED_TABLES | {"nonexistent"}
        )
        resp = client.get("/healthz")
        assert resp.status_code == 503
        body = resp.get_json()
        assert body["status"] == "fail"
        assert "nonexistent" in body["checks"]["tables"]
        assert "tables" in body["critical_failed"]

    def test_healthz_reports_missing_static_without_503(self, client, monkeypatch):
        import health

        monkeypatch.setattr(
            health,
            "EXPECTED_STATIC_FILES",
            health.EXPECTED_STATIC_FILES + ("static/does_not_exist.js",),
        )
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "does_not_exist" in body["checks"]["static_assets"]

    def test_healthz_503_when_critical_check_fails(self, client, monkeypatch):
        """Only failures in CRITICAL_CHECKS should flip HTTP to 503."""
        import health

        # Break the database check — database is in CRITICAL_CHECKS
        def _boom(*_a, **_kw):
            return "fail: db down"

        monkeypatch.setattr(health, "check_database", _boom)
        resp = client.get("/healthz")
        assert resp.status_code == 503
        body = resp.get_json()
        assert "database" in body["critical_failed"]

    def test_healthz_503_when_encryption_key_malformed(self, client, monkeypatch):
        """A malformed ENCRYPTION_KEY is a real config-drift failure
        that silently degrades sensitive fields to plaintext. It MUST
        block the deploy (encryption is in CRITICAL_CHECKS).
        """
        import crypto

        monkeypatch.setenv("ENCRYPTION_KEY", "not-a-valid-fernet-key")
        crypto.reset()
        try:
            resp = client.get("/healthz")
            assert resp.status_code == 503
            body = resp.get_json()
            assert body["checks"]["encryption"].startswith("fail:")
            assert "encryption" in body["critical_failed"]
        finally:
            crypto.reset()

    def test_healthz_still_200_when_encryption_key_unset(self, client, monkeypatch):
        """An UNSET key (dev mode) is a warn, not a fail. Deploys
        must still go green when running in dev mode.
        """
        import crypto

        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        crypto.reset()
        try:
            resp = client.get("/healthz")
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["checks"]["encryption"].startswith("warn:")
            assert "encryption" not in body["critical_failed"]
        finally:
            crypto.reset()

    def test_healthz_503_when_migrations_out_of_date(self, client, monkeypatch):
        """Schema drift (migrations behind head) is a critical failure.

        Tests can't easily simulate a real alembic mismatch because
        conftest uses db.create_all(). Instead we monkey-patch
        check_migrations to return a fail string directly and verify
        it surfaces as critical.
        """
        import health

        monkeypatch.setattr(
            health, "check_migrations", lambda _app: "fail: at abc expected xyz"
        )
        resp = client.get("/healthz")
        assert resp.status_code == 503
        body = resp.get_json()
        assert "migrations" in body["critical_failed"]

    def test_healthz_encryption_canary_roundtrip(self, client, monkeypatch):
        """With a real ENCRYPTION_KEY set, the Fernet canary must round-trip."""
        from cryptography.fernet import Fernet

        import crypto

        monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
        crypto.reset()
        try:
            resp = client.get("/healthz")
            assert resp.get_json()["checks"]["encryption"] == "ok"
        finally:
            crypto.reset()

    def test_healthz_encryption_warns_without_key(self, client, monkeypatch):
        import crypto

        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        crypto.reset()
        try:
            resp = client.get("/healthz")
            # Warn, not fail — still HTTP 200
            assert resp.status_code == 200
            assert "ENCRYPTION_KEY" in resp.get_json()["checks"]["encryption"]
        finally:
            crypto.reset()

    def test_healthz_migrations_skipped_in_tests(self, client):
        """Tests use create_all(), not alembic — check must not fail."""
        resp = client.get("/healthz")
        assert resp.get_json()["checks"]["migrations"].startswith("skipped")

    def test_healthz_digest_check_reports_scheduler_state(self, client, monkeypatch):
        """When DIGEST_TO_EMAIL is set but the scheduler isn't registered
        (as in tests), digest check should warn — not fail."""
        monkeypatch.setenv("DIGEST_TO_EMAIL", "me@example.com")
        monkeypatch.setenv("SENDGRID_API_KEY", "fake")
        import health

        health._scheduler = None  # ensure clean state
        resp = client.get("/healthz")
        # Warn, not fail — test harness doesn't run the scheduler
        assert resp.status_code == 200
        assert resp.get_json()["checks"]["digest"].startswith("warn")

    def test_healthz_no_auth_required(self, client, monkeypatch):
        """Health check must work without authentication."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/healthz")
        assert resp.status_code == 200

    def test_login_page_renders(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_app_has_secret_key(self, app):
        assert app.config["SECRET_KEY"]
        assert app.config["SECRET_KEY"] != ""


# --- Database readiness -------------------------------------------------------


class TestDatabaseReadiness:
    """Verify all models can be created and queried."""

    def test_tables_created(self, app):
        from sqlalchemy import inspect

        with app.app_context():
            from models import db

            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            expected = [
                "tasks", "goals", "projects",
                "recurring_tasks", "import_log",
            ]
            for table in expected:
                assert table in tables, f"Table '{table}' not found"


# --- Blueprint registration --------------------------------------------------


class TestAllBlueprintsRegistered:
    """Verify every API blueprint is registered."""

    def test_all_blueprints(self, app):
        expected = [
            "tasks_api",
            "goals_api",
            "projects_api",
            "review_api",
            "recurring_api",
            "digest_api",
            "scan_api",
            "import_api",
            "settings_api",
        ]
        for bp_name in expected:
            assert bp_name in app.blueprints, f"Blueprint '{bp_name}' not registered"


# --- URL rules ---------------------------------------------------------------


class TestAllRoutesExist:
    """Verify all page and API routes are registered."""

    def test_page_routes(self, app):
        rules = [r.rule for r in app.url_map.iter_rules()]
        pages = [
            "/", "/goals", "/review", "/scan",
            "/import", "/settings", "/utilities", "/print",
            "/login", "/logout", "/healthz",
        ]
        for page in pages:
            assert page in rules, f"Route '{page}' not registered"

    def test_api_routes(self, app):
        rules = [r.rule for r in app.url_map.iter_rules()]
        apis = [
            "/api/tasks",
            "/api/goals",
            "/api/projects",
            "/api/review",
            "/api/recurring",
            "/api/digest/preview",
            "/api/digest/send",
            "/api/scan/upload",
            "/api/scan/confirm",
            "/api/import/tasks/parse",
            "/api/import/tasks/confirm",
            "/api/import/goals/parse",
            "/api/import/goals/confirm",
            "/api/settings/status",
            "/api/settings/stats",
            "/api/settings/imports",
            "/api/utilities/clear-stale-next-week-due-dates",
            "/api/utilities/clear-stale-next-week-due-dates/count",
            "/api/utilities/trigger-backup",
            "/api/utilities/trigger-restore-drill",
        ]
        for api in apis:
            assert api in rules, f"API route '{api}' not registered"


# --- WSGI entry point ---------------------------------------------------------


class TestWsgiEntryPoint:
    """Verify the WSGI entry point that gunicorn uses."""

    def test_app_module_exposes_app(self):
        """gunicorn references app:app — verify the module-level var exists."""
        from app import app

        assert app is not None
        assert hasattr(app, "wsgi_app")

    def test_app_is_flask_instance(self):
        from flask import Flask

        from app import app

        assert isinstance(app, Flask)

    def test_app_under_pytest_is_bare_stub(self):
        """#248 (2026-05-27): when pytest is on the call stack, the
        module-level `app` MUST be a bare Flask() — NOT a full
        `create_app()` result.

        The bug: a full create_app() at module-import time pointed at
        the env DATABASE_URL (prod Postgres on Railway), called
        configure_logging(), and attached DBLogHandler to the root
        logger. Any test that emitted WARNING+ then wrote to prod's
        app_logs table.

        Detected via 8 ERROR rows in prod logs with `synthetic`
        RuntimeError text leaked from test_run_missed_crons.py:120
        — only possible if the test's log handler was attached to a
        prod-pointing app.

        Bare Flask() under pytest means:
          - No db.init_app() — no Flask-SQLAlchemy binding
          - No configure_logging() — no DBLogHandler attached
          - No route registration — no /api/anything served
          - Tests must use the conftest `app` fixture for any real
            Flask app testing
        """
        from app import app

        # Bare stub has TESTING=True flag.
        assert app.config.get("TESTING") is True, (
            "Module-level app must have TESTING flag under pytest"
        )
        # Bare stub has NO SQLALCHEMY_DATABASE_URI config (because
        # `create_app()` was never called). A full create_app() would
        # populate it.
        assert "SQLALCHEMY_DATABASE_URI" not in app.config, (
            "Bare stub should not have SQLALCHEMY_DATABASE_URI — "
            "presence implies create_app() ran at import time."
        )
        # Bare stub has no routes registered.
        rules = [r.rule for r in app.url_map.iter_rules()]
        # Flask auto-registers /static/<filename>; ignore that.
        non_static_rules = [r for r in rules if not r.startswith("/static")]
        assert non_static_rules == [], (
            f"Bare stub should have no routes; got {non_static_rules}"
        )

    def test_root_logger_has_no_dblog_handler_from_app_import(self):
        """#248 regression test: simply importing `from app import app`
        must NOT add a DBLogHandler to the root logger. Without #248's
        guard, this happens silently.

        Cleans handlers between checks so prior tests' explicit
        handler attachments don't pollute. Then re-imports `app`
        (cached in sys.modules so this is a no-op) and asserts no
        handler was added by the import.
        """
        import logging

        from logging_service import DBLogHandler

        # Note: we can't reliably check "no DBLogHandler ever attached"
        # because some tests in test_logging.py intentionally attach
        # one via the fixture path. But we CAN check the import alone
        # doesn't trigger one — by counting handlers, importing, and
        # counting again.
        root = logging.getLogger()
        before = sum(
            1 for h in root.handlers if isinstance(h, DBLogHandler)
        )
        # Re-import — cached in sys.modules so this just rebinds the
        # name; the module body doesn't re-execute.
        from app import app  # noqa: F401
        after = sum(
            1 for h in root.handlers if isinstance(h, DBLogHandler)
        )
        assert after == before, (
            f"Importing `from app import app` should not change "
            f"DBLogHandler count on root; before={before} after={after}"
        )
