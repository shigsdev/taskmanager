"""Unit tests for the health check subsystem (``health.py``).

These exercise the individual check functions in isolation so failures
point straight at the broken check, not a vague 503 from /healthz.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import health

# --- check_database ----------------------------------------------------------


class TestCheckDatabase:
    def test_ok_when_select_works(self, app, db):
        with app.app_context():
            assert health.check_database(db) == "ok"

    def test_fail_when_session_raises(self):
        fake_db = MagicMock()
        fake_db.session.execute.side_effect = RuntimeError("connection lost")
        result = health.check_database(fake_db)
        assert result.startswith("fail:")
        assert "connection lost" in result


# --- check_env_vars ----------------------------------------------------------


class TestCheckEnvVars:
    def test_ok_in_testing_mode(self, app):
        # conftest sets TESTING=True and dummy Google creds
        assert health.check_env_vars(app) == "ok"

    def test_fail_when_google_client_missing(self, app, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        result = health.check_env_vars(app)
        assert "GOOGLE_CLIENT_ID" in result
        assert result.startswith("fail:")


# --- check_tables ------------------------------------------------------------


class TestCheckTables:
    def test_ok_when_all_tables_present(self, app, db):
        with app.app_context():
            assert health.check_tables(db) == "ok"

    def test_fail_when_expected_table_missing(self, app, db, monkeypatch):
        monkeypatch.setattr(
            health, "EXPECTED_TABLES", health.EXPECTED_TABLES | {"ghost_table"}
        )
        with app.app_context():
            result = health.check_tables(db)
        assert result.startswith("fail:")
        assert "ghost_table" in result


# --- check_writable_db -------------------------------------------------------


class TestCheckWritableDb:
    def test_ok_on_writable_db(self, app, db):
        with app.app_context():
            assert health.check_writable_db(db) == "ok"

    def test_warn_when_engine_broken(self):
        """An engine error is reported as warn, not fail — a health
        check bug should never block a deploy."""
        fake_db = MagicMock()
        fake_db.engine.begin.side_effect = RuntimeError("read-only")
        result = health.check_writable_db(fake_db)
        assert result.startswith("warn:")
        assert "read-only" in result


# --- check_encryption --------------------------------------------------------


class TestCheckEncryption:
    def test_ok_with_real_key(self, monkeypatch):
        from cryptography.fernet import Fernet

        import crypto

        monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
        crypto.reset()
        try:
            assert health.check_encryption() == "ok"
        finally:
            crypto.reset()

    def test_warn_without_key(self, monkeypatch):
        import crypto

        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        crypto.reset()
        try:
            result = health.check_encryption()
        finally:
            crypto.reset()
        assert result.startswith("warn:")


# --- check_digest ------------------------------------------------------------


class TestCheckDigest:
    def test_skipped_without_digest_email(self, monkeypatch):
        monkeypatch.delenv("DIGEST_TO_EMAIL", raising=False)
        assert health.check_digest().startswith("skipped")

    def test_warn_without_sendgrid_key(self, monkeypatch):
        monkeypatch.setenv("DIGEST_TO_EMAIL", "me@example.com")
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        result = health.check_digest()
        assert result.startswith("warn:")

    def test_warn_when_scheduler_not_registered(self, monkeypatch):
        monkeypatch.setenv("DIGEST_TO_EMAIL", "me@example.com")
        monkeypatch.setenv("SENDGRID_API_KEY", "fake")
        health._scheduler = None
        result = health.check_digest()
        assert result.startswith("warn:")
        assert "scheduler" in result.lower()

    def test_fail_when_scheduler_not_running(self, monkeypatch):
        monkeypatch.setenv("DIGEST_TO_EMAIL", "me@example.com")
        monkeypatch.setenv("SENDGRID_API_KEY", "fake")
        fake_scheduler = MagicMock()
        fake_scheduler.running = False
        health.register_scheduler(fake_scheduler)
        try:
            assert health.check_digest().startswith("fail:")
        finally:
            health._scheduler = None

    def test_fail_when_daily_digest_job_missing(self, monkeypatch):
        monkeypatch.setenv("DIGEST_TO_EMAIL", "me@example.com")
        monkeypatch.setenv("SENDGRID_API_KEY", "fake")
        fake_scheduler = MagicMock()
        fake_scheduler.running = True
        fake_scheduler.get_job.return_value = None
        health.register_scheduler(fake_scheduler)
        try:
            result = health.check_digest()
        finally:
            health._scheduler = None
        assert result.startswith("fail:")
        assert "daily_digest" in result

    def test_ok_with_live_scheduled_job(self, monkeypatch):
        import datetime as dt

        monkeypatch.setenv("DIGEST_TO_EMAIL", "me@example.com")
        monkeypatch.setenv("SENDGRID_API_KEY", "fake")
        fake_job = MagicMock()
        fake_job.next_run_time = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
        fake_scheduler = MagicMock()
        fake_scheduler.running = True
        fake_scheduler.get_job.return_value = fake_job
        health.register_scheduler(fake_scheduler)
        try:
            assert health.check_digest() == "ok"
        finally:
            health._scheduler = None


# --- check_static_assets -----------------------------------------------------


class TestCheckStaticAssets:
    def test_ok_when_all_assets_exist(self):
        assert health.check_static_assets() == "ok"

    def test_fail_when_asset_missing(self, monkeypatch):
        monkeypatch.setattr(
            health,
            "EXPECTED_STATIC_FILES",
            health.EXPECTED_STATIC_FILES + ("static/does_not_exist.js",),
        )
        result = health.check_static_assets()
        assert result.startswith("fail:")
        assert "does_not_exist" in result


# --- check_migrations --------------------------------------------------------


class TestCheckMigrations:
    def test_skipped_in_testing(self, app):
        assert health.check_migrations(app) == "skipped: testing"


# --- run_health_checks (integration) -----------------------------------------


class TestRunHealthChecks:
    def test_returns_all_expected_keys(self, app, db):
        with app.app_context():
            report = health.run_health_checks(app, db)
        assert "status" in report
        assert "git_sha" in report
        assert "started_at" in report
        assert "checks" in report
        for k in (
            "database",
            "env_vars",
            "migrations",
            "tables",
            "writable_db",
            "encryption",
            "digest",
            "static_assets",
        ):
            assert k in report["checks"]

    def test_status_ok_when_no_failures(self, app, db):
        with app.app_context():
            report = health.run_health_checks(app, db)
        # Should pass in the default test environment
        assert report["status"] == "ok"

    def test_git_sha_defaults_to_dev_without_env(self, app, db, monkeypatch):
        monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
        with app.app_context():
            report = health.run_health_checks(app, db)
        assert report["git_sha"] == "dev"

    def test_git_sha_reports_env_when_set(self, app, db, monkeypatch):
        monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "deadbeef")
        with app.app_context():
            report = health.run_health_checks(app, db)
        assert report["git_sha"] == "deadbeef"

    def test_status_fail_when_any_check_fails(self, app, db, monkeypatch):
        monkeypatch.setattr(
            health, "EXPECTED_TABLES", health.EXPECTED_TABLES | {"missing_table"}
        )
        with app.app_context():
            report = health.run_health_checks(app, db)
        assert report["status"] == "fail"
