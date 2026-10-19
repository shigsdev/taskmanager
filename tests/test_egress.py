"""Direct unit tests for egress.py — the central outbound-HTTP module.

egress.py has three senders. This file covers two of them directly:

- ``safe_fetch_user_url`` + ``is_user_url_allowed`` (user-supplied URLs,
  ADR-006): input guards, the private/loopback/… allowlist, the IP pin
  with the original Host header, the body cap, and the opener that
  refuses redirects. test_tasks_api.py checks the same defenses through
  the url_preview route, but it stubs ``OpenerDirector.open``, so only
  this file runs the real ``_NoRedirect`` handler.
- ``safe_call_api`` (fixed third-party APIs): error shapes and the
  ``EgressError`` contract (ADR-023).

``safe_call_dav`` (#371, iCloud) is tested in test_egress_dav.py.
"""
from __future__ import annotations

import socket
import urllib.request
from unittest.mock import MagicMock, patch

import pytest
import requests

import egress
from egress import (
    EgressError,
    is_user_url_allowed,
    safe_call_api,
    safe_fetch_user_url,
)


def _resolves_to(*ips: str):
    """A getaddrinfo stand-in answering with ``ips``, in order."""
    return lambda *a, **kw: [(None, None, None, None, (ip, 0)) for ip in ips]


# One address from every range _is_disallowed_ip refuses.
DISALLOWED = [
    "127.0.0.1",        # loopback
    "::1",              # IPv6 loopback
    "10.0.0.5",         # RFC 1918
    "192.168.1.20",     # RFC 1918
    "169.254.169.254",  # link-local (cloud metadata)
    "fe80::1",          # IPv6 link-local
    "224.0.0.1",        # multicast
    "0.0.0.0",          # unspecified  # noqa: S104
    "240.0.0.1",        # reserved
]
PUBLIC = "93.184.216.34"

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

    def test_empty_resolution_returns_none(self):
        with patch("egress.socket.getaddrinfo", return_value=[]):
            assert safe_fetch_user_url("http://example.com") is None


# --- is_user_url_allowed -----------------------------------------------------


class TestIsUserUrlAllowed:
    """The single resolution path url_preview uses to tell "forbidden
    network → 400" from "fetch failed → no title" (#125)."""

    @pytest.mark.parametrize("ip", DISALLOWED)
    def test_every_disallowed_range_is_refused(self, ip):
        with patch("egress.socket.getaddrinfo", _resolves_to(ip)):
            assert is_user_url_allowed("https://x.example/") is False

    def test_a_public_address_is_allowed(self):
        with patch("egress.socket.getaddrinfo", _resolves_to(PUBLIC)):
            assert is_user_url_allowed("https://x.example/") is True

    def test_one_bad_answer_among_good_ones_refuses(self):
        with patch("egress.socket.getaddrinfo", _resolves_to(PUBLIC, "10.0.0.5")):
            assert is_user_url_allowed("https://x.example/") is False

    @pytest.mark.parametrize("url", [
        None, 42, "", "ftp://x.example/", "file:///etc/passwd", "http:///",
    ])
    def test_non_http_or_hostless_input_is_refused(self, url):
        assert is_user_url_allowed(url) is False  # type: ignore[arg-type]

    def test_unresolvable_or_empty_resolution_is_refused(self):
        with patch("egress.socket.getaddrinfo", side_effect=socket.gaierror):
            assert is_user_url_allowed("https://no-such.invalid/") is False
        with patch("egress.socket.getaddrinfo", return_value=[]):
            assert is_user_url_allowed("https://x.example/") is False


# --- safe_fetch_user_url: the SSRF defenses themselves ----------------------


class _Body:
    """What opener.open() hands back: a context manager with read(n)."""

    def __init__(self, data: bytes):
        self.data = data
        self.asked = None

    def read(self, n):
        self.asked = n
        return self.data[:n]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestSafeFetchUserUrlDefenses:

    def _fetch(self, url, ips, body=b"<title>ok</title>", **kw):
        """Run safe_fetch_user_url with DNS answering ``ips`` and a fake
        opener; returns (result, the Request it sent, the handlers it
        built the opener with, the fake body)."""
        sent = {}
        resp = _Body(body)

        class _Opener:
            def open(self, req, timeout=None):
                sent["req"], sent["timeout"] = req, timeout
                return resp

        def build_opener(*handlers):
            sent["handlers"] = handlers
            return _Opener()

        with patch("egress.socket.getaddrinfo", _resolves_to(*ips)), \
                patch.object(egress.urllib.request, "build_opener", build_opener):
            got = safe_fetch_user_url(url, **kw)
        return got, sent, resp

    @pytest.mark.parametrize("ip", DISALLOWED)
    def test_disallowed_first_answer_never_connects(self, ip):
        got, sent, _ = self._fetch("https://x.example/", [ip])
        assert got is None
        assert "req" not in sent

    def test_disallowed_later_answer_never_connects(self):
        got, sent, _ = self._fetch("https://x.example/", [PUBLIC, "127.0.0.1"])
        assert got is None
        assert "req" not in sent

    def test_connects_to_the_checked_ip_with_the_real_host_header(self):
        got, sent, _ = self._fetch("https://news.example/a?b=1", [PUBLIC])
        assert got == "<title>ok</title>"
        req = sent["req"]
        # DNS rebinding can't swap the address: the URL holds the IP.
        assert req.full_url == f"https://{PUBLIC}/a?b=1"
        assert req.get_header("Host") == "news.example"
        assert req.get_header("User-agent") == "Mozilla/5.0 TaskManager/1.0"
        assert sent["timeout"] == 5.0

    def test_port_is_kept_on_both_the_ip_and_the_host_header(self):
        _, sent, _ = self._fetch("http://news.example:8080/p", [PUBLIC])
        assert sent["req"].full_url == f"http://{PUBLIC}:8080/p"
        assert sent["req"].get_header("Host") == "news.example:8080"

    def test_ipv6_answer_is_bracketed(self):
        _, sent, _ = self._fetch("https://v6.example/", ["2606:2800:220:1::1"])
        assert sent["req"].full_url == "https://[2606:2800:220:1::1]/"

    def test_body_is_capped_at_max_bytes(self):
        got, _, resp = self._fetch(
            "https://x.example/", [PUBLIC], body=b"x" * 100, max_bytes=10,
        )
        assert resp.asked == 10
        assert got == "x" * 10

    def test_bad_utf8_is_replaced_not_raised(self):
        got, _, _ = self._fetch("https://x.example/", [PUBLIC], body=b"ok \xff")
        assert got == "ok �"

    def test_opener_is_built_with_the_no_redirect_handler(self):
        _, sent, _ = self._fetch("https://x.example/", [PUBLIC])
        assert any(isinstance(h, egress._NoRedirect) for h in sent["handlers"])

    def test_no_redirect_handler_refuses_every_redirect(self):
        """A 3xx to localhost must never become a second request: the
        handler returns None, so urllib stops at the 3xx."""
        handler = egress._NoRedirect()
        req = urllib.request.Request("https://x.example/")
        for code in (301, 302, 303, 307, 308):
            assert handler.redirect_request(
                req, None, code, "Moved", {}, "http://127.0.0.1/admin",
            ) is None

    def test_a_network_failure_returns_none(self):
        class _Down:
            def open(self, req, timeout=None):
                raise OSError("connection refused")

        with patch("egress.socket.getaddrinfo", _resolves_to(PUBLIC)), \
                patch.object(egress.urllib.request, "build_opener",
                             lambda *h: _Down()):
            assert safe_fetch_user_url("https://x.example/") is None


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
