"""Direct unit tests for egress.py — the central outbound-HTTP module.

SSRF behavior is exercised transitively by test_tasks_api.py (the
url_preview route wraps safe_fetch_user_url). This module covers the
OTHER half: safe_call_api error shapes, input-validation corners on
safe_fetch_user_url, and the EgressError contract. Cross-reference
ADR-023 for the boundary design.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from egress import EgressError, safe_call_api, safe_fetch_user_url

# --- safe_fetch_user_url: input validation ----------------------------------


class TestSafeFetchUserUrlInputValidation:
    """Inputs that should short-circuit to None without attempting any
    network work. The route-level tests cover the SSRF path; these cover
    the earlier guard clauses that protect us from non-URL inputs."""

    def test_non_string_input_returns_none(self):
        assert safe_fetch_user_url(None) is None  # type: ignore[arg-type]
        assert safe_fetch_user_url(123) is None  # type: ignore[arg-type]
        assert safe_fetch_user_url(["http://x"]) is None  # type: ignore[arg-type]

    def test_non_http_scheme_returns_none(self):
        assert safe_fetch_user_url("ftp://example.com") is None
        assert safe_fetch_user_url("file:///etc/passwd") is None
        assert safe_fetch_user_url("javascript:alert(1)") is None
        assert safe_fetch_user_url("") is None

    def test_missing_hostname_returns_none(self):
        # http:/// has a scheme but no host
        assert safe_fetch_user_url("http:///") is None
        # http://:80 has a port but no host
        assert safe_fetch_user_url("http://:80/path") is None

    def test_unresolvable_hostname_returns_none(self):
        # gaierror in the except list — must return None, not raise
        with patch("egress.socket.getaddrinfo", side_effect=__import__("socket").gaierror):
            assert safe_fetch_user_url("http://no-such-host.invalid") is None

    def test_never_raises_on_unexpected_exception(self):
        """Contract: the function promises never to raise — callers rely
        on the None return to fall through to a 'title unknown' path.
        A broken monkey-patch that raises RuntimeError would normally
        escape, but the final bare except swallows it."""
        with patch(
            "egress.socket.getaddrinfo", side_effect=RuntimeError("unexpected"),
        ):
            assert safe_fetch_user_url("http://example.com") is None


# --- safe_call_api: happy path ----------------------------------------------


class TestSafeCallApiHappyPath:

    def test_json_body_returns_parsed_response(self):
        mock_resp = MagicMock(ok=True)
        mock_resp.json.return_value = {"result": "ok", "value": 42}
        with patch("egress.requests.post", return_value=mock_resp) as mock_post:
            got = safe_call_api(
                url="https://api.example.com/v1/thing",
                headers={"x-api-key": "secret"},
                json={"q": "hi"},
                vendor="Example",
            )
        assert got == {"result": "ok", "value": 42}
        # Auth header passed through; timeout enforced
        _, kwargs = mock_post.call_args
        assert kwargs["headers"] == {"x-api-key": "secret"}
        assert kwargs["json"] == {"q": "hi"}
        assert kwargs["timeout"] == 60.0

    def test_multipart_body_path(self):
        mock_resp = MagicMock(ok=True)
        mock_resp.json.return_value = {"text": "hello"}
        with patch("egress.requests.post", return_value=mock_resp) as mock_post:
            got = safe_call_api(
                url="https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": "Bearer sk-xxx"},
                files={"file": ("audio.webm", b"bytes", "audio/webm")},
                data={"model": "whisper-1"},
                vendor="Whisper",
            )
        assert got == {"text": "hello"}
        _, kwargs = mock_post.call_args
        # Multipart path is taken when json=None
        assert "json" not in kwargs
        assert kwargs["files"] is not None
        assert kwargs["data"] == {"model": "whisper-1"}

    def test_custom_timeout_respected(self):
        mock_resp = MagicMock(ok=True)
        mock_resp.json.return_value = {}
        with patch("egress.requests.post", return_value=mock_resp) as mock_post:
            safe_call_api(
                url="https://api.example.com/x",
                headers={},
                json={},
                timeout_sec=5.5,
                vendor="X",
            )
        assert mock_post.call_args[1]["timeout"] == 5.5


# --- safe_call_api: error wrapping ------------------------------------------


class TestSafeCallApiErrorShapes:
    """EgressError messages must NEVER include the API key or full URL —
    they surface directly to users. Every failure path must produce a
    safe, informative message."""

    def test_network_exception_wrapped_as_egress_error(self):
        with patch(
            "egress.requests.post",
            side_effect=requests.ConnectionError("dns fail"),
        ), pytest.raises(EgressError) as exc_info:
            safe_call_api(
                url="https://api.anthropic.com/v1/messages",
                headers={"x-api-key": "sk-ant-SECRET"},
                json={},
                vendor="Claude",
            )
        msg = str(exc_info.value)
        assert "Claude" in msg
        # Exception type surfaces but nothing sensitive
        assert "ConnectionError" in msg
        # No key, no full URL in message
        assert "sk-ant-SECRET" not in msg
        assert "api.anthropic.com" not in msg

    def test_timeout_wrapped_as_egress_error(self):
        with patch(
            "egress.requests.post", side_effect=requests.Timeout("too slow"),
        ), pytest.raises(EgressError) as exc_info:
            safe_call_api(
                url="https://x/y", headers={}, json={}, vendor="Vision",
            )
        assert "Vision" in str(exc_info.value)
        assert "Timeout" in str(exc_info.value)

    def test_http_error_includes_status_and_detail(self):
        mock_resp = MagicMock(ok=False, status_code=429)
        mock_resp.json.return_value = {
            "error": {"message": "rate limit exceeded"},
        }
        with patch("egress.requests.post", return_value=mock_resp), \
                pytest.raises(EgressError) as exc_info:
            safe_call_api(
                url="https://api.x/y",
                headers={"x-api-key": "secret"},
                json={},
                vendor="Claude",
            )
        msg = str(exc_info.value)
        assert "Claude" in msg
        assert "429" in msg
        assert "rate limit exceeded" in msg
        assert "secret" not in msg

    def test_http_error_falls_back_to_text_when_not_json(self):
        mock_resp = MagicMock(ok=False, status_code=500)
        mock_resp.json.side_effect = ValueError("not json")
        mock_resp.text = "Internal Server Error — upstream timeout"
        with patch("egress.requests.post", return_value=mock_resp), \
                pytest.raises(EgressError) as exc_info:
            safe_call_api(
                url="https://api.x/y", headers={}, json={}, vendor="Whisper",
            )
        msg = str(exc_info.value)
        assert "500" in msg
        assert "Internal Server Error" in msg

    def test_http_error_truncates_long_text_body(self):
        """Long upstream HTML error pages shouldn't blow up the error
        message. 200 chars is plenty for a diagnostic; the rest is noise."""
        mock_resp = MagicMock(ok=False, status_code=502)
        mock_resp.json.side_effect = ValueError("not json")
        mock_resp.text = "X" * 5000
        with patch("egress.requests.post", return_value=mock_resp), \
                pytest.raises(EgressError) as exc_info:
            safe_call_api(
                url="https://api.x/y", headers={}, json={}, vendor="Vendor",
            )
        msg = str(exc_info.value)
        # 200-char cap on body detail
        assert len(msg) < 400

    def test_invalid_json_response_wrapped(self):
        mock_resp = MagicMock(ok=True)
        mock_resp.json.side_effect = ValueError("invalid json")
        with patch("egress.requests.post", return_value=mock_resp), \
                pytest.raises(EgressError) as exc_info:
            safe_call_api(
                url="https://api.x/y", headers={}, json={}, vendor="Claude",
            )
        assert "Claude" in str(exc_info.value)
        assert "invalid JSON" in str(exc_info.value)

    def test_empty_error_detail_omits_colon(self):
        """When the upstream returns an empty error body, the message
        shouldn't have a dangling 'HTTP 503: ' with nothing after it."""
        mock_resp = MagicMock(ok=False, status_code=503)
        mock_resp.json.return_value = {}  # no .error.message
        mock_resp.text = ""
        with patch("egress.requests.post", return_value=mock_resp), \
                pytest.raises(EgressError) as exc_info:
            safe_call_api(
                url="https://api.x/y", headers={}, json={}, vendor="X",
            )
        msg = str(exc_info.value)
        assert "503" in msg
        assert not msg.rstrip().endswith(":")


# --- Contract tests ---------------------------------------------------------


class TestEgressErrorContract:
    """EgressError is a RuntimeError subclass (so existing `except
    RuntimeError` blocks catch it) AND the str() output is always
    safe to surface to end-users."""

    def test_is_runtime_error_subclass(self):
        assert issubclass(EgressError, RuntimeError)

    def test_str_output_does_not_include_original_exception_args(self):
        """`raise EgressError(msg) from e` attaches __cause__; the str()
        of the EgressError itself should only be our sanitized msg,
        not the chained exception."""
        original = requests.ConnectionError("https://api.x/y?key=SECRET")
        with patch("egress.requests.post", side_effect=original), \
                pytest.raises(EgressError) as exc_info:
            safe_call_api(
                url="https://api.x/y",
                headers={"Authorization": "Bearer SECRET"},
                json={},
                vendor="X",
            )
        # str(EgressError) is the sanitized wrapper message only
        assert "SECRET" not in str(exc_info.value)
        assert "?key=" not in str(exc_info.value)
        # The original IS preserved on __cause__ for server-side
        # debugging, just not in the user-facing str().
        assert exc_info.value.__cause__ is original
