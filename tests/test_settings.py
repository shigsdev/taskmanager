"""Integration tests for the settings page (Step 18).

The settings page is a read-only dashboard that shows:
- App statistics (task/goal/recurring counts)
- External service configuration status (never reveals keys)
- Import history from the audit log
- Digest preview and send actions

Key testing concepts:
- **Security** — API key values are never exposed, only boolean status
- **Statistics** — counts reflect actual DB state
- **Import history** — entries from ImportLog are returned newest first
"""
from __future__ import annotations

import auth
from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    ImportLog,
    RecurringFrequency,
    RecurringTask,
    Task,
    TaskStatus,
    TaskType,
    Tier,
    db,
)

# --- Service status -----------------------------------------------------------


class TestServiceStatus:
    """Verify GET /api/settings/status returns config status."""

    def test_returns_status(self, authed_client):
        resp = authed_client.get("/api/settings/status")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "google_oauth" in body
        assert "google_vision" in body
        assert "anthropic" in body
        assert "sendgrid" in body

    def test_google_oauth_shows_configured(self, authed_client, monkeypatch):
        """OAuth is set in conftest, so should show True."""
        resp = authed_client.get("/api/settings/status")
        assert resp.get_json()["google_oauth"] is True

    def test_unconfigured_key_shows_false(self, authed_client, monkeypatch):
        monkeypatch.delenv("GOOGLE_VISION_API_KEY", raising=False)
        resp = authed_client.get("/api/settings/status")
        assert resp.get_json()["google_vision"] is False

    def test_configured_key_shows_true(self, authed_client, monkeypatch):
        monkeypatch.setenv("SENDGRID_API_KEY", "fake-key")
        resp = authed_client.get("/api/settings/status")
        assert resp.get_json()["sendgrid"] is True

    def test_never_reveals_key_values(self, authed_client, monkeypatch):
        monkeypatch.setenv("SENDGRID_API_KEY", "super-secret-key")
        resp = authed_client.get("/api/settings/status")
        body_str = resp.get_data(as_text=True)
        assert "super-secret-key" not in body_str

    def test_digest_email_shown_as_boolean(self, authed_client, monkeypatch):
        """digest_email returns True when set — never exposes the actual address."""
        monkeypatch.setenv("DIGEST_TO_EMAIL", "work@example.com")
        resp = authed_client.get("/api/settings/status")
        data = resp.get_json()
        assert data["digest_email"] is True
        # Verify the actual email address is not in the response
        assert "work@example.com" not in resp.get_data(as_text=True)

    def test_digest_email_false_when_not_set(self, authed_client, monkeypatch):
        monkeypatch.delenv("DIGEST_TO_EMAIL", raising=False)
        resp = authed_client.get("/api/settings/status")
        assert resp.get_json()["digest_email"] is False

    def test_digest_from_never_leaks_address(self, authed_client, monkeypatch):
        """digest_from returns True when set — never exposes the actual address."""
        monkeypatch.setenv("DIGEST_FROM_EMAIL", "noreply@example.com")
        resp = authed_client.get("/api/settings/status")
        data = resp.get_json()
        assert data["digest_from"] is True
        assert "noreply@example.com" not in resp.get_data(as_text=True)


# --- App statistics -----------------------------------------------------------


class TestAppStats:
    """Verify GET /api/settings/stats returns correct counts."""

    def test_empty_db_returns_zeros(self, authed_client):
        resp = authed_client.get("/api/settings/stats")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["total_tasks"] == 0
        assert body["active_tasks"] == 0
        assert body["total_goals"] == 0
        assert body["recurring_templates"] == 0

    def test_counts_active_tasks(self, authed_client, app):
        with app.app_context():
            db.session.add(Task(
                title="Active", type=TaskType.WORK, tier=Tier.INBOX,
            ))
            db.session.add(Task(
                title="Deleted", type=TaskType.WORK, tier=Tier.INBOX,
                status=TaskStatus.DELETED,
            ))
            db.session.commit()

        resp = authed_client.get("/api/settings/stats")
        body = resp.get_json()
        assert body["total_tasks"] == 2
        assert body["active_tasks"] == 1

    def test_counts_goals(self, authed_client, app):
        with app.app_context():
            db.session.add(Goal(
                title="Active goal",
                category=GoalCategory.WORK,
                priority=GoalPriority.SHOULD,
            ))
            db.session.add(Goal(
                title="Inactive goal",
                category=GoalCategory.WORK,
                priority=GoalPriority.SHOULD,
                is_active=False,
            ))
            db.session.commit()

        resp = authed_client.get("/api/settings/stats")
        assert resp.get_json()["total_goals"] == 1

    def test_counts_recurring(self, authed_client, app):
        with app.app_context():
            db.session.add(RecurringTask(
                title="Daily task",
                frequency=RecurringFrequency.DAILY,
                type=TaskType.PERSONAL,
            ))
            db.session.commit()

        resp = authed_client.get("/api/settings/stats")
        assert resp.get_json()["recurring_templates"] == 1


# --- Import history -----------------------------------------------------------


class TestImportHistory:
    """Verify GET /api/settings/imports returns audit log."""

    def test_empty_returns_empty_list(self, authed_client):
        resp = authed_client.get("/api/settings/imports")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_returns_import_entries(self, authed_client, app):
        with app.app_context():
            db.session.add(ImportLog(
                source="onenote_test", task_count=5,
            ))
            db.session.add(ImportLog(
                source="excel_goals", task_count=3,
            ))
            db.session.commit()

        resp = authed_client.get("/api/settings/imports")
        body = resp.get_json()
        assert len(body) == 2

    def test_entries_have_expected_fields(self, authed_client, app):
        with app.app_context():
            db.session.add(ImportLog(
                source="test_source", task_count=10,
            ))
            db.session.commit()

        resp = authed_client.get("/api/settings/imports")
        entry = resp.get_json()[0]
        assert "id" in entry
        assert entry["source"] == "test_source"
        assert entry["task_count"] == 10
        assert "imported_at" in entry

    def test_ordered_newest_first(self, authed_client, app):
        from datetime import UTC, datetime, timedelta

        with app.app_context():
            old = ImportLog(source="old", task_count=1)
            old.imported_at = datetime.now(UTC) - timedelta(days=1)
            db.session.add(old)
            new = ImportLog(source="new", task_count=2)
            db.session.add(new)
            db.session.commit()

        resp = authed_client.get("/api/settings/imports")
        body = resp.get_json()
        assert body[0]["source"] == "new"
        assert body[1]["source"] == "old"


# --- Settings page HTML -------------------------------------------------------


class TestSettingsPageView:
    """Verify the /settings page renders with the expected structure."""

    def test_renders_200(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        resp = client.get("/settings")
        assert resp.status_code == 200

    def test_has_stats_section(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/settings").data.decode()
        assert 'id="settingsStats"' in html
        assert 'id="statActiveTasks"' in html

    def test_has_services_section(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/settings").data.decode()
        assert 'id="settingsServices"' in html
        assert 'id="settingsServiceTable"' in html

    def test_has_digest_section(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/settings").data.decode()
        assert 'id="settingsDigest"' in html
        assert 'id="settingsDigestPreview"' in html
        assert 'id="settingsDigestSend"' in html

    def test_has_import_history_section(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/settings").data.decode()
        assert 'id="settingsImports"' in html
        assert 'id="settingsImportTable"' in html

    def test_has_quick_links(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/settings").data.decode()
        assert 'id="settingsLinks"' in html
        assert "/review" in html
        assert "/scan" in html
        assert "/import" in html
        assert "/print" in html

    def test_loads_settings_js(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/settings").data.decode()
        assert "settings.js" in html

    def test_requires_auth(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/settings")
        assert resp.status_code == 302


# --- Blueprint registration --------------------------------------------------


class TestSettingsBlueprint:
    """Verify the settings_api blueprint is registered."""

    def test_blueprint_registered(self, app):
        assert "settings_api" in app.blueprints

    def test_routes_exist(self, app):
        rules = [r.rule for r in app.url_map.iter_rules()]
        assert "/api/settings/status" in rules
        assert "/api/settings/stats" in rules
        assert "/api/settings/imports" in rules
