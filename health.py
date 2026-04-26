"""Health check subsystem.

Provides the set of checks run by ``/healthz`` to verify the deployed
container is actually serving the expected build and that every
critical subsystem is working. The goal is to catch deploy failures
that used to slip through a naive "HTTP 200 means healthy" check —
things like: the new container never replaced the old one, migrations
were silently skipped, expected tables don't exist, the encryption key
is missing, the scheduler never started, etc.

Each check returns a short string:

- ``"ok"``                — check passed
- ``"skipped: ..."``      — not applicable in this environment
- ``"warn: ..."``         — degraded but non-fatal
- ``"fail: ..."``         — critical failure → /healthz returns 503

Checks must be cheap and side-effect-free. They run on every health
probe.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile
from pathlib import Path
from typing import Any

# Heartbeat file path. Written by the scheduler worker every minute,
# read by check_digest in every worker so the digest check stays
# deterministic across the Gunicorn worker pool.
HEARTBEAT_PATH = Path(tempfile.gettempdir()) / "taskmanager_digest_heartbeat.json"

# Heartbeat freshness window. Heartbeat job ticks every 60 s, so 5 min
# gives plenty of slack for GC pauses, slow disk, etc., without letting
# a silently-dead scheduler look healthy for long.
HEARTBEAT_MAX_AGE_SEC = 300

# Timestamp captured at module import so /healthz can report how long
# this container has been running. Useful for spotting zombie workers.
_STARTED_AT: str = _dt.datetime.now(_dt.UTC).isoformat()

# Module-level reference to the APScheduler instance. Populated by
# ``_start_digest_scheduler`` in ``app.py`` so the health check can
# introspect the live scheduler (job registered? next run in the
# future?) without importing gunicorn internals.
_scheduler: Any = None


def register_scheduler(scheduler: Any) -> None:
    """Record the live APScheduler instance for introspection."""
    global _scheduler  # noqa: PLW0603
    _scheduler = scheduler


def write_scheduler_heartbeat(scheduler: Any) -> None:
    """Persist a small snapshot of scheduler state to disk.

    Called from inside the scheduler worker (both at boot and via a
    1-minute interval job). Non-scheduler workers read this file in
    ``check_digest`` to prove the scheduler is alive.
    """
    try:
        job = scheduler.get_job("daily_digest")
        next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
        payload = {
            "written_at": _dt.datetime.now(_dt.UTC).isoformat(),
            "running": bool(getattr(scheduler, "running", False)),
            "job_present": job is not None,
            "next_run_time": next_run,
        }
        tmp = HEARTBEAT_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload))
        # Atomic replace so readers never see a half-written file.
        tmp.replace(HEARTBEAT_PATH)
    except Exception:  # noqa: S110  heartbeat failures must never crash the scheduler worker
        pass


def _read_fresh_heartbeat() -> dict | None:
    """Return the heartbeat payload if it exists and is fresh, else None."""
    try:
        if not HEARTBEAT_PATH.exists():
            return None
        payload = json.loads(HEARTBEAT_PATH.read_text())
        written = _dt.datetime.fromisoformat(payload["written_at"])
        age = (_dt.datetime.now(_dt.UTC) - written).total_seconds()
        if age > HEARTBEAT_MAX_AGE_SEC:
            return None
        return payload
    except Exception:
        return None


# Tables that must exist in a healthy deployment. Bump this list whenever
# a new model is added to ``models.py``.
EXPECTED_TABLES = {
    "goals",
    "projects",
    "tasks",
    "recurring_tasks",
    "import_log",
}

# Static files that ``base.html`` and the service worker depend on.
# Missing any of these means a broken build.
EXPECTED_STATIC_FILES = (
    "static/app.js",
    "static/task_detail_payload.js",
    "static/style.css",
    "static/sw.js",
    "static/parse_capture.js",
    "static/capture.js",
    "static/voice_memo.js",
    "static/day_group.js",
    "static/projects.js",
    "static/calendar.js",
    "static/manifest.json",
)

PROJECT_ROOT = Path(__file__).parent


# --- Individual checks -------------------------------------------------------


def check_database(db: Any) -> str:
    """Verify a basic DB round-trip works."""
    try:
        db.session.execute(db.text("SELECT 1"))
        return "ok"
    except Exception as e:
        return f"fail: {_short(e)}"


def check_env_vars(app: Any) -> str:
    """Verify the required environment variables are set.

    ``SECRET_KEY`` is checked via ``app.config`` (populated from env at
    startup). ``GOOGLE_CLIENT_ID``/``SECRET`` are read from
    ``os.environ`` because they are consumed at blueprint registration
    time, not stored on the app.
    """
    missing = []
    dev_default = "dev-secret-change-me"  # noqa: S105  (sentinel, not a real secret)
    secret = app.config.get("SECRET_KEY")
    # Fail if SECRET_KEY is missing or still the insecure dev default,
    # except in TESTING mode where conftest sets its own dummy value.
    if (not secret or secret == dev_default) and not app.config.get("TESTING"):
        missing.append("SECRET_KEY")
    for v in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
        if not os.environ.get(v):
            missing.append(v)
    if missing:
        return f"fail: missing {', '.join(missing)}"
    return "ok"


def check_migrations(app: Any) -> str:
    """Verify the DB schema is at the latest Alembic head.

    A passing result means ``alembic current`` equals ``alembic heads``.
    A failing result means a migration is pending — which typically
    explains data-loss incidents where models changed but the table
    structure didn't.
    """
    # Tests don't run migrations (they use ``db.create_all()``) so
    # there is no alembic_version row and this check would always fail.
    if app.config.get("TESTING"):
        return "skipped: testing"

    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from sqlalchemy import text

        from models import db as _db

        try:
            row = _db.session.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchone()
            current_rev = row[0] if row else None
        except Exception:
            return "fail: alembic_version table missing"

        migrations_dir = PROJECT_ROOT / "migrations"
        if not migrations_dir.exists():
            return "skipped: no migrations dir"
        cfg = Config()
        cfg.set_main_option("script_location", str(migrations_dir))
        script = ScriptDirectory.from_config(cfg)
        head_rev = script.get_current_head()

        if current_rev == head_rev:
            return "ok"
        # Actual mismatch is still a real fail — that's the whole
        # point of the check.
        return f"fail: at {current_rev} expected {head_rev}"
    except Exception as e:
        # Any unexpected error (bad alembic version, missing
        # dependency, etc.) is a WARN, not a fail — we never want
        # a broken health check to block a deploy.
        return f"warn: {_short(e)}"


def check_tables(db: Any) -> str:
    """Verify every expected table actually exists in the live DB."""
    try:
        from sqlalchemy import inspect

        inspector = inspect(db.engine)
        actual = set(inspector.get_table_names())
        missing = EXPECTED_TABLES - actual
        if missing:
            return f"fail: missing {', '.join(sorted(missing))}"
        return "ok"
    except Exception as e:
        # An error introspecting tables is a warn, not fail — we
        # don't want SQLAlchemy introspection quirks to block a deploy.
        return f"warn: {_short(e)}"


def check_writable_db(db: Any) -> str:
    """Verify the DB accepts writes.

    Uses a temporary table inside a rolled-back transaction so no real
    state is changed. Catches read-only mode (e.g. during Railway
    Postgres maintenance windows) and hot-standby replicas.

    Returns ``warn:`` instead of ``fail:`` on error — this check is a
    nice-to-have, and an SQLAlchemy/driver quirk should never take
    down a deploy.
    """
    try:
        from sqlalchemy import text

        # ``engine.begin()`` handles the transaction lifecycle cleanly
        # on SQLAlchemy 2.x + psycopg3. Using ``connect()`` + manual
        # ``conn.begin()`` can collide with autobegin semantics.
        with db.engine.begin() as conn:
            conn.execute(text("CREATE TEMPORARY TABLE _health_canary (x INTEGER)"))
            conn.execute(text("INSERT INTO _health_canary VALUES (1)"))
            # Force rollback by raising — caught below and swallowed
            raise _Rollback
    except _Rollback:
        return "ok"
    except Exception as e:
        return f"warn: {_short(e)}"


class _Rollback(Exception):
    """Sentinel exception used to force a transaction rollback in
    ``check_writable_db`` without leaving the canary table behind."""


def check_encryption() -> str:
    """Verify Fernet can round-trip a canary value.

    Encrypts a known string and checks that (a) the ciphertext differs
    from the plaintext (proving Fernet actually ran, not the no-op
    fallback) and (b) decryption returns the original plaintext.

    Distinguishes two failure modes:

    - ``ENCRYPTION_KEY`` is unset → ``warn:``. Fine in dev, acceptable
      in prod (the app works, sensitive fields just aren't encrypted).
    - ``ENCRYPTION_KEY`` is SET but malformed → ``fail:``. Something
      is trying to use Fernet but it can't initialize, which means
      encryption silently degrades to plaintext — a data-integrity
      bug. This blocks promotion because it's a real config drift.
    """
    try:
        from crypto import decrypt, encrypt

        plaintext = "health-canary"
        ciphertext = encrypt(plaintext)
        if ciphertext == plaintext:
            # Fernet wasn't initialized — either no key set (warn) or
            # the key is malformed and crypto.py swallowed the error
            if os.environ.get("ENCRYPTION_KEY"):
                return "fail: ENCRYPTION_KEY set but not working"
            return "warn: ENCRYPTION_KEY not set"
        if decrypt(ciphertext) != plaintext:
            return "fail: roundtrip mismatch"
        return "ok"
    except Exception as e:
        # Fernet raised directly during init/encrypt — this is the
        # "malformed key" path (e.g. wrong length, wrong alphabet).
        # Treat as fail because it means the app is trying to use
        # encryption but can't.
        if os.environ.get("ENCRYPTION_KEY"):
            return f"fail: {_short(e)}"
        return f"warn: {_short(e)}"


def check_digest() -> str:
    """Verify the digest scheduler is live and has a future-dated run.

    Previously this only checked that ``apscheduler`` was importable,
    which missed the whole class of bug where the scheduler silently
    failed to start inside the gunicorn worker.
    """
    to_email = os.environ.get("DIGEST_TO_EMAIL")
    if not to_email:
        return "skipped: DIGEST_TO_EMAIL not set"

    # apscheduler must at least be importable
    try:
        import importlib.util

        if not importlib.util.find_spec("apscheduler"):
            return "fail: apscheduler not installed"
    except Exception:
        return "fail: apscheduler not installed"

    if not os.environ.get("SENDGRID_API_KEY"):
        return "warn: SENDGRID_API_KEY not set"

    # Preferred path: this worker IS the scheduler worker and has a
    # live reference to it. Introspect directly.
    if _scheduler is not None:
        try:
            if not getattr(_scheduler, "running", False):
                return "fail: scheduler not running"
            job = _scheduler.get_job("daily_digest")
            if job is None:
                return "fail: daily_digest job missing"
            if job.next_run_time is None:
                return "fail: daily_digest has no next_run_time"
            return "ok"
        except Exception as e:
            return f"fail: {_short(e)}"

    # Fallback: this is a non-scheduler worker. Read the heartbeat
    # file the scheduler worker writes every minute. If it's fresh and
    # healthy, we can trust the scheduler is alive.
    beat = _read_fresh_heartbeat()
    if beat is not None:
        if not beat.get("running"):
            return "fail: heartbeat says scheduler not running"
        if not beat.get("job_present"):
            return "fail: heartbeat says daily_digest job missing"
        if not beat.get("next_run_time"):
            return "fail: heartbeat says daily_digest has no next_run_time"
        return "ok"

    return "warn: scheduler not registered (dev/test or pre-boot)"


def check_static_assets() -> str:
    """Verify critical static files exist on disk in this container."""
    missing = [
        p for p in EXPECTED_STATIC_FILES if not (PROJECT_ROOT / p).exists()
    ]
    if missing:
        return f"fail: missing {', '.join(missing)}"
    return "ok"


# --- Public entry point ------------------------------------------------------


# Checks whose failure flips HTTP status to 503.
#
# Critical checks represent REAL data-integrity conditions where
# letting the deploy go green would be actively dangerous:
#
#   database     — no connection = app can't do anything useful
#   env_vars     — missing SECRET_KEY/OAuth = auth is broken
#   encryption   — Fernet key malformed = sensitive fields would be
#                  stored in plaintext (silent data-integrity bug)
#   migrations   — alembic_version doesn't match head = schema drift,
#                  the exact failure mode of the yesterday data-loss
#                  incident
#   tables       — an expected table is missing = app will 500 on
#                  most routes
#
# Non-critical checks (writable_db, digest, static_assets) are
# reported in the response body but never block promotion. These are
# nice-to-haves whose check logic is most likely to hit a driver/OS
# quirk that would falsely brick a deploy.
#
# In addition, every check runs through ``_safe_call`` which converts
# any uncaught Python exception to ``warn:``. That means a BUG in a
# critical check (e.g. an import error, a typo) can never brick a
# deploy either — only a legitimate ``fail:`` string returned from
# the check itself can. This is belt + suspenders.
CRITICAL_CHECKS = {
    "database",
    "env_vars",
    "encryption",
    "migrations",
    "tables",
}


def check_enum_coverage(db: Any) -> str:
    """Bug #53: assert every Python enum member used as a column type
    exists in the live Postgres enum.

    This is the second layer of defense against the alembic
    ALTER-TYPE-rolls-back-silently bug class (#23, #25, #52). The
    first layer is `_ensure_postgres_enum_values()` in app.py, which
    auto-emits ALTER TYPE for every member at boot. If that gate ever
    silently fails (or someone deletes an enum value out-of-band), this
    check catches it and turns the deploy red — surfacing in
    `validate_deploy.py`'s `/healthz` poll instead of failing the next
    user request with `InvalidTextRepresentation`.

    SQLite skip: enums are stored as VARCHAR with no native enum type,
    so there's nothing to verify.

    Returns "ok" if every Python enum member appears in pg_enum.
    Returns "fail: <enum>.<value> missing in Postgres (and N more)"
    listing the first missing pair.
    """
    if db.engine.dialect.name != "postgresql":
        return "skipped: not postgres"

    from sqlalchemy import text
    missing: list[str] = []
    try:
        with db.engine.connect() as conn:
            for mapper in db.Model.registry.mappers:
                if mapper.local_table is None:
                    continue
                for col in mapper.local_table.columns:
                    enum_cls = getattr(col.type, "enum_class", None)
                    if enum_cls is None:
                        continue
                    pg_enum_name = enum_cls.__name__.lower()
                    rows = conn.execute(text(
                        "SELECT enumlabel FROM pg_enum "
                        "JOIN pg_type ON pg_type.oid = pg_enum.enumtypid "
                        "WHERE pg_type.typname = :name",
                    ), {"name": pg_enum_name}).fetchall()
                    db_values = {r[0] for r in rows}
                    for member in enum_cls:
                        if member.name not in db_values:
                            missing.append(f"{pg_enum_name}.{member.name}")
    except Exception as e:
        return f"warn: enum coverage check failed: {_short(e)}"

    if missing:
        first = missing[0]
        rest = len(missing) - 1
        suffix = f" (and {rest} more)" if rest > 0 else ""
        return f"fail: {first} missing in Postgres{suffix}"
    return "ok"


def _safe_call(name: str, fn, *args) -> str:
    """Run a check but never let it raise — convert any unhandled
    exception to a ``warn:`` so /healthz stays up."""
    try:
        return fn(*args)
    except Exception as e:
        return f"warn: {name} crashed: {_short(e)}"


def run_health_checks(app: Any, db: Any) -> dict:
    """Run every check and return a full health report.

    The report includes a ``git_sha`` field so a deploy-validation
    script can confirm the container serving the request is the one it
    just pushed. Railway injects ``RAILWAY_GIT_COMMIT_SHA`` at build
    time. Locally this returns ``"dev"``.
    """
    checks = {
        "database": _safe_call("database", check_database, db),
        "env_vars": _safe_call("env_vars", check_env_vars, app),
        "migrations": _safe_call("migrations", check_migrations, app),
        "tables": _safe_call("tables", check_tables, db),
        "writable_db": _safe_call("writable_db", check_writable_db, db),
        "encryption": _safe_call("encryption", check_encryption),
        "digest": _safe_call("digest", check_digest),
        "static_assets": _safe_call("static_assets", check_static_assets),
        "enum_coverage": _safe_call("enum_coverage", check_enum_coverage, db),
    }

    # Overall ``status`` reflects ANY fail (for the report). HTTP 503
    # only fires for ``CRITICAL_CHECKS`` — see route handler.
    failed = [k for k, v in checks.items() if v.startswith("fail")]
    critical_failed = [k for k in failed if k in CRITICAL_CHECKS]

    return {
        "status": "fail" if failed else "ok",
        "critical_failed": critical_failed,
        "git_sha": os.environ.get("RAILWAY_GIT_COMMIT_SHA", "dev"),
        "started_at": _STARTED_AT,
        "checks": checks,
    }


def _short(exc: Exception, limit: int = 120) -> str:
    """Truncate exception messages so /healthz responses stay small and
    don't leak full stack traces."""
    text = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
    return text[:limit]
