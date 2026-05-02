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
        for tier in ["inbox", "today", "tomorrow", "this_week", "next_week", "backlog", "freezer"]:
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

    def test_contains_parent_link_section(self, client, monkeypatch):
        """Backlog #30: detail panel has a parent-link section that
        app.js toggles on for subtasks."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'id="parentLinkSection"' in html
        assert 'id="parentLinkBody"' in html
        # Starts hidden; app.js shows it when task.parent_id is set.
        assert 'parentLinkSection' in html and 'style="display:none"' in html

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


class TestProjectsPage:
    """Integration tests for the projects CRUD view at /projects (backlog #24)."""

    def test_renders_200(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        resp = client.get("/projects")
        assert resp.status_code == 200

    def test_contains_filter_dropdowns(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/projects").data.decode()
        assert 'id="projectFilterType"' in html
        assert 'id="projectFilterActive"' in html

    def test_contains_add_button(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/projects").data.decode()
        assert 'id="addProjectBtn"' in html

    def test_contains_detail_panel(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/projects").data.decode()
        assert 'id="projectDetailOverlay"' in html
        assert 'id="projectDetailForm"' in html
        assert 'id="projectName"' in html
        assert 'id="projectType"' in html
        assert 'id="projectColor"' in html
        assert 'id="projectGoalId"' in html
        assert 'id="projectArchiveToggle"' in html
        # Delete button intentionally absent — DELETE endpoint is a soft
        # delete (same as archive), so we expose only Archive/Unarchive.
        assert 'id="projectDelete"' not in html

    def test_contains_board(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/projects").data.decode()
        assert 'id="projectsBoard"' in html

    def test_loads_scripts(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/projects").data.decode()
        assert "app.js" in html
        assert "projects.js" in html
        assert "capture.js" in html

    def test_nav_includes_projects_link(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        # Projects link must appear on every authenticated page, not just /projects.
        for path in ("/", "/goals", "/projects"):
            html = client.get(path).data.decode()
            assert "/projects" in html, f"/projects nav link missing from {path}"

    def test_requires_auth(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/projects")
        assert resp.status_code == 302

    def test_rejects_wrong_email(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "bad@example.com")
        resp = client.get("/projects")
        assert resp.status_code == 403


class TestDocsPage:
    """Integration tests for the in-app /docs page (backlog #33)."""

    def test_renders_200(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_requires_auth(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/docs")
        assert resp.status_code == 302

    def test_rejects_wrong_email(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "bad@example.com")
        resp = client.get("/docs")
        assert resp.status_code == 403

    def test_contains_toc_and_import_section(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/docs").data.decode()
        # TOC present with the two first sections
        assert 'class="docs-toc"' in html
        assert '#import-onenote' in html
        assert '#import-excel-goals' in html
        # The OneNote section itself
        assert 'id="import-onenote"' in html
        # Key rules mentioned verbatim so a doc-update regression is catchable
        assert "One non-empty line = one task" in html
        assert "Indentation is NOT significant" in html

    def test_nav_includes_docs_link(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        # Docs link should appear on every authenticated page, not just /docs
        for path in ("/", "/goals", "/projects", "/docs"):
            html = client.get(path).data.decode()
            assert "/docs" in html, f"/docs nav link missing from {path}"

    def test_import_page_links_to_docs(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/import").data.decode()
        # "Format guide" link with anchor into the docs page
        assert '/docs#import-onenote' in html

    def test_import_page_has_transcript_modes(self, client, monkeypatch):
        """The HyNote / Notion AI Meeting Notes transcript ingestion adds
        two mode buttons + two input sections. Asserting the IDs are
        present catches a template revert that drops the feature wiring.
        """
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/import").data.decode()
        assert 'id="importTranscriptBtn"' in html
        assert 'id="importTranscriptUploadBtn"' in html
        assert 'id="importTranscriptInput"' in html
        assert 'id="importTranscriptUploadInput"' in html
        assert 'id="importTranscriptText"' in html
        assert 'id="importTranscriptFile"' in html

    def test_docs_page_has_capture_bar(self, client, monkeypatch):
        """Regression for 2026-04-21 bug: capture bar was initially
        omitted on /docs ("this is reading material" reasoning),
        but the user correctly called it out as an unexpected gap.
        Every other subpage has it; /docs should too. Anything typed
        lands in Inbox (server default, no data-default-tier)."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/docs").data.decode()
        assert 'id="captureBar"' in html
        assert 'id="captureInput"' in html
        assert 'id="captureType"' in html
        assert 'id="captureSubmit"' in html
        # Scripts loaded so the bar actually works
        assert 'capture.js' in html
        assert 'parse_capture.js' in html
        assert 'app.js' in html


class TestCompletedPage:
    """Integration tests for the dedicated /completed page (backlog #29)."""

    def test_renders_200(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        resp = client.get("/completed")
        assert resp.status_code == 200

    def test_requires_auth(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/completed")
        assert resp.status_code == 302

    def test_rejects_wrong_email(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "bad@example.com")
        resp = client.get("/completed")
        assert resp.status_code == 403

    def test_has_heading_and_completed_label(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/completed").data.decode()
        assert "Completed" in html
        # Marker for the JS init branch
        assert 'data-archived-list="true"' in html
        # Back link to board + bulk toolbar present
        assert 'tier-back-link' in html
        assert 'id="bulkToolbar"' in html

    def test_loads_scripts(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/completed").data.decode()
        assert "app.js" in html
        assert "capture.js" in html

    def test_capture_bar_has_no_default_tier(self, client, monkeypatch):
        """Tasks typed in the capture bar on /completed should land in
        Inbox (the server's default), NOT in archived state. Absence of
        ``data-default-tier`` on the capture bar enforces this."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/completed").data.decode()
        # The capture bar div must exist but without data-default-tier
        assert 'id="captureBar"' in html
        assert 'data-default-tier' not in html

    def test_board_completed_heading_links_to_dedicated_page(
        self, client, monkeypatch,
    ):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        # The board's Completed heading should now link to /completed
        assert 'href="/completed"' in html


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
