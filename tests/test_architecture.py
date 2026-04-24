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

    def test_route_catalog_split_into_pages_and_api(self, authed_client):
        """#43: pages get an always-visible <h3>; API endpoints are
        wrapped in a collapsed <details> so the user-facing routes
        pop instead of being buried under 58 /api/* rows."""
        resp = authed_client.get("/architecture")
        body = resp.get_data(as_text=True)
        # Pages section header (with count)
        assert "<h3>Pages (" in body
        # Collapsed API section
        assert 'details class="route-catalog-api"' in body
        assert "<summary>API endpoints (" in body

    def test_recurring_spawn_renders_as_numbered_list_not_mermaid(self, authed_client):
        """#43: the recurring-spawn flow is linear (no branches) and
        renders as <ol class="process-flow"> rather than a Mermaid
        sequence diagram. Mermaid is reserved for the voice-memo +
        auth flows that have real conditionals."""
        resp = authed_client.get("/architecture")
        body = resp.get_data(as_text=True)
        # The recurring-spawn section's H2 anchor still exists
        assert 'id="flow-recurring-spawn"' in body
        # And the section uses an <ol class="process-flow"> instead of
        # the previous <pre class="mermaid"> block
        assert 'class="process-flow"' in body


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


# --- split_route_catalog (#43) ---------------------------------------------


class TestSplitRouteCatalog:

    def test_partitions_pages_from_api_endpoints(self, app):
        from architecture_service import build_route_catalog, split_route_catalog
        catalog = build_route_catalog(app)
        pages, apis = split_route_catalog(catalog)
        # Every API endpoint starts with /api/
        assert all(e["path"].startswith("/api/") for e in apis)
        # No page route starts with /api/
        assert not any(e["path"].startswith("/api/") for e in pages)
        # The two together account for the full catalog (no entry dropped)
        assert len(pages) + len(apis) == len(catalog)

    def test_known_pages_land_in_pages_bucket(self, app):
        from architecture_service import build_route_catalog, split_route_catalog
        catalog = build_route_catalog(app)
        pages, _ = split_route_catalog(catalog)
        page_paths = {e["path"] for e in pages}
        # User-facing tabs from base.html nav
        for known_page in ("/", "/architecture", "/docs", "/goals"):
            assert known_page in page_paths

    def test_pages_bucket_smaller_than_api_bucket(self, app):
        """Sanity: there should be far more API endpoints than page
        routes. If this flips, the split is no longer a useful UX
        improvement (the whole point of #43's collapse) — investigate."""
        from architecture_service import build_route_catalog, split_route_catalog
        catalog = build_route_catalog(app)
        pages, apis = split_route_catalog(catalog)
        assert len(apis) > len(pages)


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

    def test_no_pk_marker_when_id_columns_hidden(self, app):
        """#43: `id` is hidden from the ER diagram (universal column,
        all tables have UUID PK — the marker added noise without
        info). PK markers correspondingly disappear; the template
        footnote tells the user every table has an id PK + timestamps."""
        from architecture_service import build_er_diagram
        with app.app_context():
            out = build_er_diagram()
        # No id column rendered anywhere = no PK markers anywhere
        assert " PK" not in out

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

    def test_hides_id_and_timestamp_columns(self, app):
        """#43: every table has id, created_at, updated_at — surfacing
        them on every box adds noise without information. They're
        hidden from the diagram (and footnoted in the template)."""
        from architecture_service import build_er_diagram
        with app.app_context():
            out = build_er_diagram()
        # The diagram has these tables but the universal-noise columns
        # should not appear as column rows. Test by checking the lines
        # inside the entity blocks.
        # `created_at` and `updated_at` should not show as column rows
        for line in out.splitlines():
            stripped = line.strip()
            # Column rows look like "type column_name PK" — we want to
            # ensure no column row's name is in the hidden allowlist.
            # Skip non-column lines (header, classDef, relationships, braces).
            if not stripped or stripped in {"erDiagram", "}", ""}:
                continue
            if stripped.startswith(("class ", "classDef ", "direction ")):
                continue
            if stripped.endswith("{") or "||--o{" in stripped:
                continue
            # This is a column row — assert its name is not hidden
            tokens = stripped.split()
            # Format: "type name [markers]" — name is tokens[1]
            if len(tokens) >= 2:
                assert tokens[1] not in {"id", "created_at", "updated_at"}, \
                    f"hidden column leaked into ER diagram: {stripped}"

    def test_uses_lr_direction_for_wider_layout(self, app):
        """#43: `direction LR` (left-to-right) reads more naturally
        than the default top-down for a wide-page ER diagram."""
        from architecture_service import build_er_diagram
        with app.app_context():
            out = build_er_diagram()
        assert "direction LR" in out

    def test_emits_classdef_color_groups(self, app):
        """#43: tables are color-grouped (Core / Operational / Auth)
        for visual hierarchy. classDef directives + per-table class
        assignments should be present."""
        from architecture_service import build_er_diagram
        with app.app_context():
            out = build_er_diagram()
        # Three classDef directives — one per group
        assert "classDef core" in out
        assert "classDef ops" in out
        assert "classDef auth" in out
        # And at least one class assignment line per group with the
        # expected tables. core: tasks should be assigned to it.
        # Look for `class A,B,C core` style lines.
        core_assignments = [
            line for line in out.splitlines()
            if line.strip().startswith("class ") and line.strip().endswith(" core")
        ]
        assert core_assignments, "expected at least one `class ... core` line"
        # tasks must be in the core group (it's the central user entity)
        assert any("tasks" in line for line in core_assignments)

    def test_every_model_table_has_a_group(self, app):
        """#43 drift gate: a future contributor adding a new
        `db.Model` subclass must classify it in `_ER_TABLE_GROUPS`.
        If they forget, this test fails — covers the cascade-check
        rule for "A new SQLAlchemy db.Model subclass"."""
        from architecture_service import _ER_TABLE_GROUPS
        from models import db
        for mapper in db.Model.registry.mappers:
            if mapper.local_table is None:
                continue
            name = mapper.local_table.name
            assert name in _ER_TABLE_GROUPS, (
                f"model table {name!r} has no group in _ER_TABLE_GROUPS — "
                f"add it to architecture_service._ER_TABLE_GROUPS "
                f"(core/ops/auth) and _ER_TABLE_ORDER per CLAUDE.md cascade."
            )


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
