"""Integration tests for the email digest (Step 15).

The daily digest is a plain-text email sent to the user's work address
containing today's tasks, overdue items, goal summaries, and a This Week
count. These tests verify:

1. **Digest content** — the correct tasks appear in the correct sections
2. **Sanitization** — task titles are cleaned before inserting into email
3. **SendGrid integration** — mocked so we never send real emails
4. **API endpoints** — preview and send-now work correctly
5. **Edge cases** — empty task lists, no API key configured, etc.

Key testing concepts used here:
- **Mocking** — replacing the real SendGrid API with a fake one so tests
  run without network access or API keys. We use ``monkeypatch`` to
  temporarily replace functions/environment variables during tests.
- **Content verification** — checking that specific strings appear in
  the generated digest text.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from models import Goal, GoalCategory, GoalPriority, Task, TaskType, Tier, db


def _make_task(**overrides) -> Task:
    """Helper to create a task directly in the database."""
    fields = {"title": "Digest test", "type": TaskType.WORK}
    fields.update(overrides)
    task = Task(**fields)
    db.session.add(task)
    db.session.commit()
    return task


def _make_goal(**overrides) -> Goal:
    """Helper to create a goal in the database."""
    fields = {
        "title": "Test goal",
        "category": GoalCategory.WORK,
        "priority": GoalPriority.MUST,
    }
    fields.update(overrides)
    goal = Goal(**fields)
    db.session.add(goal)
    db.session.commit()
    return goal


# --- Digest content -----------------------------------------------------------


class TestDigestContent:
    """Verify the digest text contains the right sections and data."""

    def test_contains_date_header(self, app):
        from digest_service import build_digest

        with app.app_context():
            body = build_digest()
        today_str = date.today().strftime("%A, %B %d, %Y")
        assert f"TASK DIGEST — {today_str}" in body

    def test_contains_today_section(self, app):
        from digest_service import build_digest

        with app.app_context():
            body = build_digest()
        assert "TODAY'S TASKS" in body

    def test_today_task_appears(self, app):
        from digest_service import build_digest

        with app.app_context():
            _make_task(title="Morning standup", tier=Tier.TODAY)
            body = build_digest()
        assert "Morning standup" in body

    def test_week_count_shown(self, app):
        from digest_service import build_digest

        with app.app_context():
            _make_task(title="Week item 1", tier=Tier.THIS_WEEK)
            _make_task(title="Week item 2", tier=Tier.THIS_WEEK)
            body = build_digest()
        assert "THIS WEEK REMAINING: 2 tasks" in body

    def test_past_7_days_summary_shows_completed_and_cancelled(self, app):
        """Backlog #25: digest surfaces both completed and cancelled
        counts from the past week, separately."""
        from digest_service import build_digest
        from models import TaskStatus, db

        with app.app_context():
            # Mix of statuses; only completed + cancelled should be counted
            d1 = _make_task(title="d1")
            d2 = _make_task(title="d2")
            c1 = _make_task(title="c1")
            d1.status = TaskStatus.ARCHIVED
            d2.status = TaskStatus.ARCHIVED
            c1.status = TaskStatus.CANCELLED
            db.session.commit()
            body = build_digest()
        assert "PAST 7 DAYS: 2 completed, 1 cancelled" in body

    def test_overdue_task_appears(self, app):
        from digest_service import build_digest

        with app.app_context():
            _make_task(
                title="Overdue report",
                tier=Tier.BACKLOG,
                due_date=date.today() - timedelta(days=5),
            )
            body = build_digest()
        assert "OVERDUE" in body
        assert "Overdue report" in body

    def test_due_today_from_other_tier(self, app):
        """Tasks due today but in non-Today tiers appear in a separate section."""
        from digest_service import build_digest

        with app.app_context():
            _make_task(
                title="Due today elsewhere",
                tier=Tier.THIS_WEEK,
                due_date=date.today(),
            )
            body = build_digest()
        assert "ALSO DUE TODAY" in body
        assert "Due today elsewhere" in body

    def test_goal_with_today_tasks(self, app):
        from digest_service import build_digest

        with app.app_context():
            goal = _make_goal(title="Stay Healthy")
            _make_task(
                title="Walk 30 min",
                tier=Tier.TODAY,
                goal_id=goal.id,
            )
            body = build_digest()
        assert "GOALS WITH ACTIVE TASKS TODAY" in body
        assert "Stay Healthy" in body

    def test_empty_today_shows_none(self, app):
        from digest_service import build_digest

        with app.app_context():
            body = build_digest()
        assert "(none)" in body

    def test_task_with_project_shown(self, app):
        """Tasks linked to a project show the project name in parentheses."""
        from digest_service import build_digest
        from models import Project, ProjectType

        with app.app_context():
            proj = Project(name="Portal", type=ProjectType.WORK)
            db.session.add(proj)
            db.session.commit()
            _make_task(
                title="Fix portal bug",
                tier=Tier.TODAY,
                project_id=proj.id,
            )
            body = build_digest()
        assert "(Portal)" in body

    def test_task_with_goal_shown(self, app):
        """Tasks linked to a goal show the goal name in brackets."""
        from digest_service import build_digest

        with app.app_context():
            goal = _make_goal(title="Career Growth")
            _make_task(
                title="Update resume",
                tier=Tier.TODAY,
                goal_id=goal.id,
            )
            body = build_digest()
        assert "[Goal: Career Growth]" in body

    def test_due_today_annotation(self, app):
        from digest_service import build_digest

        with app.app_context():
            _make_task(
                title="Submit report",
                tier=Tier.TODAY,
                due_date=date.today(),
            )
            body = build_digest()
        assert "(due today)" in body

    def test_footer_present(self, app):
        from digest_service import build_digest

        with app.app_context():
            body = build_digest()
        assert "Sent by your Task Manager" in body


# --- HTML body ----------------------------------------------------------------


class TestDigestHtml:
    """The digest now ships as multipart HTML + plain text. The HTML body
    is rendered via Jinja (templates/email/digest.html); these tests
    check that section data lands in the right places and that user-
    supplied content is HTML-escaped (Jinja autoescape, not raw)."""

    def test_html_contains_date_header(self, app):
        from digest_service import build_digest_html

        with app.app_context():
            html = build_digest_html()
        assert "Task Digest" in html
        today_str = date.today().strftime("%A, %B %d, %Y")
        assert today_str in html

    def test_html_includes_today_task(self, app):
        from digest_service import build_digest_html

        with app.app_context():
            _make_task(title="Morning standup", tier=Tier.TODAY)
            html = build_digest_html()
        assert "Morning standup" in html
        assert "<html" in html.lower()

    def test_html_includes_overdue_section(self, app):
        from digest_service import build_digest_html

        with app.app_context():
            _make_task(
                title="Overdue thing",
                tier=Tier.BACKLOG,
                due_date=date.today() - timedelta(days=2),
            )
            html = build_digest_html()
        assert "Overdue" in html
        assert "Overdue thing" in html

    def test_html_escapes_malicious_title(self, app):
        """Jinja autoescape must convert HTML in task titles to entities,
        otherwise a crafted title could inject markup into the email."""
        from digest_service import build_digest_html

        with app.app_context():
            _make_task(title="<script>evil()</script>", tier=Tier.TODAY)
            html = build_digest_html()
        assert "<script>evil" not in html
        assert "&lt;script&gt;evil" in html

    def test_html_overdue_appears_before_today(self, app):
        """Reorder per feature design: most urgent items at the top."""
        from digest_service import build_digest_html

        with app.app_context():
            _make_task(
                title="Overdue X",
                tier=Tier.BACKLOG,
                due_date=date.today() - timedelta(days=3),
            )
            _make_task(title="Today Y", tier=Tier.TODAY)
            html = build_digest_html()
        assert html.index("Overdue X") < html.index("Today Y")

    def test_html_cta_uses_app_url_when_set(self, app, monkeypatch):
        from digest_service import build_digest_html

        monkeypatch.setenv("APP_URL", "https://example.com/app")
        with app.app_context():
            html = build_digest_html()
        assert 'href="https://example.com/app"' in html

    def test_html_cta_omitted_when_app_url_unset(self, app, monkeypatch):
        from digest_service import build_digest_html

        monkeypatch.delenv("APP_URL", raising=False)
        with app.app_context():
            html = build_digest_html()
        assert "Open Task Manager" not in html


class TestDigestPlainTextOrder:
    """Plain-text digest reorders Overdue ahead of Today (mirrors HTML)."""

    def test_overdue_section_appears_before_today_section(self, app):
        from digest_service import build_digest

        with app.app_context():
            _make_task(
                title="Old report",
                tier=Tier.BACKLOG,
                due_date=date.today() - timedelta(days=4),
            )
            _make_task(title="Today work", tier=Tier.TODAY)
            body = build_digest()
        assert body.index("OVERDUE") < body.index("TODAY'S TASKS")


class TestDigestMultipart:
    """send_digest must attach BOTH text/plain and text/html parts so
    HTML clients see the styled email and plain-text clients still get
    a usable digest."""

    def test_send_attaches_both_html_and_plain(self, app, monkeypatch):
        from digest_service import send_digest

        monkeypatch.setenv("SENDGRID_API_KEY", "fake-key")
        captured = {}

        def _capture(api_key, from_email, to_email, subject, body_text, body_html):  # noqa: ARG001
            captured["body_text"] = body_text
            captured["body_html"] = body_html
            return True

        with (
            app.app_context(),
            patch("digest_service._sendgrid_send", side_effect=_capture),
        ):
            send_digest(to_email="test@example.com")

        assert "TASK DIGEST" in captured["body_text"]
        assert "<html" in captured["body_html"].lower()
        assert "Task Digest" in captured["body_html"]


class TestDigestPreviewHtml:
    """GET /api/digest/preview?format=html returns rendered HTML."""

    def test_html_preview_returns_text_html(self, authed_client):
        resp = authed_client.get("/api/digest/preview?format=html")
        assert resp.status_code == 200
        assert resp.mimetype == "text/html"
        assert b"<html" in resp.data.lower()
        assert b"Task Digest" in resp.data


# --- Sanitization -------------------------------------------------------------


class TestDigestSanitization:
    """Verify task content is sanitized before email insertion.

    Sanitization prevents control characters or unexpected formatting
    from appearing in the email body. This is a CLAUDE.md security
    requirement: 'sanitize task content before inserting into digest'.
    """

    def test_tabs_replaced(self, app):
        from digest_service import build_digest

        with app.app_context():
            _make_task(title="Has\ttab", tier=Tier.TODAY)
            body = build_digest()
        assert "\t" not in body
        assert "Has tab" in body

    def test_carriage_returns_removed(self, app):
        from digest_service import build_digest

        with app.app_context():
            _make_task(title="Has\rreturn", tier=Tier.TODAY)
            body = build_digest()
        assert "\r" not in body

    def test_whitespace_stripped(self, app):
        from digest_service import build_digest

        with app.app_context():
            _make_task(title="  Spaces  ", tier=Tier.TODAY)
            body = build_digest()
        assert "[ ] Spaces" in body


# --- SendGrid integration (mocked) -------------------------------------------


class TestSendDigest:
    """Verify the send_digest function calls SendGrid correctly.

    These tests use 'mocking' — replacing the real SendGrid client with
    a fake one (MagicMock) so we can verify the function's behavior
    without actually sending emails or needing a real API key.
    """

    def test_send_returns_true_on_success(self, app, monkeypatch):
        from digest_service import send_digest

        monkeypatch.setenv("SENDGRID_API_KEY", "fake-key")

        with (
            app.app_context(),
            patch("digest_service._sendgrid_send", return_value=True),
        ):
            result = send_digest(to_email="test@example.com", body_text="Test")
        assert result is True

    def test_send_returns_false_without_api_key(self, app, monkeypatch):
        from digest_service import send_digest

        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)

        with app.app_context():
            result = send_digest(to_email="test@example.com", body_text="Test")
        assert result is False

    def test_send_propagates_error_instead_of_returning_false(self, app, monkeypatch):
        """Behavior change in #50/ADR-031: send_digest used to swallow
        any exception and return False, killing the SendGrid error
        context (which is exactly what produced bug #47's misleading
        error message). Now exceptions propagate so the global error
        handler can shape them into useful JSON for the user."""
        from digest_service import send_digest

        monkeypatch.setenv("SENDGRID_API_KEY", "fake-key")

        with (
            app.app_context(),
            patch(
                "digest_service._sendgrid_send",
                side_effect=Exception("Network error"),
            ),
        ):
            try:
                send_digest(to_email="test@example.com", body_text="Test")
            except Exception as e:
                assert "Network error" in str(e)
            else:
                raise AssertionError("send_digest should have raised, not returned False")


# --- API endpoints ------------------------------------------------------------


class TestDigestPreviewAPI:
    """Verify GET /api/digest/preview returns the digest text."""

    def test_preview_returns_200(self, authed_client):
        resp = authed_client.get("/api/digest/preview")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "body" in body
        assert "TASK DIGEST" in body["body"]

    def test_preview_includes_today_tasks(self, authed_client, app):
        with app.app_context():
            _make_task(title="Preview task", tier=Tier.TODAY)

        resp = authed_client.get("/api/digest/preview")
        assert "Preview task" in resp.get_json()["body"]


class TestDigestSendAPI:
    """Verify POST /api/digest/send triggers email sending."""

    def test_send_without_to_email_returns_422(self, authed_client, monkeypatch):
        """If DIGEST_TO_EMAIL is not configured, return an error."""
        monkeypatch.delenv("DIGEST_TO_EMAIL", raising=False)
        resp = authed_client.post("/api/digest/send")
        assert resp.status_code == 422
        assert "DIGEST_TO_EMAIL" in resp.get_json()["error"]

    def test_send_without_api_key_returns_422(self, authed_client, monkeypatch):
        """If SENDGRID_API_KEY env var is unset, the API short-circuits
        with a 422 + clear "env var is not set" message. Status changed
        from 500 to 422 in #50/ADR-031: the user can act on this (set
        the env var), so it's a config problem (Unprocessable), not a
        server bug. Old behaviour returned 500 with the misleading
        hardcoded "check SENDGRID_API_KEY" message."""
        monkeypatch.setenv("DIGEST_TO_EMAIL", "work@example.com")
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        resp = authed_client.post("/api/digest/send")
        assert resp.status_code == 422
        assert "SENDGRID_API_KEY" in resp.get_json()["error"]

    def test_send_success(self, authed_client, monkeypatch):
        monkeypatch.setenv("DIGEST_TO_EMAIL", "work@example.com")
        monkeypatch.setenv("SENDGRID_API_KEY", "fake-key")

        with patch("digest_service._sendgrid_send", return_value=True):
            resp = authed_client.post("/api/digest/send")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "sent"


# --- Blueprint registration --------------------------------------------------


class TestDigestBlueprint:
    """Verify the digest_api blueprint is registered."""

    def test_blueprint_registered(self, app):
        assert "digest_api" in app.blueprints

    def test_routes_exist(self, app):
        rules = [r.rule for r in app.url_map.iter_rules()]
        assert "/api/digest/preview" in rules
        assert "/api/digest/send" in rules


# --- PR38 audit C4: digest cron callback direct test -----------------------


class TestDigestCronCallback:
    """The daily_digest scheduler job is registered in app.py via
    `scheduler.add_job(_send_scheduled_digest, ...)`. Existing tests
    cover `send_digest` in isolation. The CALLBACK that the scheduler
    actually invokes — including the env-var read, the app.app_context
    push, and the exception-swallow on EgressError — has no direct test.

    A refactor to the callback (e.g. forgetting to push app context, or
    accidentally inverting the to_email truthy check) would pass every
    other digest test and only surface in prod when the cron fires.
    These tests trigger the registered job by id, the same way the
    APScheduler thread would at 07:00."""

    @staticmethod
    def _job_func(app):
        """Boot the scheduler ourselves (TESTING mode skips it in
        create_app) and return the daily_digest job's callback.

        Important: we MUST tear down the scheduler + heartbeat or
        the next test that asserts "scheduler not registered" sees
        our leftover heartbeat file and fails."""
        import health
        from app import _start_digest_scheduler
        _start_digest_scheduler(app)
        try:
            job = health._scheduler.get_job("daily_digest")
            assert job is not None, "daily_digest job not registered"
            return job.func
        finally:
            # Stop the bg thread immediately — we only need the
            # callback reference, not actual scheduling.
            health._scheduler.shutdown(wait=False)
            health._scheduler = None
            # Wipe the heartbeat file so the next test that looks at
            # `check_digest()` doesn't see our stale "running":True row.
            try:
                if health.HEARTBEAT_PATH.exists():
                    health.HEARTBEAT_PATH.unlink()
            except OSError:
                pass

    def test_callback_runs_send_digest_when_to_email_set(self, app, monkeypatch):
        """Job-by-id trigger calls send_digest with the configured to_email."""
        monkeypatch.setenv("DIGEST_TO_EMAIL", "test-recipient@example.com")
        sent = []
        def _stub_send(to_email, **kwargs):  # noqa: ARG001
            sent.append(to_email)
        monkeypatch.setattr("digest_service.send_digest", _stub_send)
        callback = self._job_func(app)
        callback()
        assert sent == ["test-recipient@example.com"], (
            f"Expected callback to call send_digest with env DIGEST_TO_EMAIL; got {sent}."
        )

    def test_callback_no_op_when_to_email_unset(self, app, monkeypatch):
        """Without DIGEST_TO_EMAIL the callback returns early — no send."""
        monkeypatch.delenv("DIGEST_TO_EMAIL", raising=False)
        sent = []
        monkeypatch.setattr(
            "digest_service.send_digest",
            lambda *a, **kw: sent.append(a),
        )
        callback = self._job_func(app)
        callback()
        assert sent == [], "Callback should NOT call send_digest when DIGEST_TO_EMAIL is unset."

    def test_callback_swallows_send_failure(self, app, monkeypatch):
        """An EgressError (or any Exception) in send_digest must be
        logged + swallowed, not re-raised — the scheduler thread must
        survive so future jobs still run."""
        monkeypatch.setenv("DIGEST_TO_EMAIL", "test-recipient@example.com")
        def _boom(*a, **kw):
            raise RuntimeError("simulated SendGrid 500")
        monkeypatch.setattr("digest_service.send_digest", _boom)
        callback = self._job_func(app)
        # Should NOT raise — if it did, the scheduler thread would die
        # and every subsequent job (recurring spawn, tomorrow roll,
        # heartbeat) would silently stop.
        callback()
