"""Integration tests for mobile-responsive CSS (Step 11).

These tests verify that the HTML templates contain the elements and
attributes needed for mobile responsiveness:

- **Viewport meta tag** — tells mobile browsers to use the device's
  actual screen width instead of pretending to be a desktop monitor.
  Without this, the phone renders a tiny zoomed-out version of the page.
- **Touch-target elements** — buttons and interactive elements that
  exist in the DOM so the CSS can size them to ≥44px for fingers.
- **Swipe actions** — the swipe.js script tag is loaded, enabling
  swipe-to-reveal gestures on task cards.
- **CSS classes** — verifying the stylesheet contains the mobile-specific
  rules (like @media queries and .swiped class).
"""
from __future__ import annotations

import auth

# --- Viewport meta tag --------------------------------------------------------


class TestViewportMeta:
    """The viewport meta tag is critical for mobile rendering.

    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    This tells the browser: "Don't pretend to be 1024px wide — use the
    actual device width." Without it, all CSS media queries are ignored
    because the browser thinks it's on a desktop.
    """

    def test_index_has_viewport_meta(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'name="viewport"' in html
        assert "width=device-width" in html

    def test_goals_has_viewport_meta(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/goals").data.decode()
        assert 'name="viewport"' in html
        assert "width=device-width" in html

    def test_login_has_viewport_meta(self, client):
        html = client.get("/login").data.decode()
        assert 'name="viewport"' in html


# --- Touch target elements exist ----------------------------------------------


class TestTouchTargetElements:
    """Verify that elements the mobile CSS targets actually exist in the HTML.

    'Touch targets' are the things a user taps with their finger. Apple's
    Human Interface Guidelines say they should be at least 44×44 points.
    Our CSS applies min-height/min-width: 44px to these elements — but
    the CSS only works if the elements exist in the template.
    """

    def test_collapse_toggles_present(self, client, monkeypatch):
        """Each tier section has a collapse toggle button."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert "collapse-toggle" in html

    def test_voice_button_present(self, client, monkeypatch):
        """The voice input button (microphone icon) is in the capture bar."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'id="captureVoice"' in html

    def test_bulk_triage_button_present(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'id="bulkTriageBtn"' in html

    def test_detail_panel_form_inputs(self, client, monkeypatch):
        """Detail panel has form inputs that need iOS zoom prevention (16px font)."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'id="detailTitle"' in html
        assert 'id="detailNotes"' in html
        assert 'id="detailDueDate"' in html

    def test_checklist_add_button(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'id="addChecklistItem"' in html

    def test_project_filter_bar_present(self, client, monkeypatch):
        """The project filter bar that scrolls horizontally on mobile."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'id="projectFilterBar"' in html


# --- Swipe gesture script loaded ----------------------------------------------


class TestSwipeScript:
    """Verify swipe.js is included in the page.

    swipe.js adds touch event handlers (touchstart, touchmove, touchend)
    to task cards so users can swipe left to reveal action buttons.
    This only works on touch devices — on desktop it's a no-op.
    """

    def test_swipe_js_loaded_on_index(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert "swipe.js" in html

    def test_swipe_js_is_after_app_js(self, client, monkeypatch):
        """swipe.js depends on app.js (uses taskDelete), so it must load after."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        app_pos = html.index("app.js")
        swipe_pos = html.index("swipe.js")
        assert swipe_pos > app_pos


# --- CSS contains mobile rules ------------------------------------------------


class TestMobileCSSRules:
    """Verify the stylesheet has the mobile-specific CSS rules.

    We read the CSS file directly (not via HTTP) to check that the
    @media query and key mobile classes are present.

    An '@media (max-width: 600px)' block means: "only apply these styles
    when the screen is 600 pixels wide or narrower" — i.e., phones.
    """

    def test_css_has_mobile_media_query(self):
        with open("static/style.css", encoding="utf-8") as f:
            css = f.read()
        assert "@media" in css
        assert "max-width" in css

    def test_css_has_swiped_class(self):
        """The .swiped class applies translateX to slide the card left."""
        with open("static/style.css", encoding="utf-8") as f:
            css = f.read()
        assert ".task-card.swiped" in css
        assert "translateX" in css

    def test_css_has_swipe_actions(self):
        with open("static/style.css", encoding="utf-8") as f:
            css = f.read()
        assert ".swipe-actions" in css
        assert ".swipe-action-move" in css
        assert ".swipe-action-delete" in css

    def test_css_has_44px_touch_targets(self):
        """44px is the minimum recommended touch target size."""
        with open("static/style.css", encoding="utf-8") as f:
            css = f.read()
        assert "min-height: 44px" in css

    def test_css_has_ios_zoom_prevention(self):
        """font-size: 16px on form inputs prevents iOS Safari from
        auto-zooming when the user taps a text field."""
        with open("static/style.css", encoding="utf-8") as f:
            css = f.read()
        assert "font-size: 16px" in css

    def test_css_has_full_width_detail_panel(self):
        with open("static/style.css", encoding="utf-8") as f:
            css = f.read()
        assert "width: 100vw" in css


# --- Goals page mobile elements -----------------------------------------------


class TestGoalsMobileElements:
    """The goals page also needs mobile-friendly structure."""

    def test_goals_toolbar_exists(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/goals").data.decode()
        assert "goals-toolbar" in html or "goals-filters" in html

    def test_goals_filter_dropdowns(self, client, monkeypatch):
        """Filter dropdowns need min-height: 44px on mobile (applied via CSS)."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/goals").data.decode()
        assert 'id="filterCategory"' in html
        assert 'id="filterStatus"' in html
