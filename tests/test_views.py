"""Integration tests for HTML views — verify structure, elements, scripts.

These tests check that templates render correctly with the expected
DOM elements that the JavaScript relies on.
"""
from __future__ import annotations

import auth

# --- Index page (tier board) --------------------------------------------------


class TestIndexPage:
    """Integration tests for the main tier board view at /."""

    def test_renders_200(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        resp = client.get("/")
        assert resp.status_code == 200

    def test_contains_tier_sections(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        for tier in ["inbox", "today", "this_week", "backlog", "freezer"]:
            assert f'data-tier="{tier}"' in html

    def test_inbox_is_first_tier_section(self, client, monkeypatch):
        """Spec says inbox appears at top of screen as the default landing view."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        inbox_pos = html.index('data-tier="inbox"')
        today_pos = html.index('data-tier="today"')
        assert inbox_pos < today_pos

    def test_inbox_has_triage_checkboxes_container(self, client, monkeypatch):
        """Spec: bulk triage with select multiple + assign tier."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        # The triage button is inside the inbox tier section
        assert 'id="bulkTriageBtn"' in html

    def test_inbox_has_tier_count_display(self, client, monkeypatch):
        """Spec: inbox count badge shows how many items need triage."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'class="tier-count"' in html

    def test_contains_capture_bar(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'id="captureInput"' in html
        assert 'id="captureType"' in html
        assert 'id="captureVoice"' in html

    def test_contains_detail_panel(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'id="detailOverlay"' in html
        assert 'id="detailForm"' in html
        assert 'id="detailTitle"' in html
        assert 'id="detailTier"' in html
        assert 'id="detailType"' in html
        assert 'id="detailProject"' in html
        assert 'id="detailGoal"' in html
        assert 'id="detailDueDate"' in html
        assert 'id="detailNotes"' in html
        assert 'id="checklistItems"' in html

    def test_contains_project_filter_bar(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'id="projectFilterBar"' in html

    def test_contains_nav_tabs(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'data-view="all"' in html
        assert 'data-view="work"' in html
        assert 'data-view="personal"' in html

    def test_contains_goals_link(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert "/goals" in html

    def test_contains_inbox_badge(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'id="inboxBadge"' in html

    def test_contains_bulk_triage_btn(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'id="bulkTriageBtn"' in html

    def test_loads_scripts(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert "app.js" in html
        assert "capture.js" in html

    def test_contains_logout(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert "/logout" in html

    def test_contains_today_warning(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'id="todayWarning"' in html

    def test_collapse_toggles_present(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert "collapse-toggle" in html


# --- Goals page ---------------------------------------------------------------


class TestGoalsPage:
    """Integration tests for the goals view at /goals."""

    def test_renders_200(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        resp = client.get("/goals")
        assert resp.status_code == 200

    def test_contains_filter_dropdowns(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/goals").data.decode()
        assert 'id="filterCategory"' in html
        assert 'id="filterPriority"' in html
        assert 'id="filterStatus"' in html
        assert 'id="filterQuarter"' in html

    def test_contains_add_goal_button(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/goals").data.decode()
        assert 'id="addGoalBtn"' in html

    def test_contains_goal_detail_panel(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/goals").data.decode()
        assert 'id="goalDetailOverlay"' in html
        assert 'id="goalDetailForm"' in html
        assert 'id="goalTitle"' in html
        assert 'id="goalCategory"' in html
        assert 'id="goalPriority"' in html
        assert 'id="goalPriorityRank"' in html
        assert 'id="goalTargetQuarter"' in html
        assert 'id="goalStatus"' in html
        assert 'id="goalActions"' in html
        assert 'id="goalNotes"' in html

    def test_contains_linked_tasks_section(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/goals").data.decode()
        assert 'id="linkedTasksSection"' in html
        assert 'id="linkedTasksList"' in html
        assert 'id="linkedTaskInput"' in html
        assert 'id="addLinkedTaskBtn"' in html

    def test_contains_goals_board(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/goals").data.decode()
        assert 'id="goalsBoard"' in html

    def test_loads_scripts(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/goals").data.decode()
        assert "app.js" in html
        assert "goals.js" in html
        assert "capture.js" in html

    def test_contains_capture_bar(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/goals").data.decode()
        assert 'id="captureInput"' in html

    def test_contains_inbox_badge(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/goals").data.decode()
        assert 'id="inboxBadge"' in html

    def test_contains_logout(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/goals").data.decode()
        assert "/logout" in html

    def test_requires_auth(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/goals")
        assert resp.status_code == 302

    def test_rejects_wrong_email(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "bad@example.com")
        resp = client.get("/goals")
        assert resp.status_code == 403


# --- Login page ---------------------------------------------------------------


class TestLoginPage:
    """Integration tests for the login page."""

    def test_renders_200(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_contains_google_login_link(self, client):
        html = client.get("/login").data.decode()
        assert "/login/google" in html

    def test_contains_sign_in_text(self, client):
        html = client.get("/login").data.decode()
        assert "Sign in with Google" in html


# --- Unauthorized page --------------------------------------------------------


class TestUnauthorizedPage:
    """Integration tests for the unauthorized page."""

    def test_renders_403(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "bad@example.com")
        resp = client.get("/")
        assert resp.status_code == 403

    def test_contains_not_authorized_message(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "bad@example.com")
        html = client.get("/").data.decode()
        assert "Not authorized" in html

    def test_contains_back_to_login_link(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "bad@example.com")
        html = client.get("/").data.decode()
        assert "/login" in html
