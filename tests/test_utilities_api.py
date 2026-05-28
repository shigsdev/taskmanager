"""Tests for the /api/utilities/* endpoints (#222, 2026-05-24).

OAuth-gated UI wrappers over the same backfill logic exposed via
admin-token-gated /api/debug/backfill/clear-stale-next-week-due-dates.
This test file covers the route registration, auth, and the
count/run pair against a known DB state.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from models import Task, TaskStatus, TaskType, Tier, db


def _make_task(**overrides) -> Task:
    fields = {"title": "Seed", "type": TaskType.WORK}
    fields.update(overrides)
    task = Task(**fields)
    db.session.add(task)
    db.session.commit()
    return task


def _today():
    from utils import local_today_date
    return local_today_date()


class TestUtilitiesAuth:
    """Both endpoints require OAuth — anonymous requests must be
    rejected (the single-user AUTHORIZED_EMAIL gate). The admin-token
    SPLIT used by /api/debug/backfill/* does NOT apply here because
    these are surfaced through the UI to the OAuth'd owner."""

    def test_count_endpoint_requires_auth(self, client):
        resp = client.get("/api/utilities/clear-stale-next-week-due-dates/count")
        assert resp.status_code in (302, 401, 403)

    def test_run_endpoint_requires_auth(self, client):
        resp = client.post("/api/utilities/clear-stale-next-week-due-dates")
        assert resp.status_code in (302, 401, 403)

    def test_run_endpoint_rejects_GET(self, client):
        # Mutating routes must NEVER accept GET — same #190 / #185 rule.
        resp = client.get("/api/utilities/clear-stale-next-week-due-dates")
        assert resp.status_code in (302, 401, 403, 404, 405)


class TestClearStaleNextWeekDueDates:
    """Behavior pair: count returns the number of would-be-cleared
    tasks (preview, no mutation); POST clears them and returns the
    same number."""

    def test_count_returns_zero_when_clean(self, app, authed_client):
        with app.app_context():
            # A clean DB state — only a future-dated next_week task
            # which is correctly placed and shouldn't count.
            next_tue = _today() + timedelta(days=8)
            _make_task(title="ok", tier=Tier.NEXT_WEEK, due_date=next_tue)
        resp = authed_client.get(
            "/api/utilities/clear-stale-next-week-due-dates/count"
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"count": 0}

    def test_count_includes_today_and_past_dated_next_week(
        self, app, authed_client
    ):
        with app.app_context():
            today = _today()
            week_ago = today - timedelta(days=7)
            next_tue = today + timedelta(days=8)
            _make_task(title="today", tier=Tier.NEXT_WEEK, due_date=today)
            _make_task(title="past", tier=Tier.NEXT_WEEK, due_date=week_ago)
            _make_task(title="future-ok", tier=Tier.NEXT_WEEK, due_date=next_tue)
        resp = authed_client.get(
            "/api/utilities/clear-stale-next-week-due-dates/count"
        )
        assert resp.status_code == 200
        # 2 stuck (today + week_ago), 1 future preserved.
        assert resp.get_json() == {"count": 2}

    def test_count_is_readonly(self, app, authed_client):
        """Calling count twice MUST NOT mutate — the user previews
        before running."""
        with app.app_context():
            _make_task(title="stuck", tier=Tier.NEXT_WEEK, due_date=_today())
        resp1 = authed_client.get(
            "/api/utilities/clear-stale-next-week-due-dates/count"
        )
        resp2 = authed_client.get(
            "/api/utilities/clear-stale-next-week-due-dates/count"
        )
        assert resp1.get_json() == {"count": 1}
        assert resp2.get_json() == {"count": 1}

    def test_run_clears_stuck_tasks(self, app, authed_client):
        with app.app_context():
            t = _make_task(title="stuck", tier=Tier.NEXT_WEEK, due_date=_today())
            tid = t.id
        resp = authed_client.post(
            "/api/utilities/clear-stale-next-week-due-dates"
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"updated": 1}
        with app.app_context():
            db.session.expire_all()
            t2 = db.session.get(Task, tid)
            assert t2.tier == Tier.NEXT_WEEK
            assert t2.due_date is None

    def test_run_is_idempotent(self, app, authed_client):
        """Re-running after clean returns updated: 0."""
        with app.app_context():
            _make_task(title="stuck", tier=Tier.NEXT_WEEK, due_date=_today())
        first = authed_client.post(
            "/api/utilities/clear-stale-next-week-due-dates"
        )
        second = authed_client.post(
            "/api/utilities/clear-stale-next-week-due-dates"
        )
        assert first.get_json() == {"updated": 1}
        assert second.get_json() == {"updated": 0}

    def test_run_leaves_non_active_alone(self, app, authed_client):
        with app.app_context():
            today = _today()
            _make_task(
                title="archived", tier=Tier.NEXT_WEEK,
                due_date=today, status=TaskStatus.ARCHIVED,
            )
        resp = authed_client.post(
            "/api/utilities/clear-stale-next-week-due-dates"
        )
        assert resp.get_json() == {"updated": 0}


class TestUtilitiesPageRenders:
    """The /utilities page itself must render under OAuth without
    console errors — covered mechanically by tests/e2e/ui_audit.spec.js
    (route in ROUTES) AND server-side here."""

    def test_page_renders_under_oauth(self, authed_client):
        resp = authed_client.get("/utilities")
        assert resp.status_code == 200
        # Cheap content assertion — the page should at least mention
        # the utilities currently shipped.
        body = resp.get_data(as_text=True)
        assert "Utilities" in body
        assert "clear-stale-next-week-due-dates" in body
        # #223 cards
        assert "trigger-backup" in body
        assert "trigger-restore-drill" in body

    def test_page_requires_auth(self, client):
        resp = client.get("/utilities")
        assert resp.status_code in (302, 401, 403)


# --- #223 (2026-05-24): backup + restore-drill workflow dispatch ----------


class _MockResponse:
    """Minimal mock for requests.Response — enough for the dispatch
    helper's resp.status_code / resp.json() / resp.text reads."""

    def __init__(self, status_code: int, json_body: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json = json_body
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


class TestTriggerBackup:
    """POST /api/utilities/trigger-backup dispatches daily-backup.yml.
    Tests use monkeypatch on requests.post — never hits real GitHub."""

    URL = "/api/utilities/trigger-backup"

    def test_requires_auth(self, client):
        resp = client.post(self.URL)
        assert resp.status_code in (302, 401, 403)

    def test_rejects_GET(self, client):
        # Mutating route — must NEVER accept GET (#190 rule).
        resp = client.get(self.URL)
        assert resp.status_code in (302, 401, 403, 404, 405)

    def test_missing_env_var_returns_503(self, app, authed_client, monkeypatch):
        """Without GITHUB_DISPATCH_TOKEN set, the endpoint should
        return 503 with a setup-instructions message — NOT crash."""
        monkeypatch.delenv("GITHUB_DISPATCH_TOKEN", raising=False)
        resp = authed_client.post(self.URL)
        assert resp.status_code == 503
        body = resp.get_json()
        assert "error" in body
        assert "GITHUB_DISPATCH_TOKEN" in body["error"]
        # Setup pointer surfaces the runbook.
        assert "docs/security/git-credentials.md" in body["error"]

    def test_happy_path_returns_actions_url(
        self, app, authed_client, monkeypatch,
    ):
        """When GitHub returns 204 No Content, the endpoint returns
        {dispatched: true, actions_url: ...}."""
        monkeypatch.setenv("GITHUB_DISPATCH_TOKEN", "fake_token_value")
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _MockResponse(204)

        monkeypatch.setattr("utilities_api.requests.post", fake_post)
        resp = authed_client.post(self.URL)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body == {
            "dispatched": True,
            "actions_url": "https://github.com/shigsdev/taskmanager/actions",
        }
        # Verify the dispatch hit the right workflow + sent the
        # `ref: main` body GitHub requires.
        assert "daily-backup.yml/dispatches" in captured["url"]
        assert captured["json"] == {"ref": "main"}
        # Token rides in the Authorization header per ADR-007.
        assert captured["headers"]["Authorization"] == "Bearer fake_token_value"

    def test_github_error_propagates_safely(
        self, app, authed_client, monkeypatch,
    ):
        """When GitHub returns a non-204 (e.g. 401 bad token,
        422 workflow not found), the endpoint returns 503 with the
        GitHub message — but the TOKEN never appears in the response."""
        monkeypatch.setenv("GITHUB_DISPATCH_TOKEN", "fake_token_value")

        def fake_post(url, headers=None, json=None, timeout=None):
            return _MockResponse(
                401, json_body={"message": "Bad credentials"},
            )

        monkeypatch.setattr("utilities_api.requests.post", fake_post)
        resp = authed_client.post(self.URL)
        assert resp.status_code == 503
        body = resp.get_json()
        assert "401" in body["error"]
        assert "Bad credentials" in body["error"]
        # CRITICAL: token must NEVER appear in error response.
        assert "fake_token_value" not in body["error"]

    def test_network_error_returns_503(self, app, authed_client, monkeypatch):
        """A requests.RequestException (timeout, DNS failure, etc.)
        surfaces as a 503 with a generic message — no internal
        details leaked."""
        import requests as requests_lib
        monkeypatch.setenv("GITHUB_DISPATCH_TOKEN", "fake_token_value")

        def fake_post(url, headers=None, json=None, timeout=None):
            raise requests_lib.ConnectTimeout("upstream timeout")

        monkeypatch.setattr("utilities_api.requests.post", fake_post)
        resp = authed_client.post(self.URL)
        assert resp.status_code == 503
        body = resp.get_json()
        assert "network error" in body["error"].lower()
        # The error type name is OK to surface; the timeout *detail*
        # is not (and we don't include it).
        assert "fake_token_value" not in body["error"]


class TestTriggerRestoreDrill:
    """POST /api/utilities/trigger-restore-drill dispatches
    monthly-restore-drill.yml. Smaller test set — the helper itself
    is exhaustively covered by TestTriggerBackup; here we just verify
    this endpoint dispatches the RIGHT workflow file."""

    URL = "/api/utilities/trigger-restore-drill"

    def test_requires_auth(self, client):
        resp = client.post(self.URL)
        assert resp.status_code in (302, 401, 403)

    def test_dispatches_restore_drill_workflow(
        self, app, authed_client, monkeypatch,
    ):
        monkeypatch.setenv("GITHUB_DISPATCH_TOKEN", "fake_token_value")
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            return _MockResponse(204)

        monkeypatch.setattr("utilities_api.requests.post", fake_post)
        resp = authed_client.post(self.URL)
        assert resp.status_code == 200
        assert resp.get_json()["dispatched"] is True
        # CRITICAL: this endpoint must dispatch the RESTORE-DRILL
        # workflow, not the backup workflow. A copy-paste bug here
        # would silently fire backups when the user clicked
        # restore-drill — caught by this assertion.
        assert "monthly-restore-drill.yml/dispatches" in captured["url"]
        assert "daily-backup.yml" not in captured["url"]


class TestGitHubRepoOverride:
    """The GITHUB_REPO env var lets a fork override the dispatch
    target. Defaults to shigsdev/taskmanager."""

    def test_default_repo_is_shigsdev_taskmanager(
        self, app, authed_client, monkeypatch,
    ):
        monkeypatch.setenv("GITHUB_DISPATCH_TOKEN", "fake")
        monkeypatch.delenv("GITHUB_REPO", raising=False)
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            return _MockResponse(204)

        monkeypatch.setattr("utilities_api.requests.post", fake_post)
        authed_client.post("/api/utilities/trigger-backup")
        assert "shigsdev/taskmanager" in captured["url"]

    def test_repo_override_redirects_dispatch(
        self, app, authed_client, monkeypatch,
    ):
        monkeypatch.setenv("GITHUB_DISPATCH_TOKEN", "fake")
        monkeypatch.setenv("GITHUB_REPO", "myfork/taskmanager-fork")
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            return _MockResponse(204)

        monkeypatch.setattr("utilities_api.requests.post", fake_post)
        resp = authed_client.post("/api/utilities/trigger-backup")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "myfork/taskmanager-fork" in captured["url"]
        assert body["actions_url"] == "https://github.com/myfork/taskmanager-fork/actions"


class TestInlineAuditScans:
    """#236 (2026-05-26): on-demand inline-scan endpoints for the
    recurring audit scripts. Mock the script CHECKS arrays to keep
    the test fast + independent of the live filesystem state."""

    def test_bug_pattern_endpoint_requires_auth(self, client):
        resp = client.post("/api/utilities/run-bug-pattern-scan")
        assert resp.status_code in (302, 401)

    def test_security_posture_endpoint_requires_auth(self, client):
        resp = client.post("/api/utilities/run-security-posture-scan")
        assert resp.status_code in (302, 401)

    def test_bug_pattern_scan_returns_total_per_check_findings(
        self, authed_client, monkeypatch,
    ):
        """Smoke test the response shape against the real CHECKS.
        Against the current main, every check should report 0 findings.
        """
        resp = authed_client.post("/api/utilities/run-bug-pattern-scan")
        assert resp.status_code == 200
        body = resp.get_json()
        assert isinstance(body["total"], int)
        assert isinstance(body["per_check"], list)
        assert isinstance(body["findings"], list)
        # All 6 checks should be enumerated in per_check.
        labels = [c["label"] for c in body["per_check"]]
        assert "bare-1fr-grids" in labels
        assert "unbalanced-type-work" in labels
        # The findings list is empty iff total is 0.
        assert len(body["findings"]) == body["total"]

    def test_security_posture_scan_returns_total_per_check_findings(
        self, authed_client,
    ):
        resp = authed_client.post(
            "/api/utilities/run-security-posture-scan"
        )
        assert resp.status_code == 200
        body = resp.get_json()
        labels = [c["label"] for c in body["per_check"]]
        assert "pat-inventory" in labels
        assert "oauth-scope-drift" in labels
        assert "unencrypted-sensitive-columns" in labels
        assert "threat-model-freshness" in labels

    def test_inline_scan_aggregates_findings_from_mocked_checks(
        self, authed_client, monkeypatch,
    ):
        """Patch one of the script CHECKS arrays to return synthetic
        findings, then verify the endpoint aggregates them into the
        {total, per_check, findings} shape correctly."""
        from scripts import check_bug_patterns as bp_mod

        fake_findings = [
            bp_mod.Finding(
                check_id="bare-1fr-grids",
                path="static/style.css",
                line_num=42,
                line=".bad { grid-template-columns: 1fr; }",
                message="bare 1fr",
            ),
        ]

        def fake_check():
            return fake_findings

        # Replace the CHECKS tuple list with a single synthetic check.
        original = bp_mod.CHECKS
        bp_mod.CHECKS = [("bare-1fr-grids", fake_check)]
        try:
            resp = authed_client.post(
                "/api/utilities/run-bug-pattern-scan"
            )
        finally:
            bp_mod.CHECKS = original

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["total"] == 1
        assert body["per_check"] == [
            {"label": "bare-1fr-grids", "count": 1},
        ]
        finding = body["findings"][0]
        assert finding["check_id"] == "bare-1fr-grids"
        assert finding["path"] == "static/style.css"
        assert finding["line_num"] == 42

    def test_inline_scan_one_failing_check_doesnt_abort_others(
        self, authed_client,
    ):
        """If one check raises, it gets recorded with `errored` in
        per_check but the other checks still run (no fail-fast)."""
        from scripts import check_bug_patterns as bp_mod

        def passing():
            return []

        def boom():
            raise RuntimeError("synthetic")

        original = bp_mod.CHECKS
        bp_mod.CHECKS = [
            ("pass-check", passing),
            ("boom-check", boom),
            ("pass-after-boom", passing),
        ]
        try:
            resp = authed_client.post(
                "/api/utilities/run-bug-pattern-scan"
            )
        finally:
            bp_mod.CHECKS = original

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["total"] == 0
        # All 3 checks reported in per_check, the middle one with
        # `errored` set + count 0.
        assert len(body["per_check"]) == 3
        labels = [c["label"] for c in body["per_check"]]
        assert labels == ["pass-check", "boom-check", "pass-after-boom"]
        boom_entry = body["per_check"][1]
        assert boom_entry["count"] == 0
        assert "errored" in boom_entry
        assert "synthetic" in boom_entry["errored"]
        assert "RuntimeError" in boom_entry["errored"]

    def test_inline_scan_calls_backlog_autofile(
        self, authed_client, monkeypatch,
    ):
        """#243 (2026-05-27): inline-scan endpoints must call
        backlog_autofile.run_for_audit so /utilities-triggered runs
        end up in BACKLOG.md (not just cron runs)."""
        from scripts import backlog_autofile
        from scripts import check_bug_patterns as bp_mod

        captured = {"audit_name": None, "count": None}

        def fake_autofile(audit_name, findings):
            captured["audit_name"] = audit_name
            captured["count"] = len(list(findings))

        monkeypatch.setattr(
            backlog_autofile, "run_for_audit", fake_autofile,
        )
        # Synthesize one finding so we can assert it propagated.
        fake = bp_mod.Finding(
            check_id="bare-1fr-grids",
            path="static/style.css",
            line_num=42,
            line=".bad { grid-template-columns: 1fr; }",
            message="bare 1fr",
        )
        original = bp_mod.CHECKS
        bp_mod.CHECKS = [("bare-1fr-grids", lambda: [fake])]
        try:
            resp = authed_client.post(
                "/api/utilities/run-bug-pattern-scan"
            )
        finally:
            bp_mod.CHECKS = original

        assert resp.status_code == 200
        assert captured["audit_name"] == "bug-pattern"
        assert captured["count"] == 1

    def test_inline_scan_dispatches_cron_workflow_for_autofile(
        self, authed_client, monkeypatch,
    ):
        """#244 (2026-05-27): after the in-process autofile, the
        endpoint must also dispatch the matching cron workflow via
        the GitHub Actions API so the BACKLOG.md change gets
        committed back to GitHub (Railway containers can't push).
        Each audit_name maps to a specific workflow YAML file.
        """
        import utilities_api

        dispatched = []
        monkeypatch.setattr(
            utilities_api, "_dispatch_github_workflow",
            lambda workflow_file: dispatched.append(workflow_file),
        )
        # Stub autofile to a no-op (covered separately).
        from scripts import backlog_autofile
        monkeypatch.setattr(
            backlog_autofile, "run_for_audit",
            lambda *a, **kw: None,
        )

        resp = authed_client.post(
            "/api/utilities/run-bug-pattern-scan"
        )
        assert resp.status_code == 200
        assert dispatched == ["weekly-bug-pattern-scan.yml"]

    def test_inline_scan_dispatch_failure_does_not_break_response(
        self, authed_client, monkeypatch,
    ):
        """If the workflow_dispatch fails (e.g. GITHUB_DISPATCH_TOKEN
        missing in dev), the inline scan response must still 200
        with findings — the dispatch is value-add for persistence,
        not load-bearing."""
        import utilities_api

        def boom(workflow_file):
            raise ValueError(
                "GITHUB_DISPATCH_TOKEN env var not configured",
            )
        monkeypatch.setattr(
            utilities_api, "_dispatch_github_workflow", boom,
        )
        from scripts import backlog_autofile
        monkeypatch.setattr(
            backlog_autofile, "run_for_audit",
            lambda *a, **kw: None,
        )
        resp = authed_client.post(
            "/api/utilities/run-bug-pattern-scan"
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert isinstance(body["total"], int)

    def test_inline_scan_autofile_failure_does_not_break_response(
        self, authed_client, monkeypatch,
    ):
        """If backlog_autofile crashes (e.g. BACKLOG.md missing the
        autofile section), the endpoint must still return the
        findings — autofile is a value-add, not a load-bearing dep."""
        from scripts import backlog_autofile

        def boom(audit_name, findings):
            raise ValueError("simulated autofile breakage")

        monkeypatch.setattr(
            backlog_autofile, "run_for_audit", boom,
        )
        resp = authed_client.post(
            "/api/utilities/run-bug-pattern-scan"
        )
        # Endpoint still 200 with findings — autofile breakage is
        # logged at WARNING but doesn't propagate to the user.
        assert resp.status_code == 200
        body = resp.get_json()
        assert isinstance(body["total"], int)

    def test_inline_scan_does_not_send_email(
        self, authed_client, monkeypatch,
    ):
        """The endpoint must NOT trigger the SendGrid email path that
        `main()` does — the UI inline-render IS the result channel."""
        from scripts import check_bug_patterns as bp_mod

        email_sent = []
        monkeypatch.setattr(
            bp_mod, "send_scan_email",
            lambda findings, *, per_check_counts: email_sent.append(True),
        )
        resp = authed_client.post(
            "/api/utilities/run-bug-pattern-scan"
        )
        assert resp.status_code == 200
        assert email_sent == []


class TestCoverageAuditAsync:
    """#229b (2026-05-27): async background-job pattern for the
    coverage audit. The audit takes ~30s (full pytest --cov run), so
    a synchronous request would hit gunicorn worker timeouts.

    Pattern: POST kicks off a subprocess in a daemon thread and returns
    immediately with {status: "running"}. Frontend polls GET status
    until it flips to "complete" or "error". Single-slot — a second
    POST while a run is in flight returns 409.

    #250 (2026-05-28): job state moved from module-level dict to a
    shared file in /tmp/ so all gunicorn workers see the same state.
    Tests use a per-test tempfile via the `coverage_state_file`
    fixture below so they don't pollute the real /tmp file (or each
    other's state).
    """

    @pytest.fixture(autouse=True)
    def coverage_state_file(self, tmp_path, monkeypatch):
        """#250: redirect the shared-state file to a per-test temp path
        so tests don't leak state between each other or into the real
        /tmp/taskmanager_coverage_audit_state.json. Auto-used by every
        test in this class — no opt-in needed.
        """
        import utilities_api
        monkeypatch.setattr(
            utilities_api,
            "_COVERAGE_JOB_STATE_PATH",
            tmp_path / "coverage_state.json",
        )
        # Start each test with idle state (no file present).
        # _read_coverage_job_state() returns the default idle dict
        # when the file is missing, so no setup needed.

    def test_run_endpoint_requires_auth(self, client):
        resp = client.post("/api/utilities/run-coverage-audit")
        assert resp.status_code in (302, 401, 403)

    def test_status_endpoint_requires_auth(self, client):
        resp = client.get("/api/utilities/coverage-audit-status")
        assert resp.status_code in (302, 401, 403)

    def test_run_endpoint_rejects_GET(self, client):
        # State-mutating endpoint — POST only (#190 / #185 rule).
        resp = client.get("/api/utilities/run-coverage-audit")
        assert resp.status_code in (302, 401, 403, 404, 405)

    def test_kickoff_returns_running_and_started_at(
        self, authed_client, monkeypatch,
    ):
        """POST should return immediately with {status: "running"}
        and a started_at timestamp. The actual subprocess is monkey-
        patched out so the test doesn't actually run pytest --cov.
        """
        import utilities_api

        # Patch the subprocess-runner so it doesn't actually shell out.
        # We just want to confirm the endpoint returns the expected
        # shape and updates the module-level state dict.
        monkeypatch.setattr(
            utilities_api,
            "_run_coverage_audit_subprocess",
            lambda json_path: None,
        )
        # Reset state so prior tests don't leave it in "running".
        utilities_api._write_coverage_job_state({
            "status": "idle",
            "started_at": None,
            "finished_at": None,
            "duration_seconds": None,
            "result": None,
            "error": None,
        })
        resp = authed_client.post("/api/utilities/run-coverage-audit")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "running"
        assert "started_at" in body
        assert body["estimated_duration_seconds"] == 30

    def test_state_persists_via_file_not_module_dict(
        self, authed_client,
    ):
        """#250 (2026-05-28) regression: job state is stored in a file
        at `_COVERAGE_JOB_STATE_PATH` (shared across gunicorn workers)
        rather than a module-level dict (per-worker, NOT shared). The
        original module-level implementation caused the polling
        endpoint to return "idle" if the request round-robin'd to a
        gunicorn worker that hadn't received the kickoff POST.

        Verify: writing state via the helper actually persists to the
        file path the module points at — so a different process /
        thread / worker can read the same data.
        """
        import json as _json

        import utilities_api

        utilities_api._write_coverage_job_state({
            "status": "running",
            "started_at": "2026-05-28T20:00:00+00:00",
            "finished_at": None,
            "duration_seconds": None,
            "result": None,
            "error": None,
        })
        # File should exist at the path the module is currently
        # configured to use (the fixture redirected this to tmp_path).
        path = utilities_api._COVERAGE_JOB_STATE_PATH
        assert path.exists(), (
            f"Expected state file at {path}; was not created. "
            "If module-level dict is used instead of a file, this test "
            "regresses to the cross-worker bug."
        )
        # Content matches what we wrote (reading via parse, not via
        # _read_coverage_job_state, so a buggy helper can't mask the
        # bug).
        on_disk = _json.loads(path.read_text(encoding="utf-8"))
        assert on_disk["status"] == "running"
        assert on_disk["started_at"] == "2026-05-28T20:00:00+00:00"

        # And the read helper returns the same shape.
        snapshot = utilities_api._read_coverage_job_state()
        assert snapshot == on_disk

    def test_status_endpoint_reads_from_file_not_module_dict(
        self, authed_client,
    ):
        """#250 regression: GET /coverage-audit-status reads from the
        shared file. Set state via the file directly (simulating
        another worker having written it), and verify the endpoint
        returns that state. If the endpoint read from a module dict,
        this test would see idle instead of running.
        """
        import json as _json

        import utilities_api

        # Write the state directly to the file (simulating a different
        # gunicorn worker that already handled the kickoff POST).
        path = utilities_api._COVERAGE_JOB_STATE_PATH
        path.write_text(_json.dumps({
            "status": "running",
            "started_at": "2026-05-28T20:30:00+00:00",
            "finished_at": None,
            "duration_seconds": None,
            "result": None,
            "error": None,
        }), encoding="utf-8")

        # Endpoint should reflect what's in the file, NOT a per-worker
        # module dict that was never touched.
        resp = authed_client.get("/api/utilities/coverage-audit-status")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "running"
        assert body["started_at"] == "2026-05-28T20:30:00+00:00"

    def test_kickoff_returns_409_when_already_running(
        self, authed_client, monkeypatch,
    ):
        """Single-slot semantics: a second POST while status is
        "running" returns 409 with a clear error message that the
        frontend uses to "join" the existing job rather than start
        a new one.
        """
        import utilities_api

        # Force the state into "running" so the kickoff sees an
        # in-flight job and bails.
        utilities_api._write_coverage_job_state({
            "status": "running",
            "started_at": "2026-05-27T12:00:00+00:00",
            "finished_at": None,
            "duration_seconds": None,
            "result": None,
            "error": None,
        })
        try:
            resp = authed_client.post(
                "/api/utilities/run-coverage-audit"
            )
            assert resp.status_code == 409
            body = resp.get_json()
            assert "already running" in body["error"].lower()
            assert body["started_at"] == "2026-05-27T12:00:00+00:00"
        finally:
            # Restore idle state so later tests aren't blocked.
            utilities_api._write_coverage_job_state({
                "status": "idle",
                "started_at": None,
                "finished_at": None,
                "duration_seconds": None,
                "result": None,
                "error": None,
            })

    def test_status_returns_state_snapshot(self, authed_client):
        """GET /coverage-audit-status returns the module-level state
        dict snapshot — the same shape regardless of status, with
        result populated when complete.
        """
        import utilities_api

        # Seed a fake "complete" state to confirm the snapshot pickup.
        fake_result = {
            "total": 0,
            "per_check": [
                {"label": "overall-coverage-drift", "count": 0},
                {"label": "per-file-coverage-drift", "count": 0},
                {"label": "critical-path-floors", "count": 0},
            ],
            "findings": [],
            "overall": 84.0,
        }
        utilities_api._write_coverage_job_state({
            "status": "complete",
            "started_at": "2026-05-27T12:00:00+00:00",
            "finished_at": "2026-05-27T12:00:30+00:00",
            "duration_seconds": 30.0,
            "result": fake_result,
            "error": None,
        })
        try:
            resp = authed_client.get(
                "/api/utilities/coverage-audit-status"
            )
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["status"] == "complete"
            assert body["result"] == fake_result
            assert body["error"] is None
            assert body["duration_seconds"] == 30.0
        finally:
            utilities_api._write_coverage_job_state({
                "status": "idle",
                "started_at": None,
                "finished_at": None,
                "duration_seconds": None,
                "result": None,
                "error": None,
            })

    def test_status_returns_error_on_subprocess_failure(
        self, authed_client,
    ):
        """When the background subprocess fails (e.g. pytest itself
        crashes), the state dict's `error` is populated and the UI
        renders the error message instead of trying to render a
        missing result."""
        import utilities_api

        utilities_api._write_coverage_job_state({
            "status": "error",
            "started_at": "2026-05-27T12:00:00+00:00",
            "finished_at": "2026-05-27T12:00:05+00:00",
            "duration_seconds": 5.0,
            "result": None,
            "error": "RuntimeError: subprocess returned exit 2",
        })
        try:
            resp = authed_client.get(
                "/api/utilities/coverage-audit-status"
            )
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["status"] == "error"
            assert "RuntimeError" in body["error"]
            assert body["result"] is None
        finally:
            utilities_api._write_coverage_job_state({
                "status": "idle",
                "started_at": None,
                "finished_at": None,
                "duration_seconds": None,
                "result": None,
                "error": None,
            })

    def test_subprocess_runner_writes_result_to_state(
        self, authed_client, monkeypatch, tmp_path,
    ):
        """The _run_coverage_audit_subprocess function should:
          - run check_test_coverage.py with --json-only OUT
          - parse the JSON output file
          - write the parsed payload into _coverage_job_state.result
          - flip status to "complete" + populate finished_at + duration
        Mocks subprocess.run so we don't actually invoke pytest.
        """
        import json
        import subprocess

        import utilities_api

        fake_payload = {
            "total": 1,
            "per_check": [
                {"label": "overall-coverage-drift", "count": 1},
            ],
            "findings": [
                {
                    "check_id": "overall-coverage-drift",
                    "path": "(repo)",
                    "line_num": 0,
                    "message": "84.0% < baseline 86.0% - 1pp",
                },
            ],
            "overall": 84.0,
        }
        json_path = tmp_path / "result.json"
        json_path.write_text(json.dumps(fake_payload), encoding="utf-8")

        # Mock subprocess.run so the wrapper "successfully" returns
        # without actually invoking pytest. Returncode 1 simulates
        # the audit finding non-clean state.
        class FakeProc:
            returncode = 1
            stdout = ""
            stderr = ""

        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: FakeProc(),
        )

        # Seed the state as "running" the way the kickoff endpoint
        # would have left it before spawning the thread.
        utilities_api._write_coverage_job_state({
            "status": "running",
            "started_at": "2026-05-27T12:00:00+00:00",
            "finished_at": None,
            "duration_seconds": None,
            "result": None,
            "error": None,
        })
        try:
            # Invoke the runner inline (no thread — we want the
            # test to be deterministic).
            utilities_api._run_coverage_audit_subprocess(str(json_path))

            assert utilities_api._read_coverage_job_state()["status"] == "complete"
            assert utilities_api._read_coverage_job_state()["result"] == fake_payload
            assert utilities_api._read_coverage_job_state()["error"] is None
            assert utilities_api._read_coverage_job_state()["finished_at"] is not None
            assert utilities_api._read_coverage_job_state()["duration_seconds"] is not None
        finally:
            utilities_api._write_coverage_job_state({
                "status": "idle",
                "started_at": None,
                "finished_at": None,
                "duration_seconds": None,
                "result": None,
                "error": None,
            })

    def test_subprocess_runner_errors_on_empty_result_file(
        self, authed_client, monkeypatch, tmp_path,
    ):
        """Regression for the 2026-05-27 Windows cp1252 bug: pytest
        crashes mid-run on UnicodeEncodeError when sys.stderr is a
        non-utf-8 file handle, the script exits with non-2 returncode
        but never writes the result JSON, and the wrapper would
        previously fall through to `json.loads("")` and surface a
        confusing JSONDecodeError. The empty-file guard surfaces a
        clearer "result file is empty" message with returncode +
        stderr_tail for post-mortem.
        """
        import subprocess

        import utilities_api

        json_path = tmp_path / "result.json"
        json_path.write_text("", encoding="utf-8")  # empty — bug shape

        class FakeProc:
            returncode = 1
            stdout = ""
            stderr = ""

        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: FakeProc(),
        )

        utilities_api._write_coverage_job_state({
            "status": "running",
            "started_at": "2026-05-27T12:00:00+00:00",
            "finished_at": None,
            "duration_seconds": None,
            "result": None,
            "error": None,
        })
        try:
            utilities_api._run_coverage_audit_subprocess(str(json_path))
            assert utilities_api._read_coverage_job_state()["status"] == "error"
            err = utilities_api._read_coverage_job_state()["error"]
            assert "result file is empty" in err
            assert "rc=1" in err
        finally:
            utilities_api._write_coverage_job_state({
                "status": "idle",
                "started_at": None,
                "finished_at": None,
                "duration_seconds": None,
                "result": None,
                "error": None,
            })

    def test_subprocess_runner_passes_utf8_encoding_to_child(
        self, authed_client, monkeypatch, tmp_path,
    ):
        """Regression for the 2026-05-27 Windows cp1252 bug: the
        subprocess env must include PYTHONIOENCODING=utf-8 so the
        child Python's sys.stdout/stderr can encode the non-ASCII
        characters in the script's progress messages (→ etc). Without
        this, the child crashes with UnicodeEncodeError on Windows
        whose locale codec is cp1252.
        """
        import subprocess

        import utilities_api

        captured_env = {}

        class FakeProc:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(*args, **kwargs):
            captured_env.update(kwargs.get("env") or {})
            return FakeProc()

        monkeypatch.setattr(subprocess, "run", fake_run)

        # Pre-create a valid result file so the wrapper reaches the
        # subprocess call without needing the script to actually run.
        json_path = tmp_path / "result.json"
        json_path.write_text(
            '{"total": 0, "per_check": [], "findings": [], "overall": 84.0}',
            encoding="utf-8",
        )

        utilities_api._write_coverage_job_state({
            "status": "running",
            "started_at": "2026-05-27T12:00:00+00:00",
            "finished_at": None,
            "duration_seconds": None,
            "result": None,
            "error": None,
        })
        try:
            utilities_api._run_coverage_audit_subprocess(str(json_path))
            assert captured_env.get("PYTHONIOENCODING") == "utf-8"
        finally:
            utilities_api._write_coverage_job_state({
                "status": "idle",
                "started_at": None,
                "finished_at": None,
                "duration_seconds": None,
                "result": None,
                "error": None,
            })

    def test_subprocess_runner_calls_autofile_with_findings(
        self, authed_client, monkeypatch, tmp_path,
    ):
        """#243 (2026-05-27): manual /utilities runs must also autofile
        their findings into BACKLOG.md so the operator doesn't have to
        wait for the next weekly cron to see the rows. We verify the
        subprocess runner adapts the JSON findings back to the
        attribute-shape backlog_autofile expects (`check_id`, `path`,
        `detail`) and calls `run_for_audit("coverage", ...)`.
        """
        import json
        import subprocess

        import utilities_api

        fake_payload = {
            "total": 2,
            "per_check": [
                {"label": "overall-coverage-drift", "count": 0},
                {"label": "per-file-coverage-drift", "count": 2},
            ],
            "findings": [
                {
                    "check_id": "per-file-coverage-drift",
                    "path": "auth.py",
                    "detail": "97.6% → 81.9% (tolerance 5pp)",
                },
                {
                    "check_id": "per-file-coverage-drift",
                    "path": "auth_api.py",
                    "detail": "100.0% → 43.5% (tolerance 5pp)",
                },
            ],
            "overall": 84.0,
        }
        json_path = tmp_path / "result.json"
        json_path.write_text(json.dumps(fake_payload), encoding="utf-8")

        class FakeProc:
            returncode = 1
            stdout = ""
            stderr = ""

        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: FakeProc(),
        )

        captured = {"audit_name": None, "findings": None}
        from scripts import backlog_autofile

        def fake_autofile(audit_name, findings):
            captured["audit_name"] = audit_name
            # Drain to list of dicts for assertion (findings are
            # SimpleNamespace instances).
            captured["findings"] = [
                {"check_id": f.check_id, "path": f.path, "detail": f.detail}
                for f in findings
            ]
        monkeypatch.setattr(
            backlog_autofile, "run_for_audit", fake_autofile,
        )

        utilities_api._write_coverage_job_state({
            "status": "running",
            "started_at": "2026-05-27T12:00:00+00:00",
            "finished_at": None,
            "duration_seconds": None,
            "result": None,
            "error": None,
        })
        try:
            utilities_api._run_coverage_audit_subprocess(str(json_path))
            assert captured["audit_name"] == "coverage"
            assert captured["findings"] is not None
            assert len(captured["findings"]) == 2
            assert captured["findings"][0]["path"] == "auth.py"
            assert captured["findings"][1]["check_id"] == (
                "per-file-coverage-drift"
            )
            # Job state still marked complete.
            assert utilities_api._read_coverage_job_state()["status"] == "complete"
        finally:
            utilities_api._write_coverage_job_state({
                "status": "idle",
                "started_at": None,
                "finished_at": None,
                "duration_seconds": None,
                "result": None,
                "error": None,
            })

    def test_subprocess_runner_records_error_on_exception(
        self, authed_client, monkeypatch, tmp_path,
    ):
        """If subprocess.run itself raises (e.g. TimeoutExpired,
        FileNotFoundError), the runner must populate state.error
        rather than letting the exception propagate to the daemon
        thread's uncaught handler."""
        import subprocess

        import utilities_api

        def boom(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="pytest", timeout=600)

        monkeypatch.setattr(subprocess, "run", boom)

        utilities_api._write_coverage_job_state({
            "status": "running",
            "started_at": "2026-05-27T12:00:00+00:00",
            "finished_at": None,
            "duration_seconds": None,
            "result": None,
            "error": None,
        })
        try:
            utilities_api._run_coverage_audit_subprocess(
                str(tmp_path / "nope.json"),
            )
            assert utilities_api._read_coverage_job_state()["status"] == "error"
            assert utilities_api._read_coverage_job_state()["error"] is not None
            assert "Timeout" in utilities_api._read_coverage_job_state()["error"] \
                or "timeout" in utilities_api._read_coverage_job_state()["error"].lower()
        finally:
            utilities_api._write_coverage_job_state({
                "status": "idle",
                "started_at": None,
                "finished_at": None,
                "duration_seconds": None,
                "result": None,
                "error": None,
            })
