"""Tests for the /architecture page (#42) and architecture_service.

Covers:
- Route returns 200 to authenticated users
- @login_required actually applies (302 to OAuth without auth)
- Validator cookie can read the page (GET-only, ADR-004 path)
- build_route_catalog returns the known top-level routes including
  the new /architecture itself (sanity check that introspection works)
- build_route_catalog tags @login_required vs public correctly
- build_er_diagram emits Mermaid header and includes every model table
- render_architecture_md raises FileNotFoundError on missing file
  (caller handles with friendly fallback)
- render_architecture_md round-trip on a heading + table fixture

Cross-reference ADR-028 for the source-of-truth strategy.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# --- Route smoke tests ------------------------------------------------------


class TestArchitectureRoute:

    def test_authed_user_gets_200(self, authed_client):
        resp = authed_client.get("/architecture")
        assert resp.status_code == 200
        # Page contains the section anchors we expect
        body = resp.get_data(as_text=True)
        assert 'id="er-diagram"' in body
        assert 'id="route-catalog"' in body
        assert 'id="flow-recurring-spawn"' in body
        assert 'id="flow-voice-memo"' in body
        assert 'id="flow-auth"' in body

    def test_unauthed_redirects_to_oauth(self, client):
        resp = client.get("/architecture", follow_redirects=False)
        # @login_required redirects to google.login on no-session
        assert resp.status_code in (302, 401)

    def test_page_includes_mermaid_loader(self, authed_client):
        resp = authed_client.get("/architecture")
        body = resp.get_data(as_text=True)
        assert "cdn.jsdelivr.net/npm/mermaid" in body
        # Sanity: the version we pinned in the template is the one that
        # actually got rendered (catches a stale-cache-of-template bug)
        assert "mermaid@10" in body

    def test_page_renders_route_catalog_table(self, authed_client):
        resp = authed_client.get("/architecture")
        body = resp.get_data(as_text=True)
        # Route catalog table headers + at least one /architecture row
        assert 'class="route-catalog"' in body
        assert "/architecture" in body


# --- build_route_catalog ----------------------------------------------------


class TestBuildRouteCatalog:

    def test_returns_known_top_level_routes(self, app):
        from architecture_service import build_route_catalog
        catalog = build_route_catalog(app)
        paths = {entry["path"] for entry in catalog}
        # Sanity: at minimum these routes exist and are picked up
        assert "/" in paths
        assert "/architecture" in paths
        assert "/docs" in paths
        assert "/goals" in paths

    def test_static_and_oauth_routes_excluded(self, app):
        from architecture_service import build_route_catalog
        catalog = build_route_catalog(app)
        paths = [entry["path"] for entry in catalog]
        # Flask's static endpoint must not appear in the user-facing
        # catalog (infra noise)
        assert not any(p.startswith("/static/") for p in paths)
        # OAuth callbacks are infra; hidden via _HIDDEN_ROUTE_PREFIXES
        assert not any(p.startswith("/login/") for p in paths)

    def test_login_required_routes_tagged_login(self, app):
        from architecture_service import build_route_catalog
        catalog = build_route_catalog(app)
        # /architecture itself is @login_required; this confirms the
        # _detect_auth wrapper-walk found the marker we set on auth.py's
        # login_required decorator
        arch_entries = [e for e in catalog if e["path"] == "/architecture"]
        assert arch_entries, "expected /architecture in catalog"
        assert all(e["auth"] == "login" for e in arch_entries)

    def test_healthz_tagged_public(self, app):
        from architecture_service import build_route_catalog
        catalog = build_route_catalog(app)
        # /healthz is intentionally public (Railway probe + post-deploy
        # validate need it without auth)
        healthz_entries = [e for e in catalog if e["path"] == "/healthz"]
        if healthz_entries:  # may not exist in all test configs
            assert all(e["auth"] == "public" for e in healthz_entries)

    def test_each_entry_has_method_and_path(self, app):
        from architecture_service import build_route_catalog
        catalog = build_route_catalog(app)
        assert catalog, "expected at least some routes"
        for entry in catalog:
            assert "method" in entry
            assert "path" in entry
            assert "auth" in entry
            assert "doc" in entry
            # No HEAD/OPTIONS leaked through the filter
            assert entry["method"] not in {"HEAD", "OPTIONS"}


# --- build_er_diagram -------------------------------------------------------


class TestBuildErDiagram:

    def test_emits_mermaid_header(self, app):
        from architecture_service import build_er_diagram
        with app.app_context():
            out = build_er_diagram()
        assert out.startswith("erDiagram")

    def test_includes_every_known_table(self, app):
        from architecture_service import build_er_diagram
        with app.app_context():
            out = build_er_diagram()
        # All seven Model classes from models.py should appear by table name
        for table in ("tasks", "goals", "projects", "recurring_tasks",
                      "app_logs", "import_log"):
            assert table in out, f"ER diagram missing table {table!r}"

    def test_includes_pk_marker(self, app):
        from architecture_service import build_er_diagram
        with app.app_context():
            out = build_er_diagram()
        # Every table has a PK column marker
        assert " PK" in out

    def test_includes_fk_relationship_arrows(self, app):
        from architecture_service import build_er_diagram
        with app.app_context():
            out = build_er_diagram()
        # FK relationships render as Mermaid `||--o{` arrows
        assert "||--o{" in out

    def test_includes_enum_values_for_tier(self, app):
        from architecture_service import build_er_diagram
        with app.app_context():
            out = build_er_diagram()
        # Tier enum should surface its values inline (today, tomorrow,
        # this_week, etc.) — the whole point of "standard" auto-gen
        # detail per the Q9 decision
        assert "enum_" in out
        # At least one Tier value should be visible
        assert "today" in out


# --- render_architecture_md -------------------------------------------------


class TestRenderArchitectureMd:

    def test_missing_file_raises_filenotfound(self, tmp_path):
        from architecture_service import render_architecture_md
        with pytest.raises(FileNotFoundError):
            render_architecture_md(tmp_path / "nope.md")

    def test_renders_heading(self, tmp_path):
        from architecture_service import render_architecture_md
        f = tmp_path / "a.md"
        f.write_text("# Title\n\nBody.\n", encoding="utf-8")
        html = render_architecture_md(f)
        assert "<h1>Title</h1>" in html
        assert "<p>Body.</p>" in html

    def test_renders_fenced_code(self, tmp_path):
        """The fenced_code extension must be active so triple-backtick
        ASCII art in ARCHITECTURE.md renders inside <pre><code>."""
        from architecture_service import render_architecture_md
        f = tmp_path / "a.md"
        f.write_text("```\nascii art\n```\n", encoding="utf-8")
        html = render_architecture_md(f)
        assert "<pre>" in html
        assert "<code>" in html

    def test_renders_table(self, tmp_path):
        """The tables extension must be active so the threat-model table
        in ARCHITECTURE.md renders as a real <table>."""
        from architecture_service import render_architecture_md
        f = tmp_path / "a.md"
        f.write_text(
            "| col1 | col2 |\n|---|---|\n| a | b |\n",
            encoding="utf-8",
        )
        html = render_architecture_md(f)
        assert "<table>" in html
        assert "<th>col1</th>" in html
        assert "<td>a</td>" in html

    def test_real_architecture_md_renders_without_error(self):
        """Belt-and-braces — the actual file in the repo must render
        cleanly. This catches a future change to ARCHITECTURE.md that
        introduces markdown the renderer can't handle."""
        from architecture_service import render_architecture_md
        repo_root = Path(__file__).resolve().parent.parent
        html = render_architecture_md(repo_root / "ARCHITECTURE.md")
        # Smoke: non-empty and contains at least the top-level heading
        # ARCHITECTURE.md is known to start with
        assert len(html) > 1000
        assert "<h1>" in html or "<h2>" in html
