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
import os
from pathlib import Path
from typing import Any

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
    "static/style.css",
    "static/sw.js",
    "static/capture.js",
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

        with app.app_context():
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
        return f"fail: at {current_rev} expected {head_rev}"
    except Exception as e:
        return f"fail: {_short(e)}"


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
        return f"fail: {_short(e)}"


def check_writable_db(db: Any) -> str:
    """Verify the DB accepts writes.

    Uses a temporary table inside a rolled-back transaction so no real
    state is changed. Catches read-only mode (e.g. during Railway
    Postgres maintenance windows) and hot-standby replicas.
    """
    try:
        from sqlalchemy import text

        with db.engine.connect() as conn:
            trans = conn.begin()
            try:
                conn.execute(
                    text("CREATE TEMPORARY TABLE _health_canary (x INTEGER)")
                )
                conn.execute(text("INSERT INTO _health_canary VALUES (1)"))
            finally:
                trans.rollback()
        return "ok"
    except Exception as e:
        return f"fail: {_short(e)}"


def check_encryption() -> str:
    """Verify Fernet can round-trip a canary value.

    Encrypts a known string and checks that (a) the ciphertext differs
    from the plaintext (proving Fernet actually ran, not the no-op
    fallback) and (b) decryption returns the original plaintext.
    """
    try:
        from crypto import decrypt, encrypt

        plaintext = "health-canary"
        ciphertext = encrypt(plaintext)
        if ciphertext == plaintext:
            return "warn: ENCRYPTION_KEY not set"
        if decrypt(ciphertext) != plaintext:
            return "fail: roundtrip mismatch"
        return "ok"
    except Exception as e:
        return f"fail: {_short(e)}"


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

    # Inspect the live scheduler (only available in gunicorn workers —
    # not set during unit tests, so we skip there)
    if _scheduler is None:
        return "warn: scheduler not registered (dev/test or pre-boot)"

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


def check_static_assets() -> str:
    """Verify critical static files exist on disk in this container."""
    missing = [
        p for p in EXPECTED_STATIC_FILES if not (PROJECT_ROOT / p).exists()
    ]
    if missing:
        return f"fail: missing {', '.join(missing)}"
    return "ok"


# --- Public entry point ------------------------------------------------------


def run_health_checks(app: Any, db: Any) -> dict:
    """Run every check and return a full health report.

    The report includes a ``git_sha`` field so a deploy-validation
    script can confirm the container serving the request is the one it
    just pushed. Railway injects ``RAILWAY_GIT_COMMIT_SHA`` at build
    time. Locally this returns ``"dev"``.
    """
    checks = {
        "database": check_database(db),
        "env_vars": check_env_vars(app),
        "migrations": check_migrations(app),
        "tables": check_tables(db),
        "writable_db": check_writable_db(db),
        "encryption": check_encryption(),
        "digest": check_digest(),
        "static_assets": check_static_assets(),
    }

    failed = [k for k, v in checks.items() if v.startswith("fail")]

    return {
        "status": "fail" if failed else "ok",
        "git_sha": os.environ.get("RAILWAY_GIT_COMMIT_SHA", "dev"),
        "started_at": _STARTED_AT,
        "checks": checks,
    }


def _short(exc: Exception, limit: int = 120) -> str:
    """Truncate exception messages so /healthz responses stay small and
    don't leak full stack traces."""
    text = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
    return text[:limit]
