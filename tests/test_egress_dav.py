"""egress.safe_call_dav -- the read-only WebDAV path for iCloud (#371, ADR-041).

It is the only egress call that sends a user's Apple credentials, so the
refusals matter more than the happy path: no method but PROPFIND / REPORT,
no plain http, no host the caller doesn't allow, no redirect followed, and
an error that carries the HTTP status but never the URL or a credential.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from egress import EgressError, safe_call_dav


def _icloud(host: str) -> bool:
    return host in ("caldav.icloud.com", "p42-caldav.icloud.com")


def _call(**over):
    kw = {
        "method": "PROPFIND",
        "url": "https://caldav.icloud.com/",
        "headers": {"Authorization": "Basic c2VjcmV0OnB3", "Depth": "0"},
        "body": "<d:propfind xmlns:d='DAV:'/>",
        "vendor": "iCloud",
        "host_allowed": _icloud,
    }
    kw.update(over)
    return safe_call_dav(**kw)


def _resp(status: int, text: str = "<multistatus/>"):
    r = MagicMock(status_code=status, text=text)
    r.ok = 200 <= status < 400
    return r


class TestSafeCallDavHappyPath:

    def test_returns_text_of_a_207(self):
        with patch("egress.requests.request", return_value=_resp(207, "<ok/>")) as m:
            assert _call() == "<ok/>"
        args, kwargs = m.call_args
        assert args == ("PROPFIND", "https://caldav.icloud.com/")
        assert kwargs["allow_redirects"] is False
        assert kwargs["headers"]["Depth"] == "0"
        assert kwargs["data"] == b"<d:propfind xmlns:d='DAV:'/>"
        assert kwargs["timeout"] == 10.0

    def test_report_on_the_partition_host_is_allowed(self):
        with patch("egress.requests.request", return_value=_resp(207)) as m:
            _call(method="REPORT", url="https://p42-caldav.icloud.com:443/1/calendars/home/")
        assert m.call_args[0][0] == "REPORT"


class TestSafeCallDavRefusals:

    @pytest.mark.parametrize("method", ["PUT", "DELETE", "PROPPATCH", "POST", "GET", "MKCALENDAR"])
    def test_any_write_or_other_method_is_refused_before_the_network(self, method):
        with patch("egress.requests.request") as m, pytest.raises(EgressError):
            _call(method=method)
        m.assert_not_called()

    def test_plain_http_is_refused(self):
        with patch("egress.requests.request") as m, pytest.raises(EgressError):
            _call(url="http://caldav.icloud.com/")
        m.assert_not_called()

    @pytest.mark.parametrize("url", [
        "https://evil.example.com/",
        "https://caldav.icloud.com.evil.example.com/",
        "https://127.0.0.1/",
        "https:///nohost",
    ])
    def test_a_host_the_caller_does_not_allow_is_refused(self, url):
        with patch("egress.requests.request") as m, pytest.raises(EgressError):
            _call(url=url)
        m.assert_not_called()

    @pytest.mark.parametrize("status", [301, 302, 307, 308])
    def test_a_redirect_is_not_followed_and_is_an_error(self, status):
        with patch("egress.requests.request", return_value=_resp(status)), \
                pytest.raises(EgressError) as ei:
            _call()
        assert ei.value.status == status

    @pytest.mark.parametrize("status", [401, 403, 404, 500, 503])
    def test_an_http_error_carries_its_status(self, status):
        with patch("egress.requests.request", return_value=_resp(status, "nope")), \
                pytest.raises(EgressError) as ei:
            _call()
        assert ei.value.status == status
        assert str(status) in str(ei.value)

    def test_a_network_error_has_no_status_and_no_url_or_credential(self):
        boom = requests.ConnectionError("https://caldav.icloud.com/?x Basic c2VjcmV0OnB3")
        with patch("egress.requests.request", side_effect=boom), \
                pytest.raises(EgressError) as ei:
            _call()
        msg = str(ei.value)
        assert ei.value.status is None
        assert "icloud.com" not in msg
        assert "c2VjcmV0OnB3" not in msg
        assert ei.value.__cause__ is boom

    def test_an_error_message_never_echoes_the_url(self):
        with patch("egress.requests.request", return_value=_resp(500, "")), \
                pytest.raises(EgressError) as ei:
            _call(url="https://p42-caldav.icloud.com/123456789/calendars/")
        assert "123456789" not in str(ei.value)


class TestEgressErrorStatus:

    def test_status_defaults_to_none_so_old_callers_are_unchanged(self):
        e = EgressError("x")
        assert e.status is None
        assert str(e) == "x"
