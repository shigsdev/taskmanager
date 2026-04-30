"""Tests for the persistent application logging system.

Covers:
- scrub_sensitive: strips emails, API keys, bearer tokens, cookies
- DBLogHandler: inserts warning+ events, respects circuit breaker
- Row and age retention pruning
- /api/debug/logs: auth, filters, pagination, param parsing
- /api/debug/client-error: creates source="client" rows, scrubs input
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select

import logging_service
from logging_service import (
    DBLogHandler,
    RequestContextFilter,
    scrub_sensitive,
)
from models import AppLog, db

# --- scrub_sensitive ---------------------------------------------------------


class TestScrubSensitive:
    def test_none_passes_through(self):
        assert scrub_sensitive(None) is None

    def test_plain_text_untouched(self):
        assert scrub_sensitive("hello world") == "hello world"

    def test_strips_email(self):
        result = scrub_sensitive("user alice@example.com did a thing")
        assert "alice@example.com" not in result
        assert "[REDACTED:EMAIL]" in result

    def test_strips_google_api_key(self):
        key = "AIza" + "b" * 35
        result = scrub_sensitive(f"url?key={key}&other=1")
        assert key not in result
        # Either the AIza pattern OR the query-string key= pattern catches it.
        assert "[REDACTED" in result

    def test_strips_anthropic_key(self):
        key = "sk-ant-" + "x" * 30
        result = scrub_sensitive(f"x-api-key: {key}")
        assert key not in result
        assert "[REDACTED:ANTHROPIC_API_KEY]" in result

    def test_strips_openai_key(self):
        # OpenAI keys are sk-... or sk-proj-... and are matched by the
        # generic "sk-" pattern (after the more specific sk-ant- pattern
        # has had its chance). Critical for the voice-memo feature which
        # uses OPENAI_API_KEY in production.
        key = "sk-" + "x" * 25
        result = scrub_sensitive(f"openai error: api_key={key}")
        assert key not in result
        assert "[REDACTED:API_KEY]" in result

    def test_strips_openai_proj_key(self):
        # Newer OpenAI keys use sk-proj- prefix.
        key = "sk-proj-" + "y" * 30
        result = scrub_sensitive(f"key from env: {key}")
        assert key not in result
        assert "[REDACTED:API_KEY]" in result

    def test_strips_bearer_token(self):
        result = scrub_sensitive("Authorization: Bearer abc123.def456-ghi")
        assert "abc123.def456-ghi" not in result

    def test_strips_session_cookie(self):
        result = scrub_sensitive("Cookie: session=eyJ1c2VyIjoiYm9iIn0.abc")
        assert "eyJ1c2VyIjoiYm9iIn0.abc" not in result
        assert "session=[REDACTED]" in result

    def test_strips_query_string_key(self):
        result = scrub_sensitive("https://api.example.com/v1?api_key=secret123")
        assert "secret123" not in result

    def test_scrubber_never_raises(self):
        # Even with weird input, it should not crash.
        assert scrub_sensitive("") == ""
        assert scrub_sensitive("🚀" * 100).count("🚀") == 100


class TestRequestIdValidation:
    """The X-Request-ID header is client-controllable and stored in
    app_logs. Validate it gets rejected if too long or non-ASCII, so
    pre-auth callers can't pollute the log table with garbage."""

    def test_valid_short_ascii_header_accepted(self, client):

        resp = client.get("/healthz", headers={"X-Request-ID": "abc-123-xyz"})
        assert resp.status_code in (200, 503)
        # No direct g introspection post-request in Flask's test client;
        # we verify behavior by round-tripping via log query in other
        # tests. Here we just confirm the request doesn't crash.

    def test_oversize_header_triggers_fresh_uuid(self, app):
        """Headers longer than 64 chars must be replaced with a generated
        UUID, not persisted as-is."""
        from flask import g

        from logging_service import _before_request

        attacker_value = "A" * 500  # 500-char garbage
        with app.test_request_context("/", headers={"X-Request-ID": attacker_value}):
            _before_request()
            assert g.request_id != attacker_value
            assert len(g.request_id) == 36  # UUID length

    def test_non_ascii_header_triggers_fresh_uuid(self, app):
        from flask import g

        from logging_service import _before_request

        with app.test_request_context("/", headers={"X-Request-ID": "héllo"}):
            _before_request()
            assert g.request_id != "héllo"
            assert len(g.request_id) == 36

    def test_valid_header_preserved(self, app):
        from flask import g

        from logging_service import _before_request

        good_id = "req-abc-123"
        with app.test_request_context("/", headers={"X-Request-ID": good_id}):
            _before_request()
            assert g.request_id == good_id


# --- DBLogHandler ------------------------------------------------------------


@pytest.fixture
def handler(app):
    """Fresh DBLogHandler attached to the test app."""
    h = DBLogHandler(app, level=logging.WARNING)
    h.addFilter(RequestContextFilter())
    return h


def _make_record(
    level: int = logging.WARNING,
    msg: str = "hello",
    name: str = "test.logger",
    exc_info=None,
):
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="test.py",
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    # Filter would normally populate these.
    record.request_id = None
    record.route = None
    record.method = None
    return record


class TestDBLogHandler:
    def test_emit_inserts_row(self, app, handler):
        record = _make_record(msg="warning happened")
        handler.emit(record)

        with app.app_context():
            rows = list(db.session.scalars(select(AppLog)))
        assert len(rows) == 1
        assert rows[0].level == "WARNING"
        assert rows[0].message == "warning happened"
        assert rows[0].source == "server"
        assert rows[0].traceback is None

    def test_emit_scrubs_message(self, app, handler):
        record = _make_record(msg="error from alice@example.com")
        handler.emit(record)

        with app.app_context():
            row = db.session.scalar(select(AppLog))
        assert "alice@example.com" not in row.message
        assert "[REDACTED:EMAIL]" in row.message

    def test_emit_captures_exc_info(self, app, handler):
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            record = _make_record(msg="crashed", exc_info=sys.exc_info())

        handler.emit(record)
        with app.app_context():
            row = db.session.scalar(select(AppLog))
        assert row.traceback is not None
        assert "ValueError: boom" in row.traceback

    def test_emit_captures_traceback_override(self, app, handler):
        """Client-error path passes a pre-formatted stack via attribute."""
        record = _make_record(msg="js error")
        record.traceback_override = "at foo (app.js:42)\nat bar (app.js:10)"
        handler.emit(record)

        with app.app_context():
            row = db.session.scalar(select(AppLog))
        assert row.traceback is not None
        assert "at foo (app.js:42)" in row.traceback

    def test_handler_skips_its_own_logs(self, app, handler):
        """Prevents infinite recursion if the handler tries to log."""
        record = _make_record(name="logging_service", msg="oops")
        handler.emit(record)
        with app.app_context():
            rows = list(db.session.scalars(select(AppLog)))
        assert len(rows) == 0

    def test_circuit_breaker_trips_after_threshold(self, app, handler):
        """After 10 consecutive failures the handler disables itself."""
        with patch.object(handler, "_insert_record", side_effect=RuntimeError("db down")):
            for _ in range(logging_service.CIRCUIT_BREAKER_THRESHOLD):
                handler.emit(_make_record())

        assert handler.is_disabled is True

        # Further emits should no-op without raising.
        handler.emit(_make_record())

    def test_circuit_breaker_resets_on_success(self, app, handler):
        """A successful insert resets the failure counter."""
        # 5 failures
        with patch.object(handler, "_insert_record", side_effect=RuntimeError("db down")):
            for _ in range(5):
                handler.emit(_make_record())
        assert handler._consecutive_failures == 5

        # Then a success
        handler.emit(_make_record(msg="recovered"))
        assert handler._consecutive_failures == 0
        assert handler.is_disabled is False

    def test_handler_disabled_skips_emit(self, app, handler):
        handler._disabled = True
        handler.emit(_make_record(msg="should not insert"))
        with app.app_context():
            rows = list(db.session.scalars(select(AppLog)))
        assert len(rows) == 0

    def test_emit_uses_isolated_session_not_db_session(self, app, handler):
        """Regression for the 2026-04-19 enum outage.

        In prod, a Postgres enum rejection left ``db.session``'s
        transaction in the "current transaction is aborted, commands
        ignored" state; every subsequent ``db.session.commit()`` in
        the error handler also failed, which tripped the circuit
        breaker and lost server-side error visibility.

        SQLite in the test env doesn't exhibit that exact poisoned
        state, so we can't reproduce it faithfully. Instead we assert
        the structural property that *makes the fix work*: the
        handler's insert must NOT go through ``db.session``. If any
        future change regresses back to ``db.session.commit()``, this
        test fails.
        """
        # Track attempts to touch db.session. If the handler ever calls
        # .add/.commit/.execute on it during insert, that's a regression:
        # a poisoned caller transaction on db.session would then sink the
        # logger. Count calls (don't raise) so the failure message is
        # clearer than a late AttributeError inside SQLAlchemy internals.
        calls: list[str] = []
        from unittest.mock import patch as _patch
        with app.app_context():
            with _patch.object(
                db.session, "add",
                side_effect=lambda *a, **k: calls.append("add"),
            ), _patch.object(
                db.session, "commit",
                side_effect=lambda *a, **k: calls.append("commit"),
            ):
                handler.emit(_make_record(msg="routed via isolated session"))

            db.session.rollback()
            rows = list(db.session.scalars(select(AppLog)))

        assert calls == [], (
            f"DBLogHandler used db.session (calls: {calls}). "
            "Regression: it must use Session(db.engine) so a poisoned "
            "caller transaction can't cascade into the logger."
        )
        assert len(rows) == 1
        assert rows[0].message == "routed via isolated session"
        assert handler._consecutive_failures == 0
        assert handler.is_disabled is False

    def test_row_cap_pruning(self, app, handler, monkeypatch):
        """After exceeding MAX_ROWS the oldest rows get deleted.

        PR71 perf #9: row-cap prune is now gated behind
        ``PRUNE_EVERY_N_INSERTS`` (was running on every emit, which
        forced a SELECT count(*) on every WARNING+ row). Force the
        gate down to 1 here so the test exercises the prune path
        deterministically; production cadence is 50 inserts.
        """
        monkeypatch.setattr(logging_service, "MAX_ROWS", 5)
        monkeypatch.setattr(logging_service, "PRUNE_EVERY_N_INSERTS", 1)
        for i in range(8):
            handler.emit(_make_record(msg=f"msg {i}"))

        with app.app_context():
            rows = list(
                db.session.scalars(
                    select(AppLog).order_by(AppLog.timestamp.asc())
                )
            )
        # Should have pruned down to 5.
        assert len(rows) == 5
        # Oldest (msg 0, 1, 2) should be gone.
        msgs = [r.message for r in rows]
        assert "msg 0" not in msgs
        assert "msg 7" in msgs

    def test_age_pruning(self, app, handler):
        """Rows older than MAX_AGE_DAYS are swept."""
        with app.app_context():
            old = AppLog(
                timestamp=datetime.now(UTC) - timedelta(days=20),
                level="WARNING",
                logger_name="x",
                message="ancient",
                source="server",
            )
            fresh = AppLog(
                timestamp=datetime.now(UTC),
                level="WARNING",
                logger_name="x",
                message="fresh",
                source="server",
            )
            db.session.add_all([old, fresh])
            db.session.commit()

        handler._prune_age()

        with app.app_context():
            rows = list(db.session.scalars(select(AppLog)))
        messages = [r.message for r in rows]
        assert "ancient" not in messages
        assert "fresh" in messages


# --- /api/debug/logs ---------------------------------------------------------


class TestDebugLogsEndpoint:
    def test_requires_auth(self, client):
        resp = client.get("/api/debug/logs")
        # unauthenticated → redirect to OAuth login
        assert resp.status_code in (302, 401, 403)

    def test_empty_returns_zero(self, authed_client):
        resp = authed_client.get("/api/debug/logs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 0
        assert data["logs"] == []

    def _seed(self, app, **kwargs):
        with app.app_context():
            row = AppLog(
                timestamp=kwargs.get("timestamp", datetime.now(UTC)),
                level=kwargs.get("level", "WARNING"),
                logger_name=kwargs.get("logger_name", "test"),
                message=kwargs.get("message", "msg"),
                traceback=kwargs.get("traceback"),
                source=kwargs.get("source", "server"),
                route=kwargs.get("route"),
                method=kwargs.get("method"),
                status_code=kwargs.get("status_code"),
            )
            db.session.add(row)
            db.session.commit()

    def test_returns_recent_rows(self, app, authed_client):
        self._seed(app, message="first", level="ERROR")
        self._seed(app, message="second", level="WARNING")

        resp = authed_client.get("/api/debug/logs")
        data = resp.get_json()
        assert data["count"] == 2
        # Newest first
        messages = [log["message"] for log in data["logs"]]
        assert "first" in messages
        assert "second" in messages

    def test_level_filter_exact(self, app, authed_client):
        """?level=ERROR includes ERROR and CRITICAL (standard logging semantics)."""
        self._seed(app, message="info1", level="INFO")
        self._seed(app, message="warn1", level="WARNING")
        self._seed(app, message="err1", level="ERROR")
        self._seed(app, message="crit1", level="CRITICAL")

        resp = authed_client.get("/api/debug/logs?level=ERROR")
        data = resp.get_json()
        messages = {log["message"] for log in data["logs"]}
        assert "err1" in messages
        assert "crit1" in messages
        assert "warn1" not in messages
        assert "info1" not in messages

    def test_level_filter_warning_includes_above(self, app, authed_client):
        self._seed(app, message="info1", level="INFO")
        self._seed(app, message="warn1", level="WARNING")
        self._seed(app, message="err1", level="ERROR")

        resp = authed_client.get("/api/debug/logs?level=WARNING")
        data = resp.get_json()
        messages = {log["message"] for log in data["logs"]}
        assert "warn1" in messages
        assert "err1" in messages
        assert "info1" not in messages

    def test_invalid_level_400(self, authed_client):
        resp = authed_client.get("/api/debug/logs?level=BANANA")
        assert resp.status_code == 400

    def test_since_shorthand(self, app, authed_client):
        self._seed(
            app,
            message="old",
            timestamp=datetime.now(UTC) - timedelta(hours=3),
        )
        self._seed(app, message="new")

        resp = authed_client.get("/api/debug/logs?since=1h")
        data = resp.get_json()
        messages = [log["message"] for log in data["logs"]]
        assert "new" in messages
        assert "old" not in messages

    def test_since_iso(self, app, authed_client):
        self._seed(app, message="recent")
        cutoff = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        resp = authed_client.get(f"/api/debug/logs?since={cutoff}")
        assert resp.status_code == 200

    def test_since_invalid(self, authed_client):
        resp = authed_client.get("/api/debug/logs?since=notatime")
        assert resp.status_code == 400

    def test_limit_capped(self, app, authed_client):
        for i in range(5):
            self._seed(app, message=f"m{i}")
        resp = authed_client.get("/api/debug/logs?limit=2")
        data = resp.get_json()
        assert data["count"] == 2
        assert data["limit"] == 2

    def test_limit_invalid(self, authed_client):
        resp = authed_client.get("/api/debug/logs?limit=abc")
        assert resp.status_code == 400

    def test_route_filter(self, app, authed_client):
        self._seed(app, message="api-hit", route="/api/tasks/123")
        self._seed(app, message="page-hit", route="/settings")

        resp = authed_client.get("/api/debug/logs?route=/api/")
        data = resp.get_json()
        assert data["count"] == 1
        assert data["logs"][0]["message"] == "api-hit"

    def test_source_filter(self, app, authed_client):
        self._seed(app, message="srv", source="server")
        self._seed(app, message="cli", source="client")

        resp = authed_client.get("/api/debug/logs?source=client")
        data = resp.get_json()
        assert data["count"] == 1
        assert data["logs"][0]["message"] == "cli"


# --- /api/debug/client-error -------------------------------------------------


class TestDebugTokenAuth:
    """X-Debug-Token should allow unauthenticated programmatic access."""

    def test_correct_token_grants_access(self, app, client, monkeypatch):
        monkeypatch.setenv("APP_DEBUG_TOKEN", "secret-token-abc")
        resp = client.get(
            "/api/debug/logs",
            headers={"X-Debug-Token": "secret-token-abc"},
        )
        assert resp.status_code == 200

    def test_wrong_token_falls_through_to_oauth(self, client, monkeypatch):
        monkeypatch.setenv("APP_DEBUG_TOKEN", "secret-token-abc")
        resp = client.get(
            "/api/debug/logs",
            headers={"X-Debug-Token": "wrong-token"},
        )
        # No OAuth session → redirect to login
        assert resp.status_code in (302, 401, 403)

    def test_no_token_configured_blocks_header_auth(self, client, monkeypatch):
        """If APP_DEBUG_TOKEN is unset, the token path is fully disabled.

        This prevents an attacker from bypassing auth by sending an
        empty/any X-Debug-Token when the env var happens to not be set.
        """
        monkeypatch.delenv("APP_DEBUG_TOKEN", raising=False)
        resp = client.get(
            "/api/debug/logs",
            headers={"X-Debug-Token": "anything"},
        )
        assert resp.status_code in (302, 401, 403)

    def test_empty_token_env_blocks_header_auth(self, client, monkeypatch):
        """Empty string env var must not match an empty header."""
        monkeypatch.setenv("APP_DEBUG_TOKEN", "")
        resp = client.get(
            "/api/debug/logs",
            headers={"X-Debug-Token": ""},
        )
        assert resp.status_code in (302, 401, 403)

    def test_no_header_falls_through_to_oauth(self, client, monkeypatch):
        monkeypatch.setenv("APP_DEBUG_TOKEN", "secret-token-abc")
        resp = client.get("/api/debug/logs")
        assert resp.status_code in (302, 401, 403)


class TestDebugAdminTokenSplit:
    """PR65 / audit fix #126: split APP_DEBUG_TOKEN into READ-only and
    ADMIN-only tokens. The READ token must NOT authenticate mutating
    backfill / realign endpoints; only APP_DEBUG_ADMIN_TOKEN does."""

    def test_read_token_blocked_on_mutating_backfill(self, client, monkeypatch):
        """The classic leak scenario: APP_DEBUG_TOKEN is pasted into a
        chat / shell history. With the split, the leaked read token still
        cannot rewrite tier/goal/project assignments wholesale."""
        monkeypatch.setenv("APP_DEBUG_TOKEN", "read-token-leaked")
        monkeypatch.delenv("APP_DEBUG_ADMIN_TOKEN", raising=False)
        # Try to use the read token on a mutating endpoint.
        resp = client.post(
            "/api/debug/backfill/project-colors",
            headers={"X-Debug-Token": "read-token-leaked"},
        )
        # No OAuth session, read token doesn't gate this endpoint →
        # should fall through to OAuth and redirect/401.
        assert resp.status_code in (302, 401, 403)

    def test_admin_token_grants_access_to_backfill(self, app, client, monkeypatch):
        monkeypatch.setenv("APP_DEBUG_ADMIN_TOKEN", "admin-token-xyz")
        resp = client.post(
            "/api/debug/backfill/project-colors",
            headers={"X-Debug-Token": "admin-token-xyz"},
        )
        # Endpoint runs (might be 200 or other success — either way NOT
        # a 302/401/403 auth failure).
        assert resp.status_code not in (302, 401, 403)

    def test_admin_token_also_grants_read_access(self, client, monkeypatch):
        """Admin is strictly more privileged than read — admin token
        should ALSO satisfy the read-scoped decorator."""
        monkeypatch.delenv("APP_DEBUG_TOKEN", raising=False)
        monkeypatch.setenv("APP_DEBUG_ADMIN_TOKEN", "admin-token-xyz")
        resp = client.get(
            "/api/debug/logs",
            headers={"X-Debug-Token": "admin-token-xyz"},
        )
        assert resp.status_code == 200

    def test_admin_token_unset_blocks_backfill(self, client, monkeypatch):
        """If APP_DEBUG_ADMIN_TOKEN is unset, no token can authorize
        backfills via the header path."""
        monkeypatch.delenv("APP_DEBUG_ADMIN_TOKEN", raising=False)
        resp = client.post(
            "/api/debug/backfill/project-colors",
            headers={"X-Debug-Token": "anything"},
        )
        assert resp.status_code in (302, 401, 403)

    def test_realign_tiers_requires_admin_token(self, client, monkeypatch):
        """Same gate as the backfill endpoints — realign-tiers is a
        sweep that re-routes every active task."""
        monkeypatch.setenv("APP_DEBUG_TOKEN", "read-token-leaked")
        monkeypatch.delenv("APP_DEBUG_ADMIN_TOKEN", raising=False)
        resp = client.post(
            "/api/debug/realign-tiers",
            headers={"X-Debug-Token": "read-token-leaked"},
        )
        assert resp.status_code in (302, 401, 403)

    def test_token_access_is_logged(self, app, client, monkeypatch):
        """Every token-auth access should create a WARNING app_logs row."""
        # Install a handler manually (TESTING=True disables configure_logging)
        handler = DBLogHandler(app, level=logging.WARNING)
        handler.addFilter(RequestContextFilter())
        debug_logger = logging.getLogger("taskmanager.debug")
        debug_logger.addHandler(handler)
        debug_logger.setLevel(logging.WARNING)
        try:
            monkeypatch.setenv("APP_DEBUG_TOKEN", "secret-token-abc")
            resp = client.get(
                "/api/debug/logs",
                headers={"X-Debug-Token": "secret-token-abc"},
            )
            assert resp.status_code == 200

            with app.app_context():
                rows = list(db.session.scalars(select(AppLog)))
            # At least one row should describe the token-auth access.
            # Match on the substring that's actually in the log message —
            # debug_api.py was rephrased on 2026-04-18 to avoid the
            # words "token" / "secret" in the format string (semgrep
            # logger-credential-leak rule was firing on it).
            access_logs = [r for r in rows if "header-auth path" in r.message]
            assert len(access_logs) >= 1
            assert access_logs[0].level == "WARNING"
        finally:
            debug_logger.removeHandler(handler)


class TestClientErrorEndpoint:
    def test_requires_auth(self, client):
        resp = client.post("/api/debug/client-error", json={"message": "x"})
        assert resp.status_code in (302, 401, 403)

    def test_requires_json(self, authed_client):
        resp = authed_client.post(
            "/api/debug/client-error", data="not json"
        )
        assert resp.status_code == 400

    def test_creates_client_source_row(self, app, authed_client):
        # The test app has TESTING=True so configure_logging isn't called.
        # Install a DBLogHandler manually so the endpoint's log.handle()
        # has somewhere to go.
        handler = DBLogHandler(app, level=logging.ERROR)
        handler.addFilter(RequestContextFilter())
        client_logger = logging.getLogger("taskmanager.client")
        client_logger.addHandler(handler)
        client_logger.setLevel(logging.ERROR)
        try:
            resp = authed_client.post(
                "/api/debug/client-error",
                json={
                    "message": "ReferenceError: foo is not defined",
                    "stack": "at bar (/static/app.js:42)",
                    "url": "https://example.com/settings",
                    "line": 42,
                    "column": 10,
                    "userAgent": "Mozilla/5.0 Test",
                },
            )
            assert resp.status_code == 201

            with app.app_context():
                row = db.session.scalar(select(AppLog))
            assert row is not None
            assert row.source == "client"
            assert row.level == "ERROR"
            assert "ReferenceError" in row.message
            assert row.traceback is not None
            assert "at bar" in row.traceback
        finally:
            client_logger.removeHandler(handler)

    def test_client_error_scrubs_email(self, app, authed_client):
        handler = DBLogHandler(app, level=logging.ERROR)
        handler.addFilter(RequestContextFilter())
        client_logger = logging.getLogger("taskmanager.client")
        client_logger.addHandler(handler)
        client_logger.setLevel(logging.ERROR)
        try:
            resp = authed_client.post(
                "/api/debug/client-error",
                json={
                    "message": "failed for user bob@example.com",
                    "url": "/inbox",
                },
            )
            assert resp.status_code == 201

            with app.app_context():
                row = db.session.scalar(select(AppLog))
            assert "bob@example.com" not in row.message
            assert "[REDACTED:EMAIL]" in row.message
        finally:
            client_logger.removeHandler(handler)


class TestClientErrorControlCharStripAndCaps:
    """PR62 audit fix #12 + #24: per-field length caps + control-char
    strip on /api/debug/client-error so embedded \\n can't fake fake log
    rows and an attacker can't write 50KB+ messages each."""

    def test_newlines_in_message_replaced_with_space(self, app, authed_client):
        handler = DBLogHandler(app, level=logging.ERROR)
        handler.addFilter(RequestContextFilter())
        client_logger = logging.getLogger("taskmanager.client")
        client_logger.addHandler(handler)
        client_logger.setLevel(logging.ERROR)
        try:
            resp = authed_client.post(
                "/api/debug/client-error",
                json={"message": "real error\n2026-01-01 ERROR fake injected"},
            )
            assert resp.status_code == 201
            with app.app_context():
                row = db.session.scalar(select(AppLog))
            # Newline must be neutralized so the row is a single line.
            assert "\n" not in row.message
            # Both halves still present, separated by space (not newline).
            assert "real error" in row.message
            assert "fake injected" in row.message
        finally:
            client_logger.removeHandler(handler)

    def test_oversized_message_truncated_at_2k(self, app, authed_client):
        handler = DBLogHandler(app, level=logging.ERROR)
        handler.addFilter(RequestContextFilter())
        client_logger = logging.getLogger("taskmanager.client")
        client_logger.addHandler(handler)
        client_logger.setLevel(logging.ERROR)
        try:
            resp = authed_client.post(
                "/api/debug/client-error",
                json={"message": "A" * 5000},
            )
            assert resp.status_code == 201
            with app.app_context():
                row = db.session.scalar(select(AppLog))
            # Cap is 2000 chars + "...[truncated]" suffix; total < 2100.
            assert len(row.message) < 2100
            assert "[truncated]" in row.message
        finally:
            client_logger.removeHandler(handler)


class TestBackfillProjectColors:
    """#93 (PR27): the project-colors backfill admin endpoint."""

    def test_idempotent_when_no_legacy_blue_personal_projects(
        self, app, authed_client
    ):
        """Endpoint runs cleanly when no projects need updating."""
        # No projects exist (or all have manual overrides) — empty response.
        resp = authed_client.post("/api/debug/backfill/project-colors")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "scanned" in body
        assert "updated" in body
        assert isinstance(body["changes"], list)

    def test_personal_project_with_legacy_blue_gets_switched_to_green(
        self, app, authed_client
    ):
        """A Personal project carrying #2563eb (legacy default for all
        types) should be switched to #16a34a (the per-type default)."""
        from models import Project, ProjectType, db
        with app.app_context():
            p = Project(name="Old Personal", type=ProjectType.PERSONAL,
                        color="#2563eb", is_active=True)
            db.session.add(p)
            db.session.commit()
            pid = p.id

        resp = authed_client.post("/api/debug/backfill/project-colors")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["updated"] >= 1
        ids_changed = [c["id"] for c in body["changes"]]
        assert str(pid) in ids_changed
        with app.app_context():
            p2 = db.session.get(Project, pid)
            assert p2.color == "#16a34a"

    def test_work_project_with_legacy_blue_is_unchanged(
        self, app, authed_client
    ):
        """Work projects keep #2563eb (it IS the per-type default)."""
        from models import Project, ProjectType, db
        with app.app_context():
            p = Project(name="Old Work", type=ProjectType.WORK,
                        color="#2563eb", is_active=True)
            db.session.add(p)
            db.session.commit()
            pid = p.id

        authed_client.post("/api/debug/backfill/project-colors")
        with app.app_context():
            p2 = db.session.get(Project, pid)
            assert p2.color == "#2563eb"

    def test_manually_overridden_color_is_never_touched(
        self, app, authed_client
    ):
        """A Personal project with a non-legacy color (e.g. user picked
        #ff0000) must NOT be backfilled."""
        from models import Project, ProjectType, db
        with app.app_context():
            p = Project(name="Custom Color", type=ProjectType.PERSONAL,
                        color="#ff0000", is_active=True)
            db.session.add(p)
            db.session.commit()
            pid = p.id

        authed_client.post("/api/debug/backfill/project-colors")
        with app.app_context():
            p2 = db.session.get(Project, pid)
            assert p2.color == "#ff0000"


class TestBackfillTodayTomorrowDueDate:
    """#100 (PR29): backfill due_date on legacy TODAY/TOMORROW rows."""

    def test_today_tier_without_due_date_gets_today(self, app, authed_client):
        from datetime import date

        from models import Task, TaskStatus, TaskType, Tier, db
        with app.app_context():
            t = Task(title="Legacy today", type=TaskType.WORK,
                     tier=Tier.TODAY, status=TaskStatus.ACTIVE)
            db.session.add(t)
            db.session.commit()
            tid = t.id

        resp = authed_client.post(
            "/api/debug/backfill/today-tomorrow-due-date"
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["updated_today"] >= 1
        with app.app_context():
            t2 = db.session.get(Task, tid)
            assert t2.due_date == date.today()

    def test_tomorrow_tier_without_due_date_gets_tomorrow(self, app, authed_client):
        from datetime import date, timedelta

        from models import Task, TaskStatus, TaskType, Tier, db
        with app.app_context():
            t = Task(title="Legacy tomorrow", type=TaskType.WORK,
                     tier=Tier.TOMORROW, status=TaskStatus.ACTIVE)
            db.session.add(t)
            db.session.commit()
            tid = t.id

        authed_client.post("/api/debug/backfill/today-tomorrow-due-date")
        with app.app_context():
            t2 = db.session.get(Task, tid)
            assert t2.due_date == date.today() + timedelta(days=1)

    def test_already_set_due_date_is_left_alone(self, app, authed_client):
        from datetime import date

        from models import Task, TaskStatus, TaskType, Tier, db
        explicit = date(2026, 12, 31)
        with app.app_context():
            t = Task(title="Has explicit date", type=TaskType.WORK,
                     tier=Tier.TODAY, status=TaskStatus.ACTIVE,
                     due_date=explicit)
            db.session.add(t)
            db.session.commit()
            tid = t.id

        authed_client.post("/api/debug/backfill/today-tomorrow-due-date")
        with app.app_context():
            t2 = db.session.get(Task, tid)
            assert t2.due_date == explicit, "explicit date must not be overwritten"

    def test_inbox_tier_is_not_touched(self, app, authed_client):
        from models import Task, TaskStatus, TaskType, Tier, db
        with app.app_context():
            t = Task(title="Inbox no date", type=TaskType.WORK,
                     tier=Tier.INBOX, status=TaskStatus.ACTIVE)
            db.session.add(t)
            db.session.commit()
            tid = t.id

        authed_client.post("/api/debug/backfill/today-tomorrow-due-date")
        with app.app_context():
            t2 = db.session.get(Task, tid)
            assert t2.due_date is None
