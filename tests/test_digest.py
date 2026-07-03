"""Integration tests for the email digest (Step 15).

The daily digest is a plain-text email sent to the user's work address
containing today's tasks, overdue items, goal summaries, and a This Week
count. These tests verify:

1. **Digest content** — the correct tasks appear in the correct sections
2. **Sanitization** — task titles are cleaned before inserting into email
3. **SMTP integration** — mocked so we never send real emails
4. **API endpoints** — preview and send-now work correctly
5. **Edge cases** — empty task lists, no credentials configured, etc.

Key testing concepts used here:
- **Mocking** — replacing the real SMTP sender with a fake one so tests
  run without network access or credentials. We use ``monkeypatch`` to
  temporarily replace functions/environment variables during tests.
- **Content verification** — checking that specific strings appear in
  the generated digest text.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

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

    def test_html_today_appears_before_overdue(self, app):
        """#212 (2026-05-23): Today leads the digest; Overdue moved to a
        warning-style trailer at the END so the morning opens
        forward-looking. Inversion of the prior order."""
        from digest_service import build_digest_html

        with app.app_context():
            _make_task(
                title="Overdue X",
                tier=Tier.BACKLOG,
                due_date=date.today() - timedelta(days=3),
            )
            _make_task(title="Today Y", tier=Tier.TODAY)
            html = build_digest_html()
        assert html.index("Today Y") < html.index("Overdue X")

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


class TestDigestOverdueLabelCorrectness:
    """PR62 audit fix #5: future-dated Today-tier tasks were mislabeled
    as overdue in the plain-text digest."""

    def test_future_dated_today_task_not_labeled_overdue(self, app):
        from digest_service import build_digest

        with app.app_context():
            _make_task(
                title="Future plan",
                tier=Tier.TODAY,
                due_date=date.today() + timedelta(days=14),
            )
            body = build_digest()
        assert "Future plan" in body
        # Must NOT show "(overdue: ...)" for a future date
        assert "overdue" not in body.split("Future plan")[1].split("\n")[0]
        # Must show "(due ...)" instead
        future_pretty = (date.today() + timedelta(days=14)).strftime("%b %d")
        assert f"(due {future_pretty})" in body

    def test_past_dated_task_still_labeled_overdue(self, app):
        from digest_service import build_digest

        with app.app_context():
            _make_task(
                title="Real overdue",
                tier=Tier.BACKLOG,
                due_date=date.today() - timedelta(days=3),
            )
            body = build_digest()
        # OVERDUE section heading is present
        assert "OVERDUE" in body
        assert "Real overdue" in body


class TestDigestInactiveProjectAndDoneGoalFiltered:
    """PR62 audit fix #14: per-task lines were exposing inactive project
    names and DONE goal titles. The goal-section filter didn't reach the
    per-task `view`."""

    def test_inactive_project_name_not_shown_in_task_line(self, app):
        from digest_service import build_digest
        from models import Project, ProjectType

        with app.app_context():
            proj = Project(name="DEAD-PROJECT", type=ProjectType.WORK, is_active=False)
            db.session.add(proj)
            db.session.commit()
            _make_task(title="Linked task", tier=Tier.TODAY, project_id=proj.id)
            body = build_digest()
        assert "Linked task" in body
        # Inactive project name must NOT appear next to the task line.
        assert "DEAD-PROJECT" not in body

    def test_done_goal_title_not_shown_in_task_line(self, app):
        from digest_service import build_digest
        from models import GoalStatus

        with app.app_context():
            goal = _make_goal(title="DONE-GOAL")
            goal.status = GoalStatus.DONE
            db.session.commit()
            _make_task(title="Linked task 2", tier=Tier.TODAY, goal_id=goal.id)
            body = build_digest()
        assert "Linked task 2" in body
        # Done goal title must NOT appear in the task line.
        assert "DONE-GOAL" not in body


class TestSafeAppUrl:
    """PR62 audit fix #22: scheme-allowlist APP_URL before it lands in
    the email <a href> CTA button."""

    def test_https_app_url_passes_through(self, app, monkeypatch):
        from digest_service import build_digest_html

        monkeypatch.setenv("APP_URL", "https://example.com/app")
        with app.app_context():
            html = build_digest_html()
        assert 'href="https://example.com/app"' in html

    def test_javascript_scheme_blocked(self, app, monkeypatch):
        from digest_service import build_digest_html

        monkeypatch.setenv("APP_URL", "javascript:alert(1)")
        with app.app_context():
            html = build_digest_html()
        # CTA must NOT render with a malicious scheme.
        assert "javascript:" not in html
        assert "Open Task Manager" not in html

    def test_http_scheme_blocked(self, app, monkeypatch):
        """Operator-set http:// (e.g. accidental local-dev push) should
        not produce an unencrypted CTA in shipped emails."""
        from digest_service import build_digest_html

        monkeypatch.setenv("APP_URL", "http://localhost:5000")
        with app.app_context():
            html = build_digest_html()
        assert "Open Task Manager" not in html


class TestDigestPlainTextOrder:
    """#212 (2026-05-23): plain-text digest leads with TODAY'S TASKS;
    OVERDUE is now a warning-style trailer at the END (and only
    emitted when there IS overdue). Mirrors the HTML order."""

    def test_today_section_appears_before_overdue_section(self, app):
        from digest_service import build_digest

        with app.app_context():
            _make_task(
                title="Old report",
                tier=Tier.BACKLOG,
                due_date=date.today() - timedelta(days=4),
            )
            _make_task(title="Today work", tier=Tier.TODAY)
            body = build_digest()
        # Today leads; OVERDUE trails.
        assert body.index("TODAY'S TASKS") < body.index("OVERDUE")
        # The Overdue trailer carries a ⚠ marker so it reads as a
        # warning, not as a fresh top-of-digest section.
        assert "⚠ OVERDUE" in body


class TestDigestMultipart:
    """send_digest must attach BOTH text/plain and text/html parts so
    HTML clients see the styled email and plain-text clients still get
    a usable digest."""

    def test_send_attaches_both_html_and_plain(self, app, monkeypatch):
        from digest_service import send_digest

        monkeypatch.setenv("SMTP_USERNAME", "sender@gmail.com")
        monkeypatch.setenv("SMTP_PASSWORD", "fake-app-password")
        captured = {}

        def _capture(*, body_text, body_html, **kwargs):  # noqa: ARG001
            captured["body_text"] = body_text
            captured["body_html"] = body_html
            return True

        with (
            app.app_context(),
            patch("digest_service._smtp_send", side_effect=_capture),
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


# --- SMTP integration (mocked) -----------------------------------------------


class TestSendDigest:
    """Verify the send_digest function calls the SMTP sender correctly.

    These tests use 'mocking' — replacing the real ``_smtp_send`` with a
    fake so we can verify the function's behavior without opening a real
    SMTP connection or needing live credentials.
    """

    def test_send_returns_true_on_success(self, app, monkeypatch):
        from digest_service import send_digest

        monkeypatch.setenv("SMTP_USERNAME", "sender@gmail.com")
        monkeypatch.setenv("SMTP_PASSWORD", "fake-app-password")

        with (
            app.app_context(),
            patch("digest_service._smtp_send", return_value=True),
        ):
            result = send_digest(to_email="test@example.com", body_text="Test")
        assert result is True

    def test_send_returns_false_without_credentials(self, app, monkeypatch):
        from digest_service import send_digest

        monkeypatch.delenv("SMTP_USERNAME", raising=False)
        monkeypatch.delenv("SMTP_PASSWORD", raising=False)

        with app.app_context():
            result = send_digest(to_email="test@example.com", body_text="Test")
        assert result is False

    def test_send_propagates_error_instead_of_returning_false(self, app, monkeypatch):
        """Behavior change in #50/ADR-031: send_digest used to swallow
        any exception and return False, killing the send error context
        (which is exactly what produced bug #47's misleading error
        message). Now exceptions propagate so the global error handler
        can shape them into useful JSON for the user."""
        from digest_service import send_digest

        monkeypatch.setenv("SMTP_USERNAME", "sender@gmail.com")
        monkeypatch.setenv("SMTP_PASSWORD", "fake-app-password")

        with (
            app.app_context(),
            patch(
                "digest_service._smtp_send",
                side_effect=Exception("Network error"),
            ),
        ):
            try:
                send_digest(to_email="test@example.com", body_text="Test")
            except Exception as e:
                assert "Network error" in str(e)
            else:
                raise AssertionError("send_digest should have raised, not returned False")


class TestSmtpSend:
    """Unit tests for the low-level SMTP sender (``_smtp_send``)."""

    def _kwargs(self, **over):
        base = {
            "host": "smtp.example.com",
            "port": 587,
            "username": "sender@gmail.com",
            "password": "super-secret-pw",
            "from_email": "sender@gmail.com",
            "to_email": "rcpt@example.com",
            "subject": "S",
            "body_text": "plain",
            "body_html": "<p>html</p>",
        }
        base.update(over)
        return base

    def test_starttls_login_and_multipart_send(self):
        from digest_service import _smtp_send

        smtp_instance = MagicMock()
        cm = MagicMock()
        cm.__enter__.return_value = smtp_instance

        with patch("smtplib.SMTP", return_value=cm) as smtp_cls:
            result = _smtp_send(**self._kwargs())

        assert result is True
        smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=30)
        smtp_instance.starttls.assert_called_once()
        smtp_instance.login.assert_called_once_with(
            "sender@gmail.com", "super-secret-pw"
        )
        smtp_instance.send_message.assert_called_once()
        sent_msg = smtp_instance.send_message.call_args.args[0]
        assert sent_msg["Subject"] == "S"
        assert sent_msg["From"] == "sender@gmail.com"
        assert sent_msg["To"] == "rcpt@example.com"
        assert sent_msg.is_multipart()  # both text/plain + text/html parts

    def test_failure_raises_egress_without_password(self):
        from digest_service import _smtp_send
        from egress import EgressError

        smtp_instance = MagicMock()
        cm = MagicMock()
        cm.__enter__.return_value = smtp_instance
        # Simulate an auth error whose message echoes the password — the
        # surfaced EgressError must NOT include it (CLAUDE.md log-hygiene).
        smtp_instance.login.side_effect = Exception("535 nope super-secret-pw")

        with patch("smtplib.SMTP", return_value=cm), pytest.raises(EgressError) as exc:
            _smtp_send(**self._kwargs())

        assert "super-secret-pw" not in str(exc.value)


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

    def test_send_without_credentials_returns_422(self, authed_client, monkeypatch):
        """If the SMTP credentials are unset, the API short-circuits with a
        422 + clear "not set" message. Status changed from 500 to 422 in
        #50/ADR-031: the user can act on this (set the env vars), so it's a
        config problem (Unprocessable), not a server bug."""
        monkeypatch.setenv("DIGEST_TO_EMAIL", "work@example.com")
        monkeypatch.delenv("SMTP_USERNAME", raising=False)
        monkeypatch.delenv("SMTP_PASSWORD", raising=False)
        resp = authed_client.post("/api/digest/send")
        assert resp.status_code == 422
        assert "SMTP_USERNAME" in resp.get_json()["error"]

    def test_send_success(self, authed_client, monkeypatch):
        monkeypatch.setenv("DIGEST_TO_EMAIL", "work@example.com")
        monkeypatch.setenv("SMTP_USERNAME", "sender@gmail.com")
        monkeypatch.setenv("SMTP_PASSWORD", "fake-app-password")

        with patch("digest_service._smtp_send", return_value=True):
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

    def test_callback_records_ok_on_success(self, app, monkeypatch):
        """#286: a successful scheduled send persists status=ok so
        /healthz can report the last good send."""
        from digest_service import get_last_send_result
        monkeypatch.setenv("DIGEST_TO_EMAIL", "test-recipient@example.com")
        monkeypatch.setattr("digest_service.send_digest", lambda *a, **kw: True)
        callback = self._job_func(app)
        callback()
        with app.app_context():
            rec = get_last_send_result()
        assert rec is not None and rec["status"] == "ok"

    def test_callback_records_fail_on_error(self, app, monkeypatch):
        """#286: the 2026-06-07 incident — SendGrid 401 quota. The
        scheduled callback must persist status=fail + the error so the
        silent failure surfaces on /healthz."""
        from digest_service import get_last_send_result
        monkeypatch.setenv("DIGEST_TO_EMAIL", "test-recipient@example.com")
        def _boom(*a, **kw):
            raise RuntimeError("SendGrid returned HTTP 401: Maximum credits exceeded")
        monkeypatch.setattr("digest_service.send_digest", _boom)
        callback = self._job_func(app)
        callback()
        with app.app_context():
            rec = get_last_send_result()
        assert rec is not None and rec["status"] == "fail"
        assert "401" in rec["error"]


class TestDigestLastSendRecord:
    """#286: persist the most recent digest-send outcome in AppSetting so
    a silent SendGrid failure becomes a visible /healthz signal."""

    def test_record_then_read_ok(self, app):
        from digest_service import get_last_send_result, record_send_result
        with app.app_context():
            record_send_result(status="ok")
            rec = get_last_send_result()
        assert rec["status"] == "ok"
        assert "at" in rec

    def test_record_fail_includes_error(self, app):
        from digest_service import get_last_send_result, record_send_result
        with app.app_context():
            record_send_result(status="fail", error="SendGrid HTTP 401: credits")
            rec = get_last_send_result()
        assert rec["status"] == "fail"
        assert "401" in rec["error"]

    def test_record_upserts_latest_wins(self, app):
        """Only one row per the well-known key — the newest result wins."""
        from digest_service import get_last_send_result, record_send_result
        from models import AppSetting, db
        with app.app_context():
            record_send_result(status="fail", error="first")
            record_send_result(status="ok")
            assert get_last_send_result()["status"] == "ok"
            count = db.session.query(AppSetting).filter_by(
                key="digest_last_send"
            ).count()
        assert count == 1

    def test_get_returns_none_when_never_recorded(self, app):
        from digest_service import get_last_send_result
        with app.app_context():
            assert get_last_send_result() is None

    def test_error_is_capped_under_column_limit(self, app):
        """AppSetting.value is String(500); a huge error must not overflow."""
        from digest_service import get_last_send_result, record_send_result
        with app.app_context():
            record_send_result(status="fail", error="x" * 5000)
            rec = get_last_send_result()
        assert rec["status"] == "fail"
        assert len(rec["error"]) <= 300

    def test_error_is_scrubbed_before_storage(self, app):
        """#288: the stored error is republished on unauthenticated
        /healthz, so emails/keys must be redacted BEFORE persistence —
        the app_logs scrubber never sees this copy."""
        from digest_service import get_last_send_result, record_send_result
        with app.app_context():
            record_send_result(
                status="fail",
                error="SendGrid rejected recipient user@example.com "
                "(Authorization: Bearer SG.abc123xyz)",
            )
            rec = get_last_send_result()
        assert "user@example.com" not in rec["error"]
        assert "SG.abc123xyz" not in rec["error"]
        assert "rejected recipient" in rec["error"]  # diagnostics survive

    def test_manual_send_success_records_ok(self, authed_client, monkeypatch):
        """A manual resend that succeeds clears the alert (records ok)."""
        from digest_service import get_last_send_result
        monkeypatch.setenv("DIGEST_TO_EMAIL", "work@example.com")
        monkeypatch.setenv("SMTP_USERNAME", "sender@gmail.com")
        monkeypatch.setenv("SMTP_PASSWORD", "fake-app-password")
        with patch("digest_service._smtp_send", return_value=True):
            resp = authed_client.post("/api/digest/send")
        assert resp.status_code == 200
        assert get_last_send_result()["status"] == "ok"
