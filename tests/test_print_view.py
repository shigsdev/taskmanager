"""Integration tests for the print view (Step 14).

The print view at /print is a clean, printer-friendly page that shows:
- Overdue tasks (past due date, not in Today tier)
- Today's tasks
- This Week's tasks
- A blank notes area
- A print button (hidden when actually printing via @media print CSS)

Unlike the main board (which renders via JavaScript), the print view is
**server-side rendered** — the Flask route queries tasks from the database
and passes them directly to the Jinja2 template. This means the HTML
already contains the task data when it arrives in the browser, so it
prints correctly without needing JavaScript.
"""
from __future__ import annotations

from datetime import date, timedelta

import auth
from models import Task, TaskStatus, TaskType, Tier, db


def _make_task(**overrides) -> Task:
    """Helper to create a task directly in the database."""
    fields = {"title": "Print test", "type": TaskType.WORK}
    fields.update(overrides)
    task = Task(**fields)
    db.session.add(task)
    db.session.commit()
    return task


# --- Page rendering -----------------------------------------------------------


class TestPrintPageRendering:
    """Verify the /print page renders correctly."""

    def test_renders_200(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        resp = client.get("/print")
        assert resp.status_code == 200

    def test_contains_print_date(self, client, monkeypatch):
        """The page header should show today's date."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/print").data.decode()
        today_str = date.today().strftime("%A, %B %d, %Y")
        assert today_str in html

    def test_contains_print_button(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/print").data.decode()
        assert "window.print()" in html

    def test_contains_back_link(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/print").data.decode()
        assert "Back to Tasks" in html

    def test_has_today_section(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/print").data.decode()
        assert 'id="printToday"' in html

    def test_has_week_section(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/print").data.decode()
        assert 'id="printWeek"' in html

    def test_has_notes_area(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/print").data.decode()
        assert 'id="printNotes"' in html

    def test_has_print_media_query(self, client, monkeypatch):
        """@media print CSS hides the print button when actually printing."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/print").data.decode()
        assert "@media print" in html

    def test_no_nav_chrome(self, client, monkeypatch):
        """Print view is standalone — no nav bar, no base.html header."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/print").data.decode()
        # Should NOT contain the main nav elements
        assert 'class="nav"' not in html
        assert 'id="captureInput"' not in html


# --- Task content in print view -----------------------------------------------


class TestPrintViewContent:
    """Verify that tasks appear in the correct sections."""

    def test_today_task_appears(self, client, monkeypatch, app):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        with app.app_context():
            _make_task(title="Today task", tier=Tier.TODAY)

        html = client.get("/print").data.decode()
        assert "Today task" in html

    def test_week_task_appears(self, client, monkeypatch, app):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        with app.app_context():
            _make_task(title="Week task", tier=Tier.THIS_WEEK)

        html = client.get("/print").data.decode()
        assert "Week task" in html

    def test_backlog_task_excluded(self, client, monkeypatch, app):
        """Backlog tasks should NOT appear on the print view."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        with app.app_context():
            _make_task(title="Backlog task", tier=Tier.BACKLOG)

        html = client.get("/print").data.decode()
        assert "Backlog task" not in html

    def test_freezer_task_excluded(self, client, monkeypatch, app):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        with app.app_context():
            _make_task(title="Frozen task", tier=Tier.FREEZER)

        html = client.get("/print").data.decode()
        assert "Frozen task" not in html

    def test_deleted_task_excluded(self, client, monkeypatch, app):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        with app.app_context():
            _make_task(
                title="Deleted task",
                tier=Tier.TODAY,
                status=TaskStatus.DELETED,
            )

        html = client.get("/print").data.decode()
        assert "Deleted task" not in html

    def test_overdue_task_appears(self, client, monkeypatch, app):
        """Tasks past due date (not in Today) should appear in Overdue section."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        with app.app_context():
            _make_task(
                title="Overdue task",
                tier=Tier.BACKLOG,
                due_date=date.today() - timedelta(days=3),
            )

        html = client.get("/print").data.decode()
        assert "Overdue task" in html
        assert 'id="printOverdue"' in html

    def test_due_date_shown(self, client, monkeypatch, app):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        tomorrow = date.today() + timedelta(days=1)
        with app.app_context():
            _make_task(
                title="Due soon",
                tier=Tier.TODAY,
                due_date=tomorrow,
            )

        html = client.get("/print").data.decode()
        assert tomorrow.isoformat() in html

    def test_checklist_items_shown(self, client, monkeypatch, app):
        """Checklist items should render inline for each task."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        with app.app_context():
            _make_task(
                title="With checklist",
                tier=Tier.TODAY,
                checklist=[
                    {"id": "1", "text": "Step A", "checked": True},
                    {"id": "2", "text": "Step B", "checked": False},
                ],
            )

        html = client.get("/print").data.decode()
        assert "Step A" in html
        assert "Step B" in html

    def test_empty_today_shows_message(self, client, monkeypatch):
        """When no today tasks exist, show a helpful empty state."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/print").data.decode()
        assert "No tasks for today" in html

    def test_empty_week_shows_message(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/print").data.decode()
        assert "No tasks this week" in html

    def test_task_type_shown(self, client, monkeypatch, app):
        """Each task shows its type (work/personal) as metadata."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        with app.app_context():
            _make_task(title="Work item", tier=Tier.TODAY, type=TaskType.WORK)

        html = client.get("/print").data.decode()
        assert "work" in html


# --- Auth requirements --------------------------------------------------------


class TestPrintAuth:
    """Print view requires authentication like all other pages."""

    def test_requires_auth(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/print")
        assert resp.status_code == 302

    def test_rejects_wrong_email(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "bad@example.com")
        resp = client.get("/print")
        assert resp.status_code == 403


# --- Nav link present on other pages ------------------------------------------


class TestPrintNavLink:
    """Verify the Print link appears in the navigation on other pages."""

    def test_index_has_print_link(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert "/print" in html

    def test_goals_has_print_link(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/goals").data.decode()
        assert "/print" in html

    def test_review_has_print_link(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/review").data.decode()
        assert "/print" in html
