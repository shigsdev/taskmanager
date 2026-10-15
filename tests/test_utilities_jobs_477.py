"""#477 — /utilities audits can't outlive the request, and runs are capped.

The tech-debt audit shells out to pip / npm (120 s each) and jscpd (180 s),
past gunicorn's 120 s worker timeout, so it now runs in the background like
the coverage audit: POST returns at once, GET .../tech-debt-audit-status
reports it. Every /utilities button that runs work or dispatches a GitHub
workflow is rate-limited (5 a minute) with a plain message.
"""
from __future__ import annotations

import types

import pytest

import rate_limit
import utilities_api

STATUS = "/api/utilities/tech-debt-audit-status"
RUN = "/api/utilities/run-tech-debt-audit"


@pytest.fixture(autouse=True)
def job_state_files(tmp_path, monkeypatch):
    monkeypatch.setattr(utilities_api, "_TECH_DEBT_JOB_STATE_PATH", tmp_path / "td.json",
                        raising=False)
    monkeypatch.setattr(utilities_api, "_COVERAGE_JOB_STATE_PATH", tmp_path / "cov.json")


_REAL_TECH_DEBT_JOB = getattr(utilities_api, "_run_tech_debt_audit_job", None)


@pytest.fixture
def no_threads(monkeypatch):
    """Swap both background jobs for recorders: the real thread starts and
    returns at once, and a test can run the real tech-debt job itself."""
    started = []
    monkeypatch.setattr(utilities_api, "_run_tech_debt_audit_job",
                        lambda *args: started.append(("tech-debt", args)), raising=False)
    monkeypatch.setattr(utilities_api, "_run_coverage_audit_subprocess",
                        lambda *args: started.append(("coverage", args)))
    return started


def _wait_started(started, n=1):
    import time
    for _ in range(200):
        if len(started) >= n:
            return
        time.sleep(0.01)
    raise AssertionError(f"background job not started: {started}")


class TestTechDebtRunsInTheBackground:
    def test_idle_before_any_run(self, authed_client):
        body = authed_client.get(STATUS).get_json()
        assert body["status"] == "idle"
        assert body["result"] is None

    def test_post_returns_at_once_without_running_the_checks(
        self, authed_client, no_threads, monkeypatch,
    ):
        ran = []
        monkeypatch.setattr(utilities_api, "_run_audit_script_checks",
                            lambda *a, **k: ran.append(a))
        r = authed_client.post(RUN)
        assert r.status_code == 200
        assert r.get_json()["status"] == "running"
        assert ran == []  # nothing ran inside the request
        _wait_started(no_threads)
        assert no_threads[0][0] == "tech-debt"
        assert authed_client.get(STATUS).get_json()["status"] == "running"
        # A second click while it runs is refused, not a second run.
        r2 = authed_client.post(RUN)
        assert r2.status_code == 409
        assert r2.get_json()["error"] == "A tech-debt audit is already running"
        assert len(no_threads) == 1

    def test_job_records_the_result(self, authed_client, no_threads, monkeypatch):
        fake = types.SimpleNamespace(
            __name__="fake_checks",
            CHECKS=[("one", lambda: []), ("two", lambda: [])],
        )
        import scripts
        monkeypatch.setattr(scripts, "check_tech_debt", fake, raising=False)
        import sys
        monkeypatch.setitem(sys.modules, "scripts.check_tech_debt", fake)
        monkeypatch.setattr(utilities_api, "_dispatch_audit_workflow_for_autofile",
                            lambda name: None)
        from scripts import backlog_autofile
        monkeypatch.setattr(backlog_autofile, "run_for_audit", lambda *a, **k: None)
        authed_client.post(RUN)
        _wait_started(no_threads)
        _REAL_TECH_DEBT_JOB(*no_threads[0][1])  # run the real job here
        body = authed_client.get(STATUS).get_json()
        assert body["status"] == "complete"
        assert body["result"]["total"] == 0
        assert [c["label"] for c in body["result"]["per_check"]] == ["one", "two"]
        assert body["finished_at"] and body["duration_seconds"] is not None
        # The slot is free again.
        assert authed_client.post(RUN).status_code == 200

    def test_job_records_an_error(self, authed_client, no_threads, monkeypatch):
        def boom(*_a, **_k):
            raise RuntimeError("pip exploded")
        monkeypatch.setattr(utilities_api, "_run_audit_script_checks", boom)
        authed_client.post(RUN)
        _wait_started(no_threads)
        _REAL_TECH_DEBT_JOB(*no_threads[0][1])
        body = authed_client.get(STATUS).get_json()
        assert body["status"] == "error"
        assert body["error"] == "RuntimeError: pip exploded"

    def test_status_requires_login(self, client):
        assert client.get(STATUS).status_code in (302, 401, 403)


class TestUtilityRunsAreRateLimited:
    @pytest.fixture
    def limiter_on(self, app):
        # TESTING apps skip limiter.init_app (conftest keeps it off), so
        # attach it to this app for real, with fresh memory storage.
        # (init_app skips building storage while the limiter is off.)
        rate_limit.limiter.enabled = True
        app.config["RATELIMIT_ENABLED"] = True
        rate_limit.limiter.init_app(app)
        rate_limit.limiter.reset()
        yield
        rate_limit.limiter.enabled = False
        rate_limit.limiter.reset()

    @pytest.mark.parametrize("url", [
        "/api/utilities/clear-stale-next-week-due-dates",
        "/api/utilities/trigger-backup",
        "/api/utilities/trigger-restore-drill",
        "/api/utilities/run-bug-pattern-scan",
        "/api/utilities/run-security-posture-scan",
        "/api/utilities/run-coverage-audit",
        "/api/utilities/run-tech-debt-audit",
    ])
    def test_sixth_run_in_a_minute_is_refused(
        self, limiter_on, authed_client, no_threads, monkeypatch, url,
    ):
        # Keep each run cheap: no real audit, no GitHub call.
        monkeypatch.setattr(utilities_api, "_run_audit_script_checks",
                            lambda *a, **k: {"total": 0, "per_check": [], "findings": []})
        monkeypatch.delenv("GITHUB_DISPATCH_TOKEN", raising=False)
        for i in range(5):
            # The background jobs answer 409 while "running"; free the slot.
            for path in (utilities_api._TECH_DEBT_JOB_STATE_PATH,
                         utilities_api._COVERAGE_JOB_STATE_PATH):
                path.write_text('{"status": "idle"}', encoding="utf-8")
            r = authed_client.post(url)
            assert r.status_code != 429, (i, r.get_json())
        r = authed_client.post(url)
        assert r.status_code == 429
        assert r.get_json()["error"] == "Too many runs — wait a minute and try again."

    def test_the_count_preview_is_not_limited(self, authed_client, limiter_on):
        for _ in range(8):
            r = authed_client.get("/api/utilities/clear-stale-next-week-due-dates/count")
            assert r.status_code == 200
