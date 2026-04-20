"""Unit tests for scripts/validate_deploy.py helpers.

The CLI entry point is exercised by operators in real deploys, but the
pure helpers (minute math, log-check classification) benefit from unit
tests so regressions like "silently ignore errors" get caught here,
not in production.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

# scripts/ is not a package — import the module by path.
_SCRIPT = Path(__file__).parent.parent / "scripts" / "validate_deploy.py"
spec = importlib.util.spec_from_file_location("validate_deploy", _SCRIPT)
vd = importlib.util.module_from_spec(spec)
sys.modules["validate_deploy"] = vd
spec.loader.exec_module(vd)


# --- _minutes_since ----------------------------------------------------------


class TestMinutesSince:
    def test_returns_none_for_empty(self):
        assert vd._minutes_since("") is None
        assert vd._minutes_since(None) is None  # type: ignore[arg-type]

    def test_returns_none_for_garbage(self):
        assert vd._minutes_since("not a timestamp") is None

    def test_parses_iso_with_z(self):
        past = datetime.now(UTC) - timedelta(minutes=5)
        iso = past.isoformat().replace("+00:00", "Z")
        minutes = vd._minutes_since(iso)
        # ~5 + 1 buffer; allow +/- 1 for scheduler jitter
        assert minutes in (5, 6, 7)

    def test_parses_iso_with_plus_offset(self):
        past = datetime.now(UTC) - timedelta(minutes=10)
        iso = past.isoformat()  # already +00:00
        minutes = vd._minutes_since(iso)
        assert minutes in (10, 11, 12)

    def test_clamps_to_minimum_one(self):
        # started_at in the same second → delta < 60s → (0 // 60) + 1 = 1
        just_now = datetime.now(UTC).isoformat()
        assert vd._minutes_since(just_now) == 1


# --- do_log_check ------------------------------------------------------------


class TestDoLogCheck:
    """Classifier over fetch_debug_logs output.

    The function must:
      1. Return SKIP if started_at is unparseable (no deploy window).
      2. Return SKIP if the endpoint is unreachable (can't fail closed
         on network issues — this is a repair gate, not a blocker).
      3. Return SKIP on 401 (auth-check would have caught it first).
      4. Return SKIP on any non-200.
      5. Return PASS if the response has no server-side errors.
      6. Return FAIL if there's at least one server-side error.
      7. Ignore client-side rows (source='client').
    """

    def _ok_recent_timestamp(self):
        return (datetime.now(UTC) - timedelta(minutes=2)).isoformat()

    def test_skip_on_unparseable_started_at(self):
        status, rows = vd.do_log_check("https://x", "cookie", "nope")
        assert status.startswith("SKIP")
        assert rows == []

    def test_skip_on_network_error(self):
        with patch.object(vd, "fetch_debug_logs", return_value=(0, None)):
            status, rows = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status.startswith("SKIP")
        assert rows == []

    def test_skip_on_401(self):
        with patch.object(vd, "fetch_debug_logs", return_value=(401, None)):
            status, rows = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status.startswith("SKIP")

    def test_skip_on_500(self):
        with patch.object(vd, "fetch_debug_logs", return_value=(500, None)):
            status, rows = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status.startswith("SKIP")

    def test_pass_on_empty_logs(self):
        with patch.object(
            vd, "fetch_debug_logs",
            return_value=(200, {"logs": [], "count": 0}),
        ):
            status, rows = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status == "PASS"
        assert rows == []

    def test_fail_on_one_server_error(self):
        error_row = {
            "level": "ERROR",
            "source": "server",
            "route": "/api/tasks",
            "message": "psycopg error",
            "timestamp": "2026-04-20T12:00:00+00:00",
        }
        with patch.object(
            vd, "fetch_debug_logs",
            return_value=(200, {"logs": [error_row], "count": 1}),
        ):
            status, rows = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status == "FAIL"
        assert len(rows) == 1

    def test_ignores_client_side_errors(self):
        client_row = {
            "level": "ERROR",
            "source": "client",
            "message": "TypeError: undefined",
        }
        with patch.object(
            vd, "fetch_debug_logs",
            return_value=(200, {"logs": [client_row], "count": 1}),
        ):
            status, rows = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status == "PASS"
        assert rows == []

    def test_mixes_server_and_client_only_counts_server(self):
        rows_in = [
            {"level": "ERROR", "source": "client", "message": "browser"},
            {"level": "ERROR", "source": "server", "message": "real failure",
             "route": "/api/goals"},
        ]
        with patch.object(
            vd, "fetch_debug_logs",
            return_value=(200, {"logs": rows_in, "count": 2}),
        ):
            status, rows = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status == "FAIL"
        assert len(rows) == 1
        assert rows[0]["route"] == "/api/goals"

    def test_passes_since_minutes_to_fetcher(self):
        """Regression guard: the window must be scoped to this deploy."""
        captured: dict = {}

        def fake_fetch(*args, **kwargs):
            captured.update(kwargs)
            return 200, {"logs": [], "count": 0}

        with patch.object(vd, "fetch_debug_logs", side_effect=fake_fetch):
            vd.do_log_check("https://x", "cookie", self._ok_recent_timestamp())

        assert "since_minutes" in captured
        assert captured["since_minutes"] >= 1
        assert captured["level"] == "ERROR"
