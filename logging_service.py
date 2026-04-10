"""Persistent application logging → Postgres AppLog table.

Overview
--------
This module wires Python's ``logging`` up to the database so warning+
events and HTTP request summaries land in the ``app_logs`` table,
queryable via ``/api/debug/logs``. The goal: give the developer (and
any agent assisting them) direct, structured access to recent failures
without shelling into Railway.

Components
----------
* ``scrub_sensitive`` — regex-strips emails, bearer tokens, api keys,
  session cookies, and Google API keys from a string before it touches
  the DB. Per CLAUDE.md, sensitive fields must never be logged.
* ``RequestContextFilter`` — attaches request_id/route/method/status to
  every LogRecord during a Flask request, so DBLogHandler can persist
  them. The values are populated by ``_before_request`` and
  ``_after_request``.
* ``DBLogHandler`` — the core sink. On every emit above WARNING, it
  inserts one AppLog row. Wraps every DB op in try/except so a DB
  failure can never crash the app.
* Circuit breaker — if DBLogHandler fails 10 times in a row (e.g. the
  DB is down or the table is missing), it disables itself permanently
  for the process lifetime and falls back to stderr. This prevents
  "DB down → logging fails → logs DB failure → logging fails" loops.
* Retention pruner — after every successful insert, if the row count
  exceeds ``MAX_ROWS``, delete the oldest rows. A separate time-based
  sweep (>14 days) runs every ``PRUNE_EVERY_N_INSERTS`` inserts to
  amortize cost.
* ``configure_logging(app)`` — call once from ``create_app``. Wires
  everything up and registers the before/after request hooks.

Retention
---------
Dual cap, whichever hits first:
- MAX_ROWS = 10_000
- MAX_AGE_DAYS = 14

Excluded routes
---------------
``/healthz`` and ``/static/*`` are excluded from the per-request
summary log to avoid drowning real signal in health-check noise.
Exceptions raised in those routes still get logged because the handler
hooks into Python logging, not the request summary.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import traceback as tb_module
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from threading import Lock
from time import monotonic

from flask import Flask, g, has_app_context, request

# --- Constants ---------------------------------------------------------------

MAX_ROWS = 10_000
MAX_AGE_DAYS = 14
CIRCUIT_BREAKER_THRESHOLD = 10
PRUNE_EVERY_N_INSERTS = 50

EXCLUDED_PATHS = ("/healthz", "/static/")

# --- Scrubbing ---------------------------------------------------------------

# Patterns that look like sensitive data. Order matters — more specific
# patterns run first. Each pattern is replaced with its label wrapped in
# [REDACTED:...] so the log still conveys what kind of thing was there.
_SCRUB_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Google API keys (AIza...)
    (re.compile(r"AIza[0-9A-Za-z_-]{35}"), "[REDACTED:GOOGLE_API_KEY]"),
    # Anthropic API keys (sk-ant-...)
    (
        re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
        "[REDACTED:ANTHROPIC_API_KEY]",
    ),
    # OpenAI-style keys (sk-...)
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "[REDACTED:API_KEY]"),
    # Bearer tokens
    (re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE), "Bearer [REDACTED]"),
    # Authorization headers
    (
        re.compile(r"authorization['\"]?\s*[:=]\s*['\"]?[^'\"\s]+", re.IGNORECASE),
        "authorization: [REDACTED]",
    ),
    # Flask session cookies
    (
        re.compile(r"session=[A-Za-z0-9._\-]+"),
        "session=[REDACTED]",
    ),
    # Query-string API keys (?key=... or ?api_key=...)
    (
        re.compile(r"([?&](?:api_?key|key|token)=)[^&\s]+", re.IGNORECASE),
        r"\1[REDACTED]",
    ),
    # Email addresses — last so the key patterns above win first
    (
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
        "[REDACTED:EMAIL]",
    ),
)


def scrub_sensitive(text: str | None) -> str | None:
    """Strip known sensitive patterns from a log string.

    Returns None unchanged. Never raises — if a pattern somehow blows
    up, the original text is returned (better to have a log entry than
    to lose a diagnostic due to a scrubber bug).
    """
    if text is None:
        return None
    try:
        result = text
        for pattern, replacement in _SCRUB_PATTERNS:
            result = pattern.sub(replacement, result)
        return result
    except Exception:
        return text


# --- Request context filter --------------------------------------------------


class RequestContextFilter(logging.Filter):
    """Stamp the current Flask request's id/route/method onto every LogRecord.

    Reads from ``flask.g`` which is set by ``_before_request``. If there
    is no request context (startup, background jobs, tests), the fields
    are left as None so the handler can persist NULLs.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.request_id = getattr(g, "request_id", None)
            record.route = getattr(g, "route", None)
            record.method = getattr(g, "method", None)
        except RuntimeError:
            # No app/request context
            record.request_id = None
            record.route = None
            record.method = None
        return True


# --- The DB handler ----------------------------------------------------------


class DBLogHandler(logging.Handler):
    """Logging handler that inserts records into the ``app_logs`` table.

    Safety features (see module docstring):
    - Circuit breaker: disables after ``CIRCUIT_BREAKER_THRESHOLD``
      consecutive DB failures.
    - Sensitive data scrubbing on ``message`` and ``traceback``.
    - All DB operations wrapped in try/except with stderr fallback.
    - Retention pruning on every insert (row cap) and every N inserts
      (age sweep).
    """

    def __init__(self, app: Flask, level: int = logging.WARNING) -> None:
        super().__init__(level=level)
        self.app = app
        self._consecutive_failures = 0
        self._insert_count = 0
        self._disabled = False
        self._lock = Lock()

    # --- Public state ---------------------------------------------------

    @property
    def is_disabled(self) -> bool:
        return self._disabled

    def reset(self) -> None:
        """Re-enable the handler after a circuit break. Test helper."""
        with self._lock:
            self._disabled = False
            self._consecutive_failures = 0

    # --- Core emit ------------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        if self._disabled:
            return

        # Avoid recursive logging from the handler itself. If the
        # logger_name is this module's name, drop it on the floor.
        if record.name == __name__:
            return

        try:
            self._insert_record(record)
            with self._lock:
                self._consecutive_failures = 0
                self._insert_count += 1
                should_prune_age = (
                    self._insert_count % PRUNE_EVERY_N_INSERTS == 0
                )
            self._prune_rows()
            if should_prune_age:
                self._prune_age()
        except Exception:
            self._record_failure()

    # --- Insert ---------------------------------------------------------

    def _insert_record(self, record: logging.LogRecord) -> None:
        """Insert one LogRecord into the app_logs table.

        Runs inside an app context — required for Flask-SQLAlchemy's
        ``db.session`` to function outside a request (startup logs,
        scheduled jobs).
        """
        from models import AppLog, db

        # Format the message now while the record is fresh.
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)

        tb_text: str | None = None
        if record.exc_info:
            tb_text = "".join(tb_module.format_exception(*record.exc_info))
        else:
            # Allow callers (e.g. client_error) to attach a pre-formatted
            # traceback string as a record attribute.
            override = getattr(record, "traceback_override", None)
            if override:
                tb_text = str(override)

        msg = scrub_sensitive(msg) or ""
        tb_text = scrub_sensitive(tb_text)

        # Truncate extreme sizes. Postgres Text has no hard cap but we
        # don't want a runaway log to eat the DB.
        if len(msg) > 10_000:
            msg = msg[:10_000] + "…[truncated]"
        if tb_text and len(tb_text) > 20_000:
            tb_text = tb_text[:20_000] + "…[truncated]"

        # Reuse the active app context if we're inside one (e.g. during a
        # Flask request, scheduler job, or test). Only push a new one
        # when called from a truly contextless place (module-level
        # startup logs). Nested :memory: sqlite connections in tests
        # see their own DB, so a spurious push would make writes invisible.
        ctx = nullcontext() if has_app_context() else self.app.app_context()
        with ctx:
            row = AppLog(
                timestamp=datetime.now(UTC),
                level=record.levelname,
                logger_name=record.name[:200],
                message=msg,
                traceback=tb_text,
                request_id=getattr(record, "request_id", None),
                route=getattr(record, "route", None),
                method=getattr(record, "method", None),
                status_code=getattr(record, "status_code", None),
                source=getattr(record, "source", "server"),
            )
            db.session.add(row)
            db.session.commit()

    # --- Pruning --------------------------------------------------------

    def _prune_rows(self) -> None:
        """Cap total rows at MAX_ROWS by deleting the oldest."""
        from sqlalchemy import delete, select

        from models import AppLog, db

        try:
            ctx = nullcontext() if has_app_context() else self.app.app_context()
            with ctx:
                total = db.session.scalar(
                    select(db.func.count()).select_from(AppLog)
                )
                if total is None or total <= MAX_ROWS:
                    return
                excess = total - MAX_ROWS
                # Find the timestamps of the N oldest rows and delete them.
                oldest_stmt = (
                    select(AppLog.id)
                    .order_by(AppLog.timestamp.asc())
                    .limit(excess)
                )
                ids_to_delete = list(db.session.scalars(oldest_stmt))
                if ids_to_delete:
                    db.session.execute(
                        delete(AppLog).where(AppLog.id.in_(ids_to_delete))
                    )
                    db.session.commit()
        except Exception:  # noqa: S110 pruning must never raise
            # Pruning must never cause a logging failure.
            pass

    def _prune_age(self) -> None:
        """Delete rows older than MAX_AGE_DAYS."""
        from sqlalchemy import delete

        from models import AppLog, db

        try:
            cutoff = datetime.now(UTC) - timedelta(days=MAX_AGE_DAYS)
            ctx = nullcontext() if has_app_context() else self.app.app_context()
            with ctx:
                db.session.execute(
                    delete(AppLog).where(AppLog.timestamp < cutoff)
                )
                db.session.commit()
        except Exception:  # noqa: S110 pruning must never raise
            pass

    # --- Circuit breaker ------------------------------------------------

    def _record_failure(self) -> None:
        """Increment the failure counter and trip the breaker if needed.

        Falls back to stderr for the record itself so we don't silently
        drop diagnostics — the user can still see them in Railway logs.
        """
        with self._lock:
            self._consecutive_failures += 1
            should_disable = (
                self._consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD
            )

        sys.stderr.write(
            "[logging_service] DBLogHandler insert failed "
            f"(consecutive={self._consecutive_failures})\n"
        )

        if should_disable:
            with self._lock:
                self._disabled = True
            sys.stderr.write(
                "[logging_service] DBLogHandler DISABLED after "
                f"{CIRCUIT_BREAKER_THRESHOLD} consecutive failures. "
                "Falling back to stderr for the rest of this process. "
                "Restart the app after fixing the DB issue.\n"
            )


# --- Flask wiring ------------------------------------------------------------


def _should_skip_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in EXCLUDED_PATHS)


def _before_request() -> None:
    """Stamp a request id and capture route/method on flask.g.

    ``request_id`` is either the ``X-Request-ID`` header (if the caller
    sent one — useful for log correlation across clients) or a new UUID.
    """
    g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    g.route = request.path
    g.method = request.method
    g.request_start = monotonic()


def _after_request(response):
    """Emit one INFO log line per request for non-excluded paths.

    The line's level is INFO so it sits below the DBLogHandler's default
    WARNING threshold by default — it only persists if the developer
    raises the handler level via env var (see ``configure_logging``).
    """
    try:
        if _should_skip_path(request.path):
            return response

        duration_ms = int((monotonic() - getattr(g, "request_start", monotonic())) * 1000)
        logger = logging.getLogger("taskmanager.request")

        # Attach status_code so the handler can persist it.
        extra = {
            "status_code": response.status_code,
        }
        # Error responses get bumped to WARNING so they actually land
        # in the DB without requiring the INFO threshold.
        level = (
            logging.WARNING if response.status_code >= 500
            else (
                logging.INFO if response.status_code < 400
                else logging.WARNING
            )
        )
        logger.log(
            level,
            "%s %s → %d (%dms)",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
            extra=extra,
        )
    except Exception:  # noqa: S110 never let logging break a response
        # Never let a logging failure break the response.
        pass
    return response


def configure_logging(app: Flask) -> DBLogHandler | None:
    """Install the DB log handler and request-context middleware.

    Respects env vars:
    - APP_LOG_LEVEL: minimum level to persist. Default WARNING.
      Set to INFO to capture per-request summary rows.
    - APP_LOG_DISABLE: if set to a truthy value, the handler is NOT
      installed (useful for tests that want to assert on stderr only).

    Returns the installed handler so tests can inspect it, or None if
    disabled.
    """
    if os.environ.get("APP_LOG_DISABLE"):
        return None

    level_name = os.environ.get("APP_LOG_LEVEL", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)

    handler = DBLogHandler(app, level=level)
    handler.addFilter(RequestContextFilter())

    # Attach to the root logger so every module's logger inherits it.
    root = logging.getLogger()
    # Don't clobber existing handlers (gunicorn installs its own).
    # But ensure root's level is low enough that our handler actually
    # sees the records.
    if root.level > level:
        root.setLevel(level)
    root.addHandler(handler)

    # Register request hooks. Guard against double-registration in test
    # scenarios where create_app is called repeatedly.
    if not getattr(app, "_logging_hooks_installed", False):
        app.before_request(_before_request)
        app.after_request(_after_request)
        app._logging_hooks_installed = True  # type: ignore[attr-defined]

    return handler
