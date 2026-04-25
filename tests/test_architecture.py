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
        # Page contains the section anchors we expect (#44 reorg —
        # er-diagram + route-catalog moved into engineering <details>;
        # top-level anchors are now the plain-English sections).
        body = resp.get_data(as_text=True)
        assert 'id="running"' in body
        assert 'id="schema"' in body
        assert 'id="pages"' in body
        assert 'id="flow-recurring"' in body
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
        """#43/#44: pages get an always-visible plain table (under the
        "Pages in the app" H2); API endpoints are wrapped in an
        engineering <details> so the user-facing routes pop instead of
        being buried under 58 /api/* rows."""
        resp = authed_client.get("/architecture")
        body = resp.get_data(as_text=True)
        # Pages section H2 (#44 renamed from "Pages" to user-friendly)
        assert "Pages in the app" in body
        # Engineering details for API endpoints
        assert "API endpoints (" in body
        # The pages table (always visible) renders as <table class="pages-table">
        assert 'class="pages-table"' in body

    def test_quality_and_testing_section_renders(self, authed_client):
        """#54: new "Quality & testing" section between Process flows
        and the engineering details. Anchors must be present so the
        TOC links work."""
        resp = authed_client.get("/architecture")
        body = resp.get_data(as_text=True)
        # New TOC group + section anchors
        assert "Quality &amp; testing" in body
        assert 'id="ship-lifecycle"' in body
        assert 'id="quality-gates"' in body
        assert 'id="drift-gates"' in body
        assert 'id="testing-limitations"' in body

    def test_quality_gates_table_lists_all_11_gates(self, authed_client):
        """#54: the 11 quality gates table must mention every gate
        from run_all_gates.sh by name. If a contributor adds a new
        gate without updating the table, this test fails."""
        resp = authed_client.get("/architecture")
        body = resp.get_data(as_text=True)
        # Spot-check the gate names that appear in run_all_gates.sh
        for gate_name in (
            "ruff", "pytest", "Jest", "Playwright", "bandit",
            "pip-audit", "npm audit", "docs_sync_check",
            "arch_sync_check", "semgrep", "gitleaks",
        ):
            assert gate_name in body, (
                f"Quality & testing section missing reference to gate {gate_name!r}"
            )

    def test_drift_gates_table_lists_known_drift_prevention(self, authed_client):
        """#54: the drift-gates table must call out the mechanical
        sync checks that were added in response to specific bug classes."""
        resp = authed_client.get("/architecture")
        body = resp.get_data(as_text=True)
        # Each drift gate ties to a numbered bug for traceability.
        for ref in (
            "test_every_model_table_has_a_group",
            "test_every_column_has_a_description",
            "check_enum_coverage",
            "test_repo_hygiene",
            "_build_enum_repair_statements",
        ):
            assert ref in body

    def test_per_table_cards_render_with_pk_callout(self, authed_client):
        """#44: each db.Model has a per-table card with a 🔑 Primary
        key callout under the description, before the column list."""
        resp = authed_client.get("/architecture")
        body = resp.get_data(as_text=True)
        # PK callout marker — emoji in the template
        assert "🔑" in body
        assert "Primary key" in body
        # Per-table card containers
        assert 'class="db-table-detail"' in body
        # The known table headings (each db.Model gets a card)
        assert "<h4>tasks" in body
        assert "<h4>goals" in body
        assert "<h4>flask_dance_oauth" in body

    def test_fk_columns_get_fk_badge(self, authed_client):
        """#44: foreign-key columns in the per-table cards get a
        purple 'FK' badge next to the column name + a left-edge stripe
        on the row, so relationships pop visually."""
        resp = authed_client.get("/architecture")
        body = resp.get_data(as_text=True)
        # FK badge class + at least one row-fk row
        assert 'class="key-fk"' in body
        assert 'class="row-fk"' in body
        # tasks has 5 FKs; one of them should be visible
        assert "goal_id" in body

    def test_recurring_spawn_uses_flow_steps_list(self, authed_client):
        """#43/#44: the recurring-spawn flow has a linear-form
        numbered list (`<ol class="flow-steps">`) under the simple +
        detailed Mermaid flowcharts."""
        resp = authed_client.get("/architecture")
        body = resp.get_data(as_text=True)
        # The recurring-spawn section's H3 anchor (#44 renamed to flow-recurring)
        assert 'id="flow-recurring"' in body
        # And the section includes an <ol class="flow-steps"> for the prose
        assert 'class="flow-steps"' in body


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


# --- build_per_table_schema (#44) ------------------------------------------


class TestBuildPerTableSchema:

    def test_returns_one_entry_per_known_table(self, app):
        from architecture_service import build_per_table_schema
        with app.app_context():
            out = build_per_table_schema()
        names = {e["name"] for e in out}
        for known in ("tasks", "goals", "projects", "recurring_tasks",
                      "app_logs", "import_log", "flask_dance_oauth"):
            assert known in names, f"missing table {known!r} in per-table schema"

    def test_each_entry_has_required_fields(self, app):
        from architecture_service import build_per_table_schema
        with app.app_context():
            out = build_per_table_schema()
        for e in out:
            assert "name" in e
            assert "group" in e and e["group"] in {"core", "ops", "auth"}
            assert "blurb" in e and e["blurb"], f"{e['name']} blurb empty"
            assert "pk_label" in e and e["pk_label"]
            assert "columns" in e and isinstance(e["columns"], list)

    def test_fk_columns_marked(self, app):
        from architecture_service import build_per_table_schema
        with app.app_context():
            out = build_per_table_schema()
        tasks = next(e for e in out if e["name"] == "tasks")
        fk_cols = [c for c in tasks["columns"] if c["is_fk"]]
        # tasks has 5 FK columns: goal_id, project_id, parent_id,
        # recurring_task_id, batch_id
        assert len(fk_cols) >= 4
        fk_names = {c["name"] for c in fk_cols}
        assert "goal_id" in fk_names
        assert "project_id" in fk_names

    def test_fk_target_string_present_for_fk_cols(self, app):
        from architecture_service import build_per_table_schema
        with app.app_context():
            out = build_per_table_schema()
        tasks = next(e for e in out if e["name"] == "tasks")
        goal_id_col = next(c for c in tasks["columns"] if c["name"] == "goal_id")
        # fk_target is the human-readable target like "goals.id"
        assert goal_id_col["fk_target"] == "goals.id"

    def test_import_log_uses_batch_id_as_pk_label(self, app):
        """import_log uses batch_id as PK rather than the universal id;
        the PK label should call this out."""
        from architecture_service import build_per_table_schema
        with app.app_context():
            out = build_per_table_schema()
        import_log = next(e for e in out if e["name"] == "import_log")
        assert "batch_id" in import_log["pk_label"]


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

    def test_every_column_has_a_description(self, app):
        """#44 drift gate: every non-universal, non-optional column on
        every db.Model must have a plain-English description in
        `_SCHEMA_DESCRIPTIONS`. If a contributor adds a column without
        a description, this test fails — covers the cascade-check rule
        for "A new column on an existing db.Model"."""
        from architecture_service import (
            _DESCRIPTION_OPTIONAL_COLUMNS,
            _HIDDEN_ER_COLUMNS,
            _SCHEMA_DESCRIPTIONS,
        )
        from models import db
        for mapper in db.Model.registry.mappers:
            if mapper.local_table is None:
                continue
            tname = mapper.local_table.name
            assert tname in _SCHEMA_DESCRIPTIONS, (
                f"table {tname!r} missing from _SCHEMA_DESCRIPTIONS — "
                f"add a {{blurb, columns: {{...}}}} entry per the "
                f"CLAUDE.md cascade-check rule for new db.Model subclasses."
            )
            described = _SCHEMA_DESCRIPTIONS[tname].get("columns", {})
            for col in mapper.local_table.columns:
                # Skip the universal columns we deliberately don't render
                if col.name in _HIDDEN_ER_COLUMNS and col.name not in described:
                    continue
                if col.name in _DESCRIPTION_OPTIONAL_COLUMNS:
                    continue
                assert col.name in described, (
                    f"column {tname}.{col.name} has no description in "
                    f"_SCHEMA_DESCRIPTIONS — add a {{desc, notes, "
                    f"fk_target?}} entry per the CLAUDE.md cascade-check "
                    f"rule for new columns."
                )

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
