"""The claude.ai MCP connector endpoint, ``POST /mcp`` (#522, ADR-044).

Claude in claude.ai (desktop and phone) reaches this app through a custom
connector: a remote MCP server Anthropic's servers call with the
connector's Request header ``authorization: Bearer <token>``. This is a
hand-written, stateless MCP Streamable HTTP server — JSON answers only, no
SSE, no sessions — speaking both protocol eras:

- **2026-07-28** ("modern"): no handshake; every request carries
  ``params._meta["io.modelcontextprotocol/protocolVersion"]`` and the
  ``MCP-Protocol-Version`` / ``Mcp-Method`` (and for ``tools/call``
  ``Mcp-Name``) headers, which must match the body. ``server/discover``
  replaces ``initialize``; every result carries ``resultType: "complete"``.
- **2025-11-25 and earlier** ("legacy"): ``initialize`` then requests; a
  missing ``MCP-Protocol-Version`` header means 2025-03-26.

Security (ADR-044): ``@mcp_token_required`` accepts only the MCP token —
no OAuth session, validator cookie, voice token or dev bypass — and no
other route reads that token. A request with an ``Origin`` other than
claude.ai / claude.com is refused (MCP's DNS-rebinding rule). The tools
(``mcp_tools``) can create, list, complete, edit and move tasks; nothing
deletes, cancels, or reaches goals, settings, exports or auth.
"""

from __future__ import annotations

import base64
import binascii
import re

from flask import Blueprint, Response, jsonify, request

from auth import mcp_token_required
from mcp_tools import SECTIONS, TOOLS, UnknownTool, call_tool
from rate_limit import MCP_LIMIT, limiter
from utils import local_today_date

bp = Blueprint("mcp_api", __name__)

MODERN_VERSION = "2026-07-28"
LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
SUPPORTED_VERSIONS = [MODERN_VERSION, *LEGACY_VERSIONS]
# A legacy request with no MCP-Protocol-Version header (the spec's rule).
_LEGACY_DEFAULT = "2025-03-26"
ALLOWED_ORIGINS = frozenset({"https://claude.ai", "https://claude.com"})
META_VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
SERVER_INFO = {"name": "taskmanager", "title": "Task Manager", "version": "1"}

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
HEADER_MISMATCH = -32020
UNSUPPORTED_VERSION = -32022

_BASE64_NAME = re.compile(r"=\?base64\?(.*)\?=")


class _RpcError(Exception):
    def __init__(self, code: int, message: str, status: int = 400, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.data = data


def build_instructions() -> str:
    today = local_today_date()
    return (
        f"Today is {today.isoformat()} ({today.strftime('%A')}) in the user's time zone. "
        "This is the user's personal task manager. Tasks are Work or Personal and sit in "
        f"one board section: {', '.join(SECTIONS)}. A new task goes to the Inbox unless a "
        "due date or section places it; a due date files it to the section that date "
        "falls in. Write dates as YYYY-MM-DD. Projects are named by their exact name and "
        "must be of the task's type. You can create, list, complete, edit and move tasks; "
        "you cannot delete or cancel them. Use list_tasks to find a task's id."
    )


def _rpc_error(req_id, code: int, message: str, status: int, data: dict | None = None):
    error: dict = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return jsonify(jsonrpc="2.0", id=req_id, error=error), status


@bp.before_request
def _check_origin():
    origin = request.headers.get("Origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        return _rpc_error(None, INVALID_REQUEST, "Forbidden origin", 403)
    return None


def _decode_name(value: str) -> str | None:
    m = _BASE64_NAME.fullmatch(value)
    if not m:
        return value
    try:
        return base64.b64decode(m.group(1), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None


def _check_modern_headers(method: str, params: dict, version: str) -> None:
    if request.headers.get("MCP-Protocol-Version") != version:
        raise _RpcError(HEADER_MISMATCH, "MCP-Protocol-Version header doesn't match _meta")
    if request.headers.get("Mcp-Method") != method:
        raise _RpcError(HEADER_MISMATCH, "Mcp-Method header doesn't match method")
    if method == "tools/call":
        raw = request.headers.get("Mcp-Name")
        if raw is None or _decode_name(raw) != params.get("name"):
            raise _RpcError(HEADER_MISMATCH, "Mcp-Name header doesn't match params.name")


def _tools_call(params: dict) -> dict:
    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(name, str):
        raise _RpcError(INVALID_PARAMS, "params.name must be a tool name")
    if not isinstance(arguments, dict):
        raise _RpcError(INVALID_PARAMS, "params.arguments must be an object")
    try:
        return call_tool(name, arguments)
    except UnknownTool as e:
        raise _RpcError(INVALID_PARAMS, f"Unknown tool: {name}") from e


def _dispatch(method: str, params: dict, *, modern: bool) -> dict:
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        return _tools_call(params)
    if method == "ping":
        return {}
    if modern and method == "server/discover":
        return {
            "supportedVersions": SUPPORTED_VERSIONS,
            "capabilities": {"tools": {}},
            "instructions": build_instructions(),
            "_meta": {"serverInfo": SERVER_INFO},
        }
    if not modern and method == "initialize":
        asked = params.get("protocolVersion")
        return {
            "protocolVersion": asked if asked in LEGACY_VERSIONS else LEGACY_VERSIONS[0],
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
            "instructions": build_instructions(),
        }
    raise _RpcError(METHOD_NOT_FOUND, f"Method not found: {method}", status=404)


@bp.post("/mcp")
@limiter.limit(MCP_LIMIT)
@mcp_token_required
def mcp_endpoint():
    """MCP connector for claude.ai: create, list, complete, edit and move tasks."""
    body = request.get_json(silent=True, force=True)
    if body is None:
        return _rpc_error(None, PARSE_ERROR, "Parse error", 400)
    if isinstance(body, list):
        return _rpc_error(None, INVALID_REQUEST, "Batches are not supported", 400)
    if (
        not isinstance(body, dict)
        or body.get("jsonrpc") != "2.0"
        or not isinstance(body.get("method"), str)
    ):
        return _rpc_error(
            body.get("id") if isinstance(body, dict) else None,
            INVALID_REQUEST,
            "Invalid request",
            400,
        )
    if "id" not in body:
        # A notification (incl. notifications/initialized): nothing to answer.
        return Response(status=202)

    req_id = body["id"]
    method = body["method"]
    params = body.get("params") or {}
    if not isinstance(params, dict):
        return _rpc_error(req_id, INVALID_PARAMS, "params must be an object", 400)
    meta = params.get("_meta")
    version = meta.get(META_VERSION_KEY) if isinstance(meta, dict) else None
    modern = version is not None

    try:
        if modern:
            if version != MODERN_VERSION:
                raise _RpcError(
                    UNSUPPORTED_VERSION,
                    f"Unsupported protocol version: {version}",
                    data={"supported": SUPPORTED_VERSIONS, "requested": version},
                )
            _check_modern_headers(method, params, version)
        else:
            header = request.headers.get("MCP-Protocol-Version", _LEGACY_DEFAULT)
            if header not in LEGACY_VERSIONS:
                raise _RpcError(INVALID_REQUEST, f"Unsupported protocol version: {header}")
        result = _dispatch(method, params, modern=modern)
    except _RpcError as e:
        # Modern clients read the HTTP status; legacy ones read the
        # JSON-RPC error in a 200, except for a bad version header.
        status = e.status if modern or e.code == INVALID_REQUEST else 200
        return _rpc_error(req_id, e.code, e.message, status, e.data)

    if modern:
        result = {**result, "resultType": "complete"}
    return jsonify(jsonrpc="2.0", id=req_id, result=result)
