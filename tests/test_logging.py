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

    def test_row_cap_pruning(self, app, handler, monkeypatch):
        """After exceeding MAX_ROWS the oldest rows get deleted."""
        monkeypatch.setattr(logging_service, "MAX_ROWS", 5)
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

    def test_level_filter(self, app, authed_client):
        self._seed(app, message="warn1", level="WARNING")
        self._seed(app, message="err1", level="ERROR")

        resp = authed_client.get("/api/debug/logs?level=ERROR")
        data = resp.get_json()
        assert data["count"] == 1
        assert data["logs"][0]["message"] == "err1"

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
