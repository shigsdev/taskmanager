"""Tests for the /api/utilities/* endpoints (#222, 2026-05-24).

OAuth-gated UI wrappers over the same backfill logic exposed via
admin-token-gated /api/debug/backfill/clear-stale-next-week-due-dates.
This test file covers the route registration, auth, and the
count/run pair against a known DB state.
"""
from __future__ import annotations

from datetime import timedelta

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
