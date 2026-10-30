"""Protocol + scope tests for ``POST /mcp`` (#522 / ADR-044).

The endpoint speaks stateless MCP Streamable HTTP with JSON answers, in
both eras: 2026-07-28 (every request carries ``_meta`` and the
``MCP-Protocol-Version`` / ``Mcp-Method`` / ``Mcp-Name`` headers) and the
older ``initialize`` handshake. It accepts ONLY the MCP token, sent as
``Authorization: Bearer <token>`` — the scope rows below are the
load-bearing security property: if any "refused" row ever answers 2xx,
ADR-044's guarantee is broken.
"""

from __future__ import annotations

import base64
import logging

import pytest

import mcp_token
import rate_limit
import validator_cookie
import voice_action_token
import voice_token_service
from models import Task
from models import db as _db
from utils import local_today_date

SECRET = "test-secret"
EMAIL = "me@example.com"
MODERN = "2026-07-28"
META_KEY = "io.modelcontextprotocol/protocolVersion"
SUPPORTED = ["2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26"]


def _tok(**kw) -> str:
    return mcp_token.mint(SECRET, EMAIL, **kw)


def _auth(token: str | None = None) -> dict:
    return {"Authorization": f"Bearer {token or _tok()}"}


def _modern(client, method, params=None, *, id=1, headers=None, drop=(), token=None):
    """A 2026-07-28 request with every header set to match the body;
    ``headers`` overrides, ``drop`` removes."""
    params = dict(params or {})
    params["_meta"] = {META_KEY: MODERN, **params.get("_meta", {})}
    body = {"jsonrpc": "2.0", "id": id, "method": method, "params": params}
    hdrs = {**_auth(token), "MCP-Protocol-Version": MODERN, "Mcp-Method": method}
    if method == "tools/call":
        hdrs["Mcp-Name"] = params.get("name", "")
    hdrs.update(headers or {})
    for name in drop:
        hdrs.pop(name, None)
    return client.post("/mcp", json=body, headers=hdrs)


def _legacy(client, method, params=None, *, id=1, headers=None, token=None):
    body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if id is not None:
        body["id"] = id
    return client.post("/mcp", json=body, headers={**_auth(token), **(headers or {})})


def _create_params(title="From Claude"):
    return {"name": "create_task", "arguments": {"title": title, "type": "work"}}


def _error_code(resp) -> int:
    return resp.get_json()["error"]["code"]


class TestModern:
    def test_discover(self, client):
        resp = _modern(client, "server/discover")
        assert resp.status_code == 200
        result = resp.get_json()["result"]
        assert result["supportedVersions"] == SUPPORTED
        assert result["capabilities"] == {"tools": {}}
        assert result["resultType"] == "complete"
        assert result["_meta"]["serverInfo"]["name"] == "taskmanager"
        assert resp.get_json()["id"] == 1

    def test_instructions_carry_today(self, client):
        result = _modern(client, "server/discover").get_json()["result"]
        assert local_today_date().isoformat() in result["instructions"]

    def test_tools_list_modern(self, client):
        result = _modern(client, "tools/list").get_json()["result"]
        assert [t["name"] for t in result["tools"]] == [
            "create_task",
            "list_tasks",
            "complete_task",
            "update_task",
            "move_task",
        ]
        assert result["resultType"] == "complete"

    def test_tools_call_modern_creates_task(self, client):
        resp = _modern(client, "tools/call", _create_params())
        assert resp.status_code == 200, resp.get_json()
        result = resp.get_json()["result"]
        assert result["isError"] is False
        assert result["resultType"] == "complete"
        assert Task.query.filter_by(title="From Claude").count() == 1

    def test_ping_modern(self, client):
        resp = _modern(client, "ping")
        assert resp.status_code == 200
        assert resp.get_json()["result"] == {"resultType": "complete"}

    def test_unknown_method_modern_404(self, client):
        resp = _modern(client, "resources/list")
        assert resp.status_code == 404
        assert _error_code(resp) == -32601


class TestHeaderMismatch:
    @pytest.mark.parametrize(
        "method,kwargs",
        [
            ("tools/list", {"drop": ["MCP-Protocol-Version"]}),
            ("tools/list", {"headers": {"MCP-Protocol-Version": "2025-11-25"}}),
            ("tools/list", {"headers": {"Mcp-Method": "tools/call"}}),
            ("tools/list", {"drop": ["Mcp-Method"]}),
            ("tools/call", {"drop": ["Mcp-Name"]}),
            ("tools/call", {"headers": {"Mcp-Name": "move_task"}}),
            ("tools/call", {"headers": {"Mcp-Name": "=?base64?!!notbase64?="}}),
        ],
        ids=[
            "missing-version",
            "version-differs",
            "method-differs",
            "missing-method",
            "missing-name",
            "name-differs",
            "name-bad-base64",
        ],
    )
    def test_header_mismatch_is_400(self, client, method, kwargs):
        params = _create_params() if method == "tools/call" else None
        resp = _modern(client, method, params, **kwargs)
        assert resp.status_code == 400
        assert _error_code(resp) == -32020
        assert Task.query.count() == 0

    def test_mcp_name_base64_accepted(self, client):
        encoded = base64.b64encode(b"create_task").decode()
        resp = _modern(
            client, "tools/call", _create_params(), headers={"Mcp-Name": f"=?base64?{encoded}?="}
        )
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["result"]["isError"] is False

    def test_unsupported_modern_version(self, client):
        resp = _modern(
            client,
            "tools/list",
            {"_meta": {META_KEY: "2027-01-01"}},
            headers={"MCP-Protocol-Version": "2027-01-01"},
        )
        assert resp.status_code == 400
        error = resp.get_json()["error"]
        assert error["code"] == -32022
        assert error["data"]["supported"] == SUPPORTED


class TestLegacy:
    def test_legacy_initialize_echoes_known_version(self, client):
        result = _legacy(client, "initialize", {"protocolVersion": "2025-06-18"}).get_json()[
            "result"
        ]
        assert result["protocolVersion"] == "2025-06-18"
        assert result["capabilities"] == {"tools": {}}
        assert result["serverInfo"]["name"] == "taskmanager"
        assert local_today_date().isoformat() in result["instructions"]
        assert "resultType" not in result

    def test_legacy_initialize_unknown_version_gets_latest_legacy(self, client):
        result = _legacy(client, "initialize", {"protocolVersion": "2024-11-05"}).get_json()[
            "result"
        ]
        assert result["protocolVersion"] == "2025-11-25"

    def test_legacy_flow(self, client):
        init = _legacy(client, "initialize", {"protocolVersion": "2025-11-25"})
        assert init.status_code == 200
        assert "Mcp-Session-Id" not in init.headers
        note = _legacy(client, "notifications/initialized", id=None)
        assert note.status_code == 202
        listed = _legacy(client, "tools/list", id=2)
        assert len(listed.get_json()["result"]["tools"]) == 5
        called = _legacy(client, "tools/call", _create_params("Legacy"), id=3)
        assert called.status_code == 200
        assert called.get_json()["result"]["isError"] is False
        assert Task.query.filter_by(title="Legacy").count() == 1

    def test_legacy_unknown_method(self, client):
        resp = _legacy(client, "resources/list")
        assert resp.status_code == 200
        assert _error_code(resp) == -32601

    def test_legacy_bad_version_header(self, client):
        resp = _legacy(client, "tools/list", headers={"MCP-Protocol-Version": "1999-01-01"})
        assert resp.status_code == 400

    def test_legacy_known_version_header(self, client):
        resp = _legacy(client, "tools/list", headers={"MCP-Protocol-Version": "2025-06-18"})
        assert resp.status_code == 200


class TestEnvelope:
    def test_notification_202_no_body(self, client):
        resp = _legacy(client, "notifications/cancelled", {"requestId": 1}, id=None)
        assert resp.status_code == 202
        assert resp.data == b""

    def test_id_zero_is_answered(self, client):
        resp = _legacy(client, "ping", id=0)
        assert resp.status_code == 200
        assert resp.get_json()["id"] == 0

    def test_batch_rejected(self, client):
        body = [{"jsonrpc": "2.0", "id": 1, "method": "ping"}]
        resp = client.post("/mcp", json=body, headers=_auth())
        assert resp.status_code == 400
        assert _error_code(resp) == -32600

    @pytest.mark.parametrize("data", ["not json", ""])
    def test_non_json_body_is_parse_error(self, client, data):
        resp = client.post("/mcp", data=data, headers=_auth(), content_type="text/plain")
        assert resp.status_code == 400
        assert _error_code(resp) == -32700

    @pytest.mark.parametrize(
        "body",
        ["hello", {"id": 1, "method": "ping"}, {"jsonrpc": "2.0", "id": 1, "method": 5}],
    )
    def test_non_object_json_is_invalid_request(self, client, body):
        resp = client.post("/mcp", json=body, headers=_auth())
        assert resp.status_code == 400
        assert _error_code(resp) == -32600

    def test_get_and_delete_are_405(self, client):
        assert client.get("/mcp", headers=_auth()).status_code == 405
        assert client.delete("/mcp", headers=_auth()).status_code == 405

    def test_unknown_tool_is_32602(self, client):
        resp = _legacy(client, "tools/call", {"name": "delete_task", "arguments": {}})
        assert _error_code(resp) == -32602
        resp = _modern(client, "tools/call", {"name": "delete_task", "arguments": {}})
        assert resp.status_code == 400
        assert _error_code(resp) == -32602

    def test_arguments_not_object_is_32602(self, client):
        resp = _legacy(client, "tools/call", {"name": "create_task", "arguments": ["x"]})
        assert _error_code(resp) == -32602


class TestOrigin:
    def test_foreign_origin_403(self, client):
        resp = _legacy(client, "ping", headers={"Origin": "https://evil.example"})
        assert resp.status_code == 403

    @pytest.mark.parametrize("origin", ["https://claude.ai", "https://claude.com"])
    def test_claude_origins_allowed(self, client, origin):
        assert _legacy(client, "ping", headers={"Origin": origin}).status_code == 200

    def test_no_origin_allowed(self, client):
        assert _legacy(client, "ping").status_code == 200


def _unauthorized(resp) -> None:
    assert resp.status_code == 401
    body = resp.get_json()
    assert body["error"]["code"] == -32001
    assert body["id"] is None


def _ping_body():
    return {"jsonrpc": "2.0", "id": 1, "method": "ping"}


class TestAuth:
    def test_no_token_401(self, client):
        _unauthorized(client.post("/mcp", json=_ping_body()))

    def test_bad_token_401(self, client):
        _unauthorized(client.post("/mcp", json=_ping_body(), headers=_auth("garbage")))

    def test_revoked_token_401(self, client):
        token = _tok(jti="feedfacefeedface")
        voice_token_service.add_jti_to_denylist(mcp_token.REVOKED_JTIS_KEY, "feedfacefeedface")
        _db.session.commit()
        _unauthorized(client.post("/mcp", json=_ping_body(), headers=_auth(token)))

    def test_expired_token_401(self, client, monkeypatch):
        import time

        real = time.time
        monkeypatch.setattr(time, "time", lambda: real() - 3 * 86400)
        token = _tok(days=1)
        monkeypatch.setattr(time, "time", real)
        _unauthorized(client.post("/mcp", json=_ping_body(), headers=_auth(token)))

    def test_lowercase_bearer_accepted(self, client):
        # RFC 7235: the scheme is case-insensitive, and the value is typed
        # by hand into a dialog that never shows it again.
        headers = {"Authorization": f"bearer {_tok()}"}
        assert client.post("/mcp", json=_ping_body(), headers=headers).status_code == 200

    def test_token_in_path_is_not_a_route(self, client):
        assert client.post(f"/mcp/{_tok()}", json=_ping_body()).status_code == 404

    def test_mcp_token_refused_on_api_tasks(self, client):
        assert client.get("/api/tasks", headers=_auth()).status_code == 401

    def test_mcp_token_refused_on_voice_review(self, client):
        assert client.get("/api/voice-review/queue", headers=_auth()).status_code == 401

    def test_voice_token_refused_on_mcp(self, client):
        voice = voice_action_token.mint(SECRET, EMAIL, days=90)
        _unauthorized(client.post("/mcp", json=_ping_body(), headers=_auth(voice)))

    def test_validator_cookie_refused_on_mcp(self, client):
        client.set_cookie(validator_cookie.COOKIE_NAME, validator_cookie.mint(SECRET, EMAIL, 90))
        _unauthorized(client.post("/mcp", json=_ping_body()))

    def test_oauth_session_refused_on_mcp(self, authed_client):
        _unauthorized(authed_client.post("/mcp", json=_ping_body()))

    def test_dev_bypass_does_not_open_mcp(self, client, monkeypatch):
        monkeypatch.setenv("LOCAL_DEV_BYPASS_AUTH", "1")
        monkeypatch.setenv("AUTHORIZED_EMAIL", EMAIL)
        import auth

        assert auth._dev_bypass_active()
        _unauthorized(client.post("/mcp", json=_ping_body()))


class TestRateLimit:
    @pytest.fixture
    def limiter_on(self, app):
        rate_limit.limiter.enabled = True
        app.config["RATELIMIT_ENABLED"] = True
        rate_limit.limiter.init_app(app)
        rate_limit.limiter.reset()
        yield
        rate_limit.limiter.enabled = False
        rate_limit.limiter.reset()

    def test_rate_limited_at_60_per_minute(self, client, limiter_on):
        headers = _auth()
        for _ in range(60):
            assert client.post("/mcp", json=_ping_body(), headers=headers).status_code == 200
        assert client.post("/mcp", json=_ping_body(), headers=headers).status_code == 429


def test_token_never_logged(client, caplog):
    caplog.set_level(logging.DEBUG)
    token = _tok()
    _legacy(client, "initialize", {"protocolVersion": "2025-11-25"}, token=token)
    _legacy(client, "tools/call", _create_params(), id=2, token=token)
    assert Task.query.count() == 1
    assert not any(token in r.getMessage() for r in caplog.records)
