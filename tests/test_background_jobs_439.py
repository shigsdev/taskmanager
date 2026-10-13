"""#439 — background jobs can stop silently.

1. Exactly one gunicorn worker runs the scheduler, chosen by an exclusive
   file lock that the OS releases when its holder exits — so the
   replacement for a killed worker takes over (it used to be "age == 1").
2. The digest: an hour's misfire grace, and a catch-up at scheduler start
   when today's send was missed by no more than 3 hours.
3. The DIGEST_TZ fallback to the server clock logs an ERROR.
"""
from __future__ import annotations

import importlib.util
import logging
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import scheduler_lock

ROOT = Path(__file__).resolve().parent.parent
ET = ZoneInfo("America/New_York")


# --- 1. the scheduler lock ---------------------------------------------


class TestSchedulerLock:

    def test_second_holder_is_refused_until_the_first_lets_go(self, tmp_path):
        path = str(tmp_path / "s.lock")
        first = scheduler_lock.try_acquire(path)
        assert first is not None
        assert scheduler_lock.try_acquire(path) is None
        scheduler_lock.release(first)
        again = scheduler_lock.try_acquire(path)
        assert again is not None
        scheduler_lock.release(again)

    def test_a_dead_holder_frees_the_lock(self, tmp_path):
        """The real case: worker 1 is killed and its replacement boots."""
        path = str(tmp_path / "s.lock")
        holder = subprocess.Popen(  # noqa: S603 — fixed argv, our own interpreter
            [sys.executable, "-c",
             "import sys, time, scheduler_lock\n"
             "h = scheduler_lock.try_acquire(sys.argv[1])\n"
             "print('held' if h else 'refused', flush=True)\n"
             "time.sleep(30)\n",
             path],
            cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert holder.stdout.readline().strip() == "held"
            assert scheduler_lock.try_acquire(path) is None
        finally:
            holder.kill()
            holder.wait(timeout=10)
        deadline = time.monotonic() + 5
        got = None
        while got is None and time.monotonic() < deadline:
            got = scheduler_lock.try_acquire(path)
            if got is None:
                time.sleep(0.1)
        assert got is not None
        scheduler_lock.release(got)


def _load_gunicorn_conf():
    spec = importlib.util.spec_from_file_location("gunicorn_conf_439", ROOT / "gunicorn.conf.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Worker:
    def __init__(self, age):
        self.age = age


class TestPostWorkerInit:

    @pytest.fixture
    def started(self, monkeypatch, tmp_path):
        import app as app_module
        calls = []
        monkeypatch.setattr(app_module, "_start_digest_scheduler", lambda a: calls.append(a))
        monkeypatch.setattr(app_module, "create_app", lambda: "the-app")
        monkeypatch.setattr(scheduler_lock, "DEFAULT_PATH", str(tmp_path / "s.lock"))
        real = scheduler_lock.try_acquire
        monkeypatch.setattr(scheduler_lock, "try_acquire",
                            lambda path=None: real(str(tmp_path / "s.lock")))
        return calls

    def test_a_replacement_worker_starts_it_when_the_lock_is_free(self, started):
        conf = _load_gunicorn_conf()
        conf.post_worker_init(_Worker(age=3))  # was skipped under age == 1
        assert started == ["the-app"]
        scheduler_lock.release(conf._scheduler_lock)

    def test_a_second_live_worker_does_not(self, started, tmp_path):
        held = scheduler_lock.try_acquire(str(tmp_path / "s.lock"))
        try:
            conf = _load_gunicorn_conf()
            conf.post_worker_init(_Worker(age=1))
            assert started == []
            assert conf._scheduler_lock is None
        finally:
            scheduler_lock.release(held)


# --- 2. the digest -------------------------------------------------------


def _at(h, m, day=12):
    return datetime(2026, 10, day, h, m, tzinfo=ET)


def _sent(dt):
    return {"status": "ok", "at": dt.astimezone(UTC).isoformat()}


class TestShouldCatchUp:

    def test_missed_this_morning_inside_the_window(self):
        from digest_service import should_catch_up
        assert should_catch_up(_at(7, 20), 7, 0, _sent(_at(7, 0, day=11)))
        assert should_catch_up(_at(9, 59), 7, 0, _sent(_at(7, 0, day=11)))

    def test_never_sent(self):
        from digest_service import should_catch_up
        assert should_catch_up(_at(7, 5), 7, 0, None)

    def test_before_the_digest_time(self):
        from digest_service import should_catch_up
        assert not should_catch_up(_at(6, 59), 7, 0, None)

    def test_past_the_window(self):
        from digest_service import should_catch_up
        assert not should_catch_up(_at(10, 1), 7, 0, None)

    @pytest.mark.parametrize("status", ["ok", "fail", "skip"])
    def test_already_attempted_today(self, status):
        from digest_service import should_catch_up
        last = {"status": status, "at": _at(7, 0, ).astimezone(UTC).isoformat()}
        assert not should_catch_up(_at(7, 30), 7, 0, last)


class TestSchedulerDigest:

    def _cleanup(self):
        import contextlib

        import health
        if health._scheduler is not None:
            with contextlib.suppress(Exception):
                health._scheduler.shutdown(wait=False)
            health._scheduler = None
        with contextlib.suppress(Exception):
            health.HEARTBEAT_PATH.unlink(missing_ok=True)

    def test_jobs_have_an_hours_grace_and_coalesce(self, app, monkeypatch):
        from app import _start_digest_scheduler
        monkeypatch.setenv("DIGEST_TIME", "07:00")
        monkeypatch.setenv("DIGEST_TZ", "America/New_York")
        _start_digest_scheduler(app)
        try:
            import health
            for job_id in ("daily_digest", "tomorrow_roll", "realign_tiers_with_due_dates"):
                job = health._scheduler.get_job(job_id)
                assert job.misfire_grace_time == 3600, job_id
                assert job.coalesce is True, job_id
        finally:
            self._cleanup()

    def test_catch_up_sends_once_when_due(self, app):
        from app import _digest_catch_up
        from digest_service import record_send_result
        sends = []
        with app.app_context():
            record_send_result(status="ok")  # "at" = the real now
        # A "now" far ahead of the recorded send, inside its window.
        later = datetime.now(ET).replace(year=2099, hour=7, minute=30)
        assert _digest_catch_up(app, lambda: sends.append(1), 7, 0,
                                "America/New_York", now=later)
        assert sends == [1]

    def test_catch_up_skips_when_already_attempted(self, app):
        """Attempted at 07:05 (it failed); the scheduler starts at 07:30,
        inside the window — nothing is sent again."""
        import json

        from app import _digest_catch_up
        from digest_service import LAST_SEND_KEY
        from models import AppSetting, db
        sends = []
        attempted = _at(7, 5, day=12).replace(year=2099)
        with app.app_context():
            db.session.add(AppSetting(key=LAST_SEND_KEY, value=json.dumps(
                {"status": "fail", "at": attempted.astimezone(UTC).isoformat()})))
            db.session.commit()
        assert not _digest_catch_up(app, lambda: sends.append(1), 7, 0,
                                    "America/New_York",
                                    now=_at(7, 30, day=12).replace(year=2099))
        assert sends == []

    def test_catch_up_failure_never_raises(self, app):
        from app import _digest_catch_up

        def boom():
            raise RuntimeError("transport down")
        assert _digest_catch_up(app, boom, 7, 0, "America/New_York",
                                now=_at(7, 10, day=12).replace(year=2099)) is False


# --- 3. the tz fallback says so ------------------------------------------


class TestTzFallback:

    def test_fallback_logs_an_error_once(self, monkeypatch, caplog):
        import utils
        monkeypatch.setenv("DIGEST_TZ", "Not/AZone")
        monkeypatch.setattr(utils, "_tz_fallback_logged", False)
        with caplog.at_level(logging.ERROR, logger="utils"):
            utils.local_today_date()
            utils.local_today_date()
        errors = [r for r in caplog.records if "could not be loaded" in r.getMessage()]
        assert len(errors) == 1
