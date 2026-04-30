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

import hmac
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from functools import wraps

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from auth import login_required
from logging_service import scrub_sensitive
from models import AppLog, db

# PR62 audit fix #24: strip C0 control characters (0x00-0x1F) and DEL
# (0x7F) from user-supplied log fields so an attacker can't inject
# fake-looking log lines via embedded newlines/CRs into rows visible
# through /api/debug/logs. Newlines inside `stack` are legitimate and
# stripping there would corrupt traces — so this regex only applies to
# fields concatenated into the single-line `combined` log message.
_CTRL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


# Numeric ordering so ?level=WARNING returns WARNING, ERROR, and CRITICAL
# — matches standard Python logging "this level and above" semantics.
_LEVEL_RANK = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


# --- Debug token auth --------------------------------------------------------
#
# Two-tier token model (PR65 / audit fix #126):
#
#   1. Normal OAuth (login_required) — for the human developer in a browser.
#      Always trusted for everything.
#
#   2. X-Debug-Token header matching APP_DEBUG_TOKEN — READ-ONLY token, used
#      by automation that needs to query /api/debug/logs without a session.
#      Decorator: ``debug_auth_required``. The READ token explicitly does
#      NOT authenticate mutating endpoints — if the read token leaks (Slack
#      paste during a debug session, shell history grep) an attacker still
#      cannot rewrite tier/goal/project assignments.
#
#   3. X-Debug-Token header matching APP_DEBUG_ADMIN_TOKEN — ADMIN token,
#      required for mutating one-shot endpoints (/backfill/*, /realign-tiers).
#      Decorator: ``debug_admin_auth_required``. Used rarely (typically once
#      per migration), so the value can be rotated frequently. OAuth still
#      passes both decorators — the split only constrains the token path.
#
# Both tokens are optional — when an env var is unset, the corresponding
# token path is disabled and only OAuth works on those routes.
#
# Every token-authenticated access is logged as WARNING so the developer
# sees it in the same app_logs table the read token is used to query.


def _check_token_match(env_var: str) -> bool:
    """Compare X-Debug-Token to ``os.environ[env_var]`` via constant-time.

    Returns True iff the env var is set, the header is present, and the
    two match exactly. Compared with ``hmac.compare_digest`` to prevent
    timing attacks.
    """
    provided = request.headers.get("X-Debug-Token")
    expected = os.environ.get(env_var)
    if not (expected and provided):
        return False
    return hmac.compare_digest(
        provided.encode("utf-8"), expected.encode("utf-8")
    )


def debug_auth_required(view):
    """Allow OAuth OR a matching APP_DEBUG_TOKEN header (read-only scope).

    Use this for read-only debug endpoints (/api/debug/logs, /summary,
    /client-error). APP_DEBUG_ADMIN_TOKEN ALSO satisfies this — admin
    is strictly more privileged than read.
    """
    oauth_guarded = login_required(view)

    @wraps(view)
    def wrapped(*args, **kwargs):
        if _check_token_match("APP_DEBUG_TOKEN") or _check_token_match(
            "APP_DEBUG_ADMIN_TOKEN"
        ):
            logger.warning(  # nosemgrep
                "debug endpoint accessed via header-auth path: %s %s",
                request.method,
                request.path,
            )
            return view(*args, email="<debug-token>", **kwargs)
        return oauth_guarded(*args, **kwargs)

    return wrapped


def debug_admin_auth_required(view):
    """Allow OAuth OR a matching APP_DEBUG_ADMIN_TOKEN header.

    Use this for mutating debug endpoints (/api/debug/backfill/*,
    /api/debug/realign-tiers). The READ token (APP_DEBUG_TOKEN) does
    NOT pass this gate — that's the whole point of the split.

    PR65 / audit fix #126: prior to this split, APP_DEBUG_TOKEN
    authenticated EVERY debug endpoint including state-rewriting
    backfills. A leaked read token (paste into Slack, shell history)
    would then authorize wholesale tier/goal/project rewrites.
    """
    oauth_guarded = login_required(view)

    @wraps(view)
    def wrapped(*args, **kwargs):
        if _check_token_match("APP_DEBUG_ADMIN_TOKEN"):
            logger.warning(  # nosemgrep
                "admin debug endpoint accessed via header-auth path: %s %s",
                request.method,
                request.path,
            )
            return view(*args, email="<admin-debug-token>", **kwargs)
        return oauth_guarded(*args, **kwargs)

    return wrapped

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
@debug_auth_required
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
        # PR28 audit fix #7: escape LIKE wildcards (% _) so a query
        # string like ?route=% doesn't expand to a much broader filter
        # than the user intended ("starts with literal text" semantics).
        # SQL injection is already blocked by parameterization; this is
        # about correctness of the prefix match.
        escaped = route_prefix.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_")
        stmt = stmt.where(AppLog.route.like(f"{escaped}%", escape="\\"))
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
@debug_auth_required
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

    # PR62 audit fix #12: cap each user-controlled field length BEFORE
    # any concatenation. The DBLogHandler trims at 10/20 KB but that's
    # post-truncation of the *combined* message. A 50 KB stack + 50 KB
    # message + 50 KB url = 150 KB through the log path before truncation,
    # which is wasted I/O. Each field gets a tight per-field cap here.
    def _capped(raw, max_len):
        if raw is None:
            return ""
        s = str(raw)
        return s if len(s) <= max_len else s[:max_len] + "...[truncated]"

    # PR62 audit fix #24: strip control chars from each field before
    # joining with " | ". Without this, a `\n` in `message` lets the
    # injected text fake a separate log entry when anyone views logs as
    # plain text. Newlines are legitimate inside `stack` (which we don't
    # join), so we only strip from the joined fields.
    def _no_ctrl(s):
        return _CTRL_CHARS_RE.sub(" ", s)

    raw_msg = _no_ctrl(_capped(data.get("message") or "(no message)", 2000))
    raw_stack = _capped(data.get("stack"), 8000) if data.get("stack") else None
    url = _no_ctrl(_capped(data.get("url"), 1000))
    user_agent = _no_ctrl(_capped(data.get("userAgent"), 500))
    line = data.get("line")
    column = data.get("column")

    # Build a combined message so it's readable in one row.
    parts = [raw_msg]
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


# --- One-shot admin backfills (#77 etc.) ------------------------------------


@bp.post("/backfill/task-goal-from-project")
@debug_admin_auth_required  # PR65 #126: write endpoint requires admin token
def backfill_task_goal_from_project(email: str):  # noqa: ARG001
    """#77 (2026-04-26): one-shot — set every task's goal_id to its
    project's goal_id (overwriting whatever's there).

    Idempotent: re-running is a no-op when already in sync. Logs an
    INFO row with the count so the run is auditable in /api/debug/logs.

    Triggers the same logic as scripts/backfill_task_goal_from_project.py
    but runs INSIDE the Railway environment so postgres.railway.internal
    resolves. Use when local `railway run` can't reach the internal DB.

    Auth: same X-Debug-Token as the rest of /api/debug/*.

    Returns: {"tasks_with_project": N, "updated": N, "orphans": [uuid, ...]}.
    """
    from models import Project, Task, db

    tasks_with_project = list(db.session.scalars(
        select(Task).where(Task.project_id.is_not(None))
    ))
    projects_by_id = {p.id: p for p in db.session.scalars(select(Project))}

    updated = 0
    orphans: list[str] = []
    for t in tasks_with_project:
        proj = projects_by_id.get(t.project_id)
        if proj is None:
            orphans.append(str(t.id))
            continue
        new_goal_id = proj.goal_id
        if t.goal_id != new_goal_id:
            t.goal_id = new_goal_id
            updated += 1
    db.session.commit()
    logger.info(
        "backfill task_goal_from_project: tasks_with_project=%d updated=%d orphans=%d",
        len(tasks_with_project), updated, len(orphans),
    )
    return jsonify({
        "tasks_with_project": len(tasks_with_project),
        "updated": updated,
        "orphans": orphans,
    }), 200


@bp.post("/realign-tiers")
@debug_admin_auth_required  # PR65 #126: write endpoint requires admin token
def realign_tiers(email: str):  # noqa: ARG001
    """#108 (PR43, 2026-04-27): one-shot — re-route every active task
    whose tier no longer matches its due_date.

    Same logic as the new 00:03 cron, but available on-demand for
    immediate cleanup of existing drifted state. User-reported bug:
    a recurring task spawned days ago with due=Apr 28 sat in
    THIS_WEEK; today (Apr 27) Apr 28 is "tomorrow" but the tier
    didn't auto-update.

    Idempotent. Auth: X-Debug-Token. Returns: {"updated": N}.
    """
    from task_service import realign_tiers_with_due_dates
    n = realign_tiers_with_due_dates()
    logger.info("realign_tiers ad-hoc: updated=%d", n)
    return jsonify({"updated": n}), 200


@bp.post("/backfill/today-tomorrow-due-date")
@debug_admin_auth_required  # PR65 #126: write endpoint requires admin token
def backfill_today_tomorrow_due_date(email: str):  # noqa: ARG001
    """#100 (2026-04-26 PR29): set due_date on every active TODAY /
    TOMORROW task that's missing one. The same as the per-save auto-
    fill in `_today_auto_fill` (#46), but applied retroactively to
    legacy rows that pre-date that rule.

    Without this, /calendar grouped purely by due_date and silently
    dropped legacy TOMORROW-tier tasks from tomorrow's cell — exactly
    the user-reported mismatch ("Update position paper..." invisible).
    PR29 also added a tier-fallback in calendar.js for the visual
    side; this endpoint closes the data drift so any future surface
    that filters by date stays consistent.

    Idempotent: re-running is a no-op once everything's in sync.
    Auth: X-Debug-Token. Returns: {"updated_today": N, "updated_tomorrow": N}.
    """
    from datetime import date, timedelta

    from models import Task, TaskStatus, Tier, db

    today = date.today()  # local server tz; matches _local_today_date used elsewhere
    tomorrow = today + timedelta(days=1)

    today_rows = list(db.session.scalars(
        select(Task).where(
            Task.tier == Tier.TODAY,
            Task.due_date.is_(None),
            Task.status == TaskStatus.ACTIVE,
        )
    ))
    tomorrow_rows = list(db.session.scalars(
        select(Task).where(
            Task.tier == Tier.TOMORROW,
            Task.due_date.is_(None),
            Task.status == TaskStatus.ACTIVE,
        )
    ))
    for t in today_rows:
        t.due_date = today
    for t in tomorrow_rows:
        t.due_date = tomorrow
    db.session.commit()
    logger.info(
        "backfill today_tomorrow_due_date: today=%d tomorrow=%d",
        len(today_rows), len(tomorrow_rows),
    )
    return jsonify({
        "updated_today": len(today_rows),
        "updated_tomorrow": len(tomorrow_rows),
    }), 200


@bp.post("/backfill/project-colors")
@debug_admin_auth_required  # PR65 #126: write endpoint requires admin token
def backfill_project_colors(email: str):  # noqa: ARG001
    """#93 (2026-04-26): apply per-type default color (#66) to legacy
    projects that were created before PR3 and still carry the old
    single default color #2563eb.

    Idempotent: only updates projects whose color matches the legacy
    default AND whose type now has a different default
    (i.e. Personal projects get switched to #16a34a; Work stays #2563eb).
    Manually-overridden colors are NEVER touched.

    Auth: X-Debug-Token. Returns: {"scanned": N, "updated": N,
    "changes": [{"id": ..., "name": ..., "type": ..., "old": ..., "new": ...}]}.
    """
    from models import Project, ProjectType, db
    from project_service import _default_color_for_type

    LEGACY_DEFAULT = "#2563eb"
    projects = list(db.session.scalars(
        select(Project).where(Project.is_active.is_(True))
    ))
    changes: list[dict] = []
    for p in projects:
        if p.color != LEGACY_DEFAULT:
            continue
        new_color = _default_color_for_type(p.type)
        if new_color == LEGACY_DEFAULT:
            continue
        type_name = p.type.value if isinstance(p.type, ProjectType) else str(p.type)
        changes.append({
            "id": str(p.id), "name": p.name, "type": type_name,
            "old": p.color, "new": new_color,
        })
        p.color = new_color
    db.session.commit()
    logger.info(
        "backfill project_colors: scanned=%d updated=%d",
        len(projects), len(changes),
    )
    return jsonify({
        "scanned": len(projects),
        "updated": len(changes),
        "changes": changes,
    }), 200
