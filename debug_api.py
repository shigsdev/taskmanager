"""Debug/diagnostic endpoints — single-user locked via login_required.

Endpoints:
    GET  /api/debug/logs          — query recent AppLog rows
    POST /api/debug/client-error  — receive browser-side errors

Security: both endpoints sit behind ``login_required`` which enforces
the ``AUTHORIZED_EMAIL`` match. Even though the data here is
post-scrub, it's still more detail than a normal UI should expose, so
we keep the same single-user lockdown as every other route.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from auth import login_required
from logging_service import scrub_sensitive
from models import AppLog, db

# Numeric ordering so ?level=WARNING returns WARNING, ERROR, and CRITICAL
# — matches standard Python logging "this level and above" semantics.
_LEVEL_RANK = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}

logger = logging.getLogger("taskmanager.debug")

bp = Blueprint("debug_api", __name__, url_prefix="/api/debug")

# --- Constants ---------------------------------------------------------------

DEFAULT_LIMIT = 100
MAX_LIMIT = 500
DEFAULT_SINCE_MINUTES = 60

# Levels we recognize for filtering (anything else → 400)
VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _parse_since(raw: str | None) -> datetime:
    """Parse a ``since`` query param.

    Accepts either:
    - A shorthand like ``10m``, ``2h``, ``1d``
    - An ISO-8601 timestamp
    Defaults to ``DEFAULT_SINCE_MINUTES`` ago.
    """
    if not raw:
        return datetime.now(UTC) - timedelta(minutes=DEFAULT_SINCE_MINUTES)

    raw = raw.strip()
    # URL-encoding of '+' becomes ' ' — repair before ISO parsing so
    # timezones like "+00:00" survive the round trip.
    iso_candidate = raw.replace(" ", "+")

    # Shorthand check: <number><unit> like "10m" / "2h" / "1d".
    # Only consider shorthand if the whole thing is short and all-digits
    # plus the unit suffix — avoids swallowing a year like "2026".
    short = raw.lower()
    if (
        len(short) <= 5
        and short[-1:] in "smhd"
        and short[:-1].isdigit()
    ):
        n = int(short[:-1])
        unit = short[-1]
        delta = {
            "s": timedelta(seconds=n),
            "m": timedelta(minutes=n),
            "h": timedelta(hours=n),
            "d": timedelta(days=n),
        }[unit]
        return datetime.now(UTC) - delta

    # ISO-8601
    try:
        parsed = datetime.fromisoformat(iso_candidate)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    except ValueError as e:
        raise ValueError(f"invalid 'since' value: {raw!r}") from e


# --- GET /api/debug/logs -----------------------------------------------------


@bp.get("/logs")
@login_required
def get_logs(email: str):  # noqa: ARG001
    """Query recent app_logs rows.

    Query params:
    - since   — shorthand (10m/2h/1d) or ISO-8601. Default: 1h ago.
    - level   — DEBUG|INFO|WARNING|ERROR|CRITICAL. Default: all.
    - route   — filter by route prefix (startswith).
    - limit   — max rows to return. Default 100, cap 500.
    - source  — "server" or "client". Default: both.

    Returns newest-first.
    """
    try:
        since = _parse_since(request.args.get("since"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    level = request.args.get("level")
    if level:
        level = level.upper()
        if level not in VALID_LEVELS:
            return jsonify({
                "error": f"invalid level: {level}",
                "valid": sorted(VALID_LEVELS),
            }), 400

    route_prefix = request.args.get("route")
    source = request.args.get("source")

    try:
        limit = int(request.args.get("limit", DEFAULT_LIMIT))
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400
    limit = max(1, min(limit, MAX_LIMIT))

    stmt = select(AppLog).where(AppLog.timestamp >= since)
    if level:
        # "WARNING and above" semantics — include every level with rank
        # >= the requested level, matching standard logging behavior.
        min_rank = _LEVEL_RANK[level]
        included = [
            name for name, rank in _LEVEL_RANK.items() if rank >= min_rank
        ]
        stmt = stmt.where(AppLog.level.in_(included))
    if route_prefix:
        stmt = stmt.where(AppLog.route.like(f"{route_prefix}%"))
    if source:
        stmt = stmt.where(AppLog.source == source)
    stmt = stmt.order_by(AppLog.timestamp.desc()).limit(limit)

    rows = list(db.session.scalars(stmt))

    return jsonify({
        "count": len(rows),
        "since": since.isoformat(),
        "limit": limit,
        "logs": [
            {
                "id": str(row.id),
                "timestamp": row.timestamp.isoformat(),
                "level": row.level,
                "logger": row.logger_name,
                "message": row.message,
                "traceback": row.traceback,
                "request_id": row.request_id,
                "route": row.route,
                "method": row.method,
                "status_code": row.status_code,
                "source": row.source,
            }
            for row in rows
        ],
    })


# --- POST /api/debug/client-error --------------------------------------------


@bp.post("/client-error")
@login_required
def client_error(email: str):  # noqa: ARG001
    """Receive a browser-side error report.

    Expected JSON body:
    {
        "message": str,
        "stack": str (optional),
        "url": str (optional),
        "userAgent": str (optional),
        "line": int (optional),
        "column": int (optional)
    }

    We don't persist raw HTML/DOM snapshots — just the message, stack,
    and the page URL so we can correlate with server logs via the
    route field.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    raw_msg = data.get("message") or "(no message)"
    raw_stack = data.get("stack")
    url = data.get("url") or ""
    user_agent = data.get("userAgent") or ""
    line = data.get("line")
    column = data.get("column")

    # Build a combined message so it's readable in one row.
    parts = [str(raw_msg)]
    if line is not None or column is not None:
        parts.append(f"at line={line} col={column}")
    if url:
        parts.append(f"url={url}")
    if user_agent:
        parts.append(f"ua={user_agent}")
    combined = " | ".join(parts)

    # Log via Python logging so the DBLogHandler picks it up — but
    # override the source and include the stack as exc_info-style.
    scrubbed_msg = scrub_sensitive(combined) or combined
    scrubbed_stack = scrub_sensitive(str(raw_stack)) if raw_stack else None

    record = logger.makeRecord(
        name="taskmanager.client",
        level=logging.ERROR,
        fn="(client)",
        lno=0,
        msg=scrubbed_msg,
        args=(),
        exc_info=None,
    )
    # Source="client" so /api/debug/logs?source=client can filter.
    record.source = "client"
    # DBLogHandler picks up traceback_override as a fallback when
    # exc_info is not set (browser errors don't have Python excinfo).
    if scrubbed_stack:
        record.traceback_override = scrubbed_stack

    logger.handle(record)

    return jsonify({"ok": True}), 201
