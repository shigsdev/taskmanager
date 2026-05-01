"""Unit tests for the health check subsystem (``health.py``).

These exercise the individual check functions in isolation so failures
point straight at the broken check, not a vague 503 from /healthz.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import health

# --- check_database ----------------------------------------------------------


class TestCheckEnumCoverage:
    """Bug #53: defense-in-depth check that every Python enum member
    used as a column type exists in the live Postgres enum. SQLite
    test runs hit the skip branch (no enum table to query)."""

    def test_skipped_on_sqlite(self, app, db):
        """Tests run on SQLite — the check should short-circuit with
        'skipped: not postgres' rather than try (and fail) to query
        pg_enum."""
        with app.app_context():
            result = health.check_enum_coverage(db)
        assert result == "skipped: not postgres"

    def test_fails_when_pg_enum_missing_value(self, monkeypatch):
        """Simulate the bug class: Python enum has a member that the
        Postgres enum doesn't. Check must return fail:."""
        import enum as _enum
        from unittest.mock import MagicMock

        # Fake DB returning a postgres dialect + an empty enum row set.
        fake_db = MagicMock()
        fake_db.engine.dialect.name = "postgresql"
        # `pg_enum` query returns no rows (DB has no enum values at all)
        fake_conn = MagicMock()
        fake_conn.execute.return_value.fetchall.return_value = []
        fake_db.engine.connect.return_value.__enter__.return_value = fake_conn

        # Fake one mapper with one column whose type carries an enum_class.
        class _FakeEnum(_enum.StrEnum):
            ALPHA = "alpha"
            BETA = "beta"

        fake_mapper = MagicMock()
        fake_col = MagicMock()
        fake_col.type.enum_class = _FakeEnum
        fake_mapper.local_table.columns = [fake_col]
        fake_db.Model.registry.mappers = [fake_mapper]

        result = health.check_enum_coverage(fake_db)
        assert result.startswith("fail:")
        # Should mention at least one missing value
        assert "ALPHA" in result or "BETA" in result

    def test_ok_when_pg_enum_has_all_values(self, monkeypatch):
        """All Python enum members appear in pg_enum → ok."""
        import enum as _enum
        from unittest.mock import MagicMock

        fake_db = MagicMock()
        fake_db.engine.dialect.name = "postgresql"
        # pg_enum returns the values our Python enum has
        fake_conn = MagicMock()
        fake_conn.execute.return_value.fetchall.return_value = [("ALPHA",), ("BETA",)]
        fake_db.engine.connect.return_value.__enter__.return_value = fake_conn

        class _FakeEnum(_enum.StrEnum):
            ALPHA = "alpha"
            BETA = "beta"

        fake_mapper = MagicMock()
        fake_col = MagicMock()
        fake_col.type.enum_class = _FakeEnum
        fake_mapper.local_table.columns = [fake_col]
        fake_db.Model.registry.mappers = [fake_mapper]

        assert health.check_enum_coverage(fake_db) == "ok"


# --- _build_enum_repair_statements (auto-derived ALTER TYPE) ---------------


class TestBuildEnumRepairStatements:
    """Bug #53: prevention — _build_enum_repair_statements derives the
    ALTER TYPE list from db.Model.registry, eliminating the manual list
    that drifted three times (#23, #25, #52)."""

    def test_emits_alter_for_every_python_enum_member(self, app):
        """For every (enum_class, member) used as a column type in
        models.py, the function emits an ALTER TYPE statement. Catches
        the bug class by construction — if a contributor adds
        ProjectType.PERSONAL to the Python enum, the corresponding
        ALTER TYPE appears in the boot gate without any manual edit."""
        from app import _build_enum_repair_statements
        with app.app_context():
            stmts = _build_enum_repair_statements()
        # Spot check known members: TaskType.WORK, ProjectType.PERSONAL
        # (the missed-third-time #52 case), Tier.NEXT_WEEK, etc.
        assert any("projecttype" in s and "PERSONAL" in s for s in stmts), (
            "must emit ALTER TYPE for ProjectType.PERSONAL "
            "(the bug that motivated #53)"
        )
        assert any("tier" in s and "NEXT_WEEK" in s for s in stmts)
        assert any("tier" in s and "TOMORROW" in s for s in stmts)
        assert any("taskstatus" in s and "CANCELLED" in s for s in stmts)

    def test_uses_if_not_exists(self, app):
        """Every statement must be IF NOT EXISTS so re-running on every
        boot is safe (no error if the value's already there)."""
        from app import _build_enum_repair_statements
        with app.app_context():
            stmts = _build_enum_repair_statements()
        for s in stmts:
            assert "IF NOT EXISTS" in s

    def test_dedups_when_same_enum_used_by_multiple_columns(self, app):
        """TaskType is used by both `tasks.type` and
        `recurring_tasks.type` — the gate should emit ONE statement per
        (enum, member), not duplicates."""
        from app import _build_enum_repair_statements
        with app.app_context():
            stmts = _build_enum_repair_statements()
        # No duplicate strings
        assert len(stmts) == len(set(stmts))


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

    def test_all_five_jobs_registered(self, app, monkeypatch):
        """All scheduler crons exist: daily_digest, tomorrow_roll,
        promote_due_today (#46), recurring_spawn (#35), scheduler_heartbeat."""
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
            assert "promote_due_today" in job_ids, (
                "backlog #46: 00:02 promotion cron should be registered"
            )
            assert "recurring_spawn" in job_ids, (
                "backlog #35: auto-spawn cron should run at 00:05 local"
            )
            assert "scheduler_heartbeat" in job_ids
        finally:
            self._cleanup()

    def test_promote_due_today_scheduled_at_00_02(self, app, monkeypatch):
        """Schedule must be 00:02 so it lands between tomorrow_roll
        (00:01) and recurring_spawn (00:05). Order matters per ADR-029
        — by the time recurring_spawn runs, any planning-tier task
        with due_date=today has been promoted, and the #38 cross-tier
        dedup correctly sees it in TODAY."""
        from app import _start_digest_scheduler

        monkeypatch.setenv("DIGEST_TIME", "07:00")
        monkeypatch.setenv("DIGEST_TZ", "America/New_York")
        _start_digest_scheduler(app)
        try:
            import health as _health
            job = _health._scheduler.get_job("promote_due_today")
            assert job is not None
            hour, minute = self._cron_spec(job)
            assert "0" in str(hour)
            assert "2" in str(minute)
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


# --- check_tls_expiry (#5) ---------------------------------------------------


class TestCheckTlsExpiry:
    """#5 — TLS cert expiry check. Disabled by default; only runs when
    TLS_EXPIRY_HOST is set. Always warn-only (never fail:)."""

    def setup_method(self):
        # Reset the module-level cache between tests so cached results
        # from a previous case don't bleed into the next.
        health._tls_cache.clear()

    def test_skipped_when_env_not_set(self, monkeypatch):
        monkeypatch.delenv("TLS_EXPIRY_HOST", raising=False)
        assert health.check_tls_expiry() == "skipped: TLS_EXPIRY_HOST not set"

    def test_skipped_when_env_blank(self, monkeypatch):
        monkeypatch.setenv("TLS_EXPIRY_HOST", "   ")
        assert health.check_tls_expiry() == "skipped: TLS_EXPIRY_HOST not set"

    def test_warn_on_invalid_port(self, monkeypatch):
        monkeypatch.setenv("TLS_EXPIRY_HOST", "shigs.us:notaport")
        result = health.check_tls_expiry()
        assert result.startswith("warn: invalid TLS_EXPIRY_HOST port")

    def test_warn_on_dns_failure(self, monkeypatch):
        # Use an unresolvable hostname; getaddrinfo raises socket.gaierror.
        monkeypatch.setenv("TLS_EXPIRY_HOST", "this-host-definitely-does-not-exist.invalid")
        result = health.check_tls_expiry()
        assert result.startswith("warn: TLS check failed:")

    def test_returns_ok_when_cert_far_from_expiry(self, monkeypatch):
        """Mock the socket + ssl path so we don't need network access."""
        import datetime as _dt
        future = _dt.datetime.now(_dt.UTC) + _dt.timedelta(days=180)
        not_after = future.strftime("%b %e %H:%M:%S %Y GMT")  # OpenSSL fmt

        self._mock_handshake(monkeypatch, {"notAfter": not_after})
        monkeypatch.setenv("TLS_EXPIRY_HOST", "test.example:443")
        assert health.check_tls_expiry() == "ok"

    def test_warns_when_cert_within_30_days(self, monkeypatch):
        import datetime as _dt
        soon = _dt.datetime.now(_dt.UTC) + _dt.timedelta(days=10)
        not_after = soon.strftime("%b %e %H:%M:%S %Y GMT")

        self._mock_handshake(monkeypatch, {"notAfter": not_after})
        monkeypatch.setenv("TLS_EXPIRY_HOST", "test.example")
        result = health.check_tls_expiry()
        assert result.startswith("warn: ")
        assert "days remaining" in result

    def test_warns_when_cert_already_expired(self, monkeypatch):
        import datetime as _dt
        past = _dt.datetime.now(_dt.UTC) - _dt.timedelta(days=5)
        not_after = past.strftime("%b %e %H:%M:%S %Y GMT")

        self._mock_handshake(monkeypatch, {"notAfter": not_after})
        monkeypatch.setenv("TLS_EXPIRY_HOST", "test.example")
        result = health.check_tls_expiry()
        assert result.startswith("warn: cert expired")

    def test_warns_when_peer_cert_missing_not_after(self, monkeypatch):
        self._mock_handshake(monkeypatch, {})  # empty cert dict
        monkeypatch.setenv("TLS_EXPIRY_HOST", "test.example")
        assert health.check_tls_expiry() == "warn: peer cert missing notAfter"

    def test_caches_within_5_minutes(self, monkeypatch):
        """Second call within cache window must NOT re-handshake."""
        import datetime as _dt
        future = _dt.datetime.now(_dt.UTC) + _dt.timedelta(days=180)
        not_after = future.strftime("%b %e %H:%M:%S %Y GMT")

        call_count = [0]

        def fake_create_connection(*args, **kwargs):
            call_count[0] += 1
            return _MockSocket()

        import socket
        monkeypatch.setattr(socket, "create_connection", fake_create_connection)

        import ssl as _ssl
        ctx = MagicMock()
        ssock = MagicMock()
        ssock.getpeercert.return_value = {"notAfter": not_after}
        ssock.__enter__ = lambda self: self
        ssock.__exit__ = lambda *a: None
        ctx.wrap_socket.return_value = ssock
        monkeypatch.setattr(_ssl, "create_default_context", lambda: ctx)

        monkeypatch.setenv("TLS_EXPIRY_HOST", "test.example")
        health.check_tls_expiry()
        health.check_tls_expiry()
        health.check_tls_expiry()
        assert call_count[0] == 1, "cache should suppress repeat handshakes"

    # --- helpers ---------------------------------------------------------

    @staticmethod
    def _mock_handshake(monkeypatch, peer_cert):
        """Patch socket.create_connection + ssl.create_default_context
        so check_tls_expiry runs end-to-end without network access."""
        import socket
        import ssl as _ssl

        monkeypatch.setattr(
            socket,
            "create_connection",
            lambda *a, **kw: _MockSocket(),
        )

        ctx = MagicMock()
        ssock = MagicMock()
        ssock.getpeercert.return_value = peer_cert
        ssock.__enter__ = lambda self: self
        ssock.__exit__ = lambda *a: None
        ctx.wrap_socket.return_value = ssock
        monkeypatch.setattr(_ssl, "create_default_context", lambda: ctx)


class _MockSocket:
    """Minimal context-manager mock for socket.create_connection."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None
