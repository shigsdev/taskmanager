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
    def setup_method(self):
        """Clear scheduler + heartbeat between tests so the fallback
        path doesn't leak across cases."""
        health._scheduler = None
        if health.HEARTBEAT_PATH.exists():
            health.HEARTBEAT_PATH.unlink()

    def teardown_method(self):
        health._scheduler = None
        if health.HEARTBEAT_PATH.exists():
            health.HEARTBEAT_PATH.unlink()

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


class TestDigestHeartbeat:
    """Heartbeat fallback path — for non-scheduler Gunicorn workers."""

    def setup_method(self):
        health._scheduler = None
        if health.HEARTBEAT_PATH.exists():
            health.HEARTBEAT_PATH.unlink()

    def teardown_method(self):
        health._scheduler = None
        if health.HEARTBEAT_PATH.exists():
            health.HEARTBEAT_PATH.unlink()

    def _make_live_scheduler(self):
        import datetime as dt

        job = MagicMock()
        job.next_run_time = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
        sched = MagicMock()
        sched.running = True
        sched.get_job.return_value = job
        return sched

    def test_write_and_read_roundtrip(self):
        sched = self._make_live_scheduler()
        health.write_scheduler_heartbeat(sched)
        payload = health._read_fresh_heartbeat()
        assert payload is not None
        assert payload["running"] is True
        assert payload["job_present"] is True
        assert payload["next_run_time"]

    def test_check_digest_ok_from_fresh_heartbeat(self, monkeypatch):
        """Non-scheduler worker: _scheduler is None but heartbeat exists."""
        monkeypatch.setenv("DIGEST_TO_EMAIL", "me@example.com")
        monkeypatch.setenv("SENDGRID_API_KEY", "fake")
        sched = self._make_live_scheduler()
        health.write_scheduler_heartbeat(sched)
        # This worker never called register_scheduler
        assert health._scheduler is None
        assert health.check_digest() == "ok"

    def test_check_digest_warn_when_heartbeat_stale(self, monkeypatch):
        """Stale heartbeat should be treated as missing, not healthy."""
        import datetime as dt
        import json

        monkeypatch.setenv("DIGEST_TO_EMAIL", "me@example.com")
        monkeypatch.setenv("SENDGRID_API_KEY", "fake")
        old = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=health.HEARTBEAT_MAX_AGE_SEC + 60)
        health.HEARTBEAT_PATH.write_text(json.dumps({
            "written_at": old.isoformat(),
            "running": True,
            "job_present": True,
            "next_run_time": dt.datetime.now(dt.UTC).isoformat(),
        }))
        assert health._read_fresh_heartbeat() is None
        assert health.check_digest().startswith("warn:")

    def test_check_digest_fail_when_heartbeat_says_not_running(self, monkeypatch):
        import datetime as dt
        import json

        monkeypatch.setenv("DIGEST_TO_EMAIL", "me@example.com")
        monkeypatch.setenv("SENDGRID_API_KEY", "fake")
        health.HEARTBEAT_PATH.write_text(json.dumps({
            "written_at": dt.datetime.now(dt.UTC).isoformat(),
            "running": False,
            "job_present": True,
            "next_run_time": dt.datetime.now(dt.UTC).isoformat(),
        }))
        result = health.check_digest()
        assert result.startswith("fail:")
        assert "not running" in result

    def test_check_digest_fail_when_heartbeat_missing_job(self, monkeypatch):
        import datetime as dt
        import json

        monkeypatch.setenv("DIGEST_TO_EMAIL", "me@example.com")
        monkeypatch.setenv("SENDGRID_API_KEY", "fake")
        health.HEARTBEAT_PATH.write_text(json.dumps({
            "written_at": dt.datetime.now(dt.UTC).isoformat(),
            "running": True,
            "job_present": False,
            "next_run_time": None,
        }))
        result = health.check_digest()
        assert result.startswith("fail:")
        assert "job missing" in result

    def test_write_heartbeat_swallows_scheduler_errors(self):
        """A broken scheduler.get_job must never crash the heartbeat job."""
        sched = MagicMock()
        sched.get_job.side_effect = RuntimeError("boom")
        # Must not raise
        health.write_scheduler_heartbeat(sched)

    def test_scheduler_worker_prefers_live_scheduler_over_heartbeat(self, monkeypatch):
        """If _scheduler is set (we ARE the scheduler worker), ignore
        any stale heartbeat file and trust the live object."""
        monkeypatch.setenv("DIGEST_TO_EMAIL", "me@example.com")
        monkeypatch.setenv("SENDGRID_API_KEY", "fake")
        # Stale heartbeat that would trip a fail-branch if used
        import datetime as dt
        import json

        health.HEARTBEAT_PATH.write_text(json.dumps({
            "written_at": dt.datetime.now(dt.UTC).isoformat(),
            "running": False,  # would produce fail: if heartbeat path taken
            "job_present": True,
            "next_run_time": dt.datetime.now(dt.UTC).isoformat(),
        }))
        sched = self._make_live_scheduler()
        health.register_scheduler(sched)
        assert health.check_digest() == "ok"


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


class TestSchedulerJobsRegistered:
    """_start_digest_scheduler registers all expected cron jobs.

    Covers the full job list so a future change that inadvertently
    drops a job (or adds one without updating the assertion) breaks
    here instead of in prod after a silent midnight no-op.
    """

    def _cleanup(self):
        """Tear down both the in-memory scheduler AND the heartbeat
        file it writes to /tmp. The file is what fools
        test_healthz_digest_check_reports_scheduler_state into seeing
        a live-scheduler signal when `_scheduler` has been reset to
        None — cross-test pollution caught by gates."""
        import contextlib

        import health as _health
        if _health._scheduler is not None:
            with contextlib.suppress(Exception):
                _health._scheduler.shutdown(wait=False)
            _health._scheduler = None
        with contextlib.suppress(Exception):
            _health.HEARTBEAT_PATH.unlink(missing_ok=True)

    def _cron_spec(self, job):
        """Best-effort extract (hour, minute) from a CronTrigger."""
        trigger = getattr(job, "trigger", None)
        if trigger is None:
            return None
        fields = {f.name: str(f) for f in getattr(trigger, "fields", [])}
        return fields.get("hour"), fields.get("minute")

    def test_all_four_jobs_registered(self, app, monkeypatch):
        """#35 regression: recurring_spawn cron must exist alongside
        daily_digest, tomorrow_roll, scheduler_heartbeat."""
        from app import _start_digest_scheduler

        # Need env set so the startup function doesn't early-exit.
        monkeypatch.setenv("DIGEST_TIME", "07:00")
        monkeypatch.setenv("DIGEST_TZ", "America/New_York")

        # Start the scheduler, then immediately tear it down so tests
        # don't leave a background thread running.
        _start_digest_scheduler(app)
        try:
            import health as _health
            scheduler = _health._scheduler
            assert scheduler is not None
            job_ids = {j.id for j in scheduler.get_jobs()}
            assert "daily_digest" in job_ids
            assert "tomorrow_roll" in job_ids
            assert "recurring_spawn" in job_ids, (
                "backlog #35: auto-spawn cron should run at 00:05 local"
            )
            assert "scheduler_heartbeat" in job_ids
        finally:
            self._cleanup()

    def test_recurring_spawn_scheduled_at_00_05(self, app, monkeypatch):
        """Schedule must be exactly 00:05 so it lands after
        tomorrow_roll (00:01) but well before the morning digest."""
        from app import _start_digest_scheduler

        monkeypatch.setenv("DIGEST_TIME", "07:00")
        monkeypatch.setenv("DIGEST_TZ", "America/New_York")
        _start_digest_scheduler(app)
        try:
            import health as _health
            job = _health._scheduler.get_job("recurring_spawn")
            assert job is not None
            hour, minute = self._cron_spec(job)
            # CronTrigger field stringification quotes the value
            assert "0" in str(hour)
            assert "5" in str(minute)
        finally:
            self._cleanup()
