"""Shared pytest fixtures."""
from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import event as _sa_event
from sqlalchemy.orm import Session as _SASession

import auth
from app import create_app
from models import db as _db
from rate_limit import limiter as _limiter

# Monotonic counter for per-test heartbeat file names (see
# _reset_digest_heartbeat). A plain int is fine — tests run single-process.
_HB_COUNTER = 0

# PR 9 (2026-05-21): rate limiting is a prod concern, exercised in prod
# — never in unit tests. The per-route `@limiter.limit` decorators are
# enforced under the test client even though `limiter.init_app` is
# skipped for TESTING apps (the decorator's own check fires regardless),
# AND the `RATELIMIT_ENABLED` config key is only consulted during
# `init_app` — which is skipped — so it can't disable enforcement here.
# Flipping the Limiter instance's `enabled` flag off is the one switch
# that the decorator path actually honours. Set once at import; the
# test process never wants live rate limiting. Without this a test
# class with more calls to one endpoint than its per-route limit
# flakes with a 429 (PR 9's tight "5 per minute" transcript limit hit
# this — TestTranscriptUploadAPI makes 7 calls).
_limiter.enabled = False


# #447: SQLite ignores String(n) widths; Postgres (prod) refuses a longer value
# with DataError (StringDataRightTruncation) — which failed whole imports on
# prod while every test passed. Check widths at flush, for every session, and
# raise the same DataError Postgres would, so any write path that lets an
# over-long value through fails HERE.
#
# #476: same for Integer — SQLite stores anything up to 2**63, Postgres
# `integer` refuses past ±2**31-1 ("integer out of range").
def _check_string_widths(session, _flush_context, _instances):
    from sqlalchemy import BigInteger, Integer, SmallInteger, String, inspect
    from sqlalchemy.exc import DataError

    for obj in list(session.new) + list(session.dirty):
        mapper = inspect(obj).mapper
        for col in mapper.columns:
            if isinstance(col.type, Integer) and not isinstance(
                col.type, (BigInteger, SmallInteger),
            ):
                attr = mapper.get_property_by_column(col).key
                value = getattr(obj, attr, None)
                if (isinstance(value, int) and not isinstance(value, bool)
                        and abs(value) > 2**31 - 1):
                    raise DataError(
                        f"{col.table.name}.{col.name}", {},
                        ValueError(f"integer out of range: {col.table.name}.{col.name}"),
                    )
                continue
            length = getattr(col.type, "length", None)
            if not isinstance(col.type, String) or not length:
                continue
            attr = mapper.get_property_by_column(col).key
            value = getattr(obj, attr, None)
            if isinstance(value, str) and len(value) > length:
                raise DataError(
                    f"{col.table.name}.{col.name}", {},
                    ValueError(
                        f"value too long for type character varying({length}): "
                        f"{col.table.name}.{col.name} has {len(value)}"
                    ),
                )


_sa_event.listen(_SASession, "before_flush", _check_string_widths)


@pytest.fixture(autouse=True)
def _isolate_audit_autofile(monkeypatch):
    """#362: no test writes audit results into the real BACKLOG.md or
    dispatches a real GitHub workflow.

    Every audit runner in ``utilities_api`` ends with
    ``backlog_autofile.run_for_audit``, which rewrites ``BACKLOG_PATH`` —
    the repo's real BACKLOG.md. Route tests reached it unmocked, so every
    gate run rewrote two audit rows with fake findings. Point it at a file
    inside a directory that is never created: an unrelated test that
    reaches the autofile hits the existing FileNotFoundError handling
    (logged and swallowed) and writes nothing. Tests that want a real
    upsert set their own path after this runs (``temp_backlog`` in
    test_backlog_autofile.py).

    The same routes then POST a ``workflow_dispatch`` when
    ``GITHUB_DISPATCH_TOKEN`` is set; drop it so a test run can never
    fire real Actions runs. Tests that exercise dispatch ``setenv`` it.
    """
    from scripts import backlog_autofile

    monkeypatch.setattr(
        backlog_autofile, "BACKLOG_PATH",
        Path(tempfile.gettempdir()) / f"tm_test_no_backlog_{os.getpid()}"
        / "BACKLOG.md",
    )
    monkeypatch.delenv("GITHUB_DISPATCH_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def _reset_digest_heartbeat(monkeypatch):
    """Isolate the two process-global digest-check inputs per test.

    ``check_digest`` reads two module globals that several tests mutate:
      * ``health.HEARTBEAT_PATH`` — by default a SINGLE file in the shared
        system temp dir. Multiple tests writing/deleting it caused
        cross-test pollution under ``pytest-randomly`` AND intermittent
        Windows/OneDrive unlink/replace races. Point it at a UNIQUE
        per-test file (system temp, own name — NOT pytest's ``tmp_path``,
        whose session-end cleanup crashes on OneDrive-locked dirs) so no
        two tests ever share a heartbeat.
      * ``health._scheduler`` — set to a mock by scheduler tests; the
        heartbeat-fallback tests need it back at ``None``.
    Both reset before AND after every test so ordering can't contaminate.
    """
    global _HB_COUNTER
    import health

    _HB_COUNTER += 1
    hb_path = Path(tempfile.gettempdir()) / (
        f"tm_test_heartbeat_{os.getpid()}_{_HB_COUNTER}.json"
    )
    monkeypatch.setattr(health, "HEARTBEAT_PATH", hb_path)
    health._scheduler = None
    yield
    health._scheduler = None
    with contextlib.suppress(OSError):
        hb_path.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        hb_path.with_suffix(".json.tmp").unlink(missing_ok=True)


@pytest.fixture
def app(monkeypatch):
    # Dummy OAuth credentials so flask-dance registers cleanly; the real OAuth
    # flow is never executed in tests (we monkeypatch get_current_user_email).
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("OAUTHLIB_INSECURE_TRANSPORT", "1")
    monkeypatch.setenv("FLASK_ENV", "development")

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "AUTHORIZED_EMAIL": "me@example.com",
            "SESSION_COOKIE_SECURE": False,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        }
    )
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    return _db


@pytest.fixture
def authed_client(client, monkeypatch):
    """Client pre-authenticated as the authorized user."""
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
    return client
