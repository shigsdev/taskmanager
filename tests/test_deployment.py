"""Deployment readiness tests (Step 20).

Verify that all deployment infrastructure is in place and the app
can boot correctly for Railway hosting.

Key testing concepts:
- **Procfile** — tells Railway/Heroku which processes to run.
  The 'web' process starts gunicorn; the 'release' process
  runs database migrations before each deploy.
- **Gunicorn** — a production WSGI server that serves the Flask app.
  Unlike Flask's dev server, gunicorn handles multiple concurrent
  requests via worker processes.
- **Nixpacks** — Railway's build system that auto-detects the project
  type and builds it. runtime.txt tells it which Python version to use.
- **Health check** — a simple endpoint that Railway pings to verify
  the app is running. Returns 200 with {"status": "ok"}.
"""
from __future__ import annotations

from pathlib import Path

import auth

PROJECT_ROOT = Path(__file__).parent.parent


# --- Deployment files --------------------------------------------------------


class TestDeploymentFiles:
    """Verify required deployment files exist and are correct."""

    def test_procfile_exists(self):
        procfile = PROJECT_ROOT / "Procfile"
        assert procfile.exists(), "Procfile is required for Railway deployment"

    def test_procfile_has_web_process(self):
        content = (PROJECT_ROOT / "Procfile").read_text()
        assert "web:" in content
        assert "gunicorn" in content

    def test_procfile_has_release_phase(self):
        content = (PROJECT_ROOT / "Procfile").read_text()
        assert "release:" in content
        assert "flask db upgrade" in content

    def test_railway_toml_exists(self):
        toml = PROJECT_ROOT / "railway.toml"
        assert toml.exists(), "railway.toml configures Railway deployment"

    def test_railway_toml_uses_nixpacks(self):
        content = (PROJECT_ROOT / "railway.toml").read_text()
        assert "nixpacks" in content

    def test_railway_toml_has_start_command(self):
        content = (PROJECT_ROOT / "railway.toml").read_text()
        assert "gunicorn" in content

    def test_runtime_txt_exists(self):
        runtime = PROJECT_ROOT / "runtime.txt"
        assert runtime.exists(), "runtime.txt pins the Python version"

    def test_runtime_txt_has_python_version(self):
        content = (PROJECT_ROOT / "runtime.txt").read_text().strip()
        assert content.startswith("python-")

    def test_gunicorn_config_exists(self):
        config = PROJECT_ROOT / "gunicorn.conf.py"
        assert config.exists(), "gunicorn.conf.py sets production defaults"

    def test_gunicorn_config_binds_to_port(self):
        content = (PROJECT_ROOT / "gunicorn.conf.py").read_text()
        assert "PORT" in content
        assert "bind" in content

    def test_requirements_has_gunicorn(self):
        content = (PROJECT_ROOT / "requirements.txt").read_text()
        assert "gunicorn" in content

    def test_requirements_has_psycopg(self):
        content = (PROJECT_ROOT / "requirements.txt").read_text()
        assert "psycopg" in content

    def test_env_example_exists(self):
        env = PROJECT_ROOT / ".env.example"
        assert env.exists()

    def test_env_example_has_required_vars(self):
        content = (PROJECT_ROOT / ".env.example").read_text()
        required = [
            "SECRET_KEY",
            "ENCRYPTION_KEY",
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "AUTHORIZED_EMAIL",
            "DATABASE_URL",
            "SENDGRID_API_KEY",
            "DIGEST_TO_EMAIL",
            "GOOGLE_VISION_API_KEY",
            "ANTHROPIC_API_KEY",
        ]
        for var in required:
            assert var in content, f"{var} missing from .env.example"

    def test_gitignore_excludes_env(self):
        gitignore = PROJECT_ROOT / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert ".env" in content


# --- App boot and health check -----------------------------------------------


class TestAppBoot:
    """Verify the app boots and responds to health checks."""

    def test_app_creates_successfully(self, app):
        assert app is not None

    def test_healthz_returns_ok(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "ok"}

    def test_healthz_no_auth_required(self, client, monkeypatch):
        """Health check must work without authentication."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/healthz")
        assert resp.status_code == 200

    def test_login_page_renders(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_app_has_secret_key(self, app):
        assert app.config["SECRET_KEY"]
        assert app.config["SECRET_KEY"] != ""


# --- Database readiness -------------------------------------------------------


class TestDatabaseReadiness:
    """Verify all models can be created and queried."""

    def test_tables_created(self, app):
        from sqlalchemy import inspect

        with app.app_context():
            from models import db

            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            expected = [
                "tasks", "goals", "projects",
                "recurring_tasks", "import_log",
            ]
            for table in expected:
                assert table in tables, f"Table '{table}' not found"


# --- Blueprint registration --------------------------------------------------


class TestAllBlueprintsRegistered:
    """Verify every API blueprint is registered."""

    def test_all_blueprints(self, app):
        expected = [
            "tasks_api",
            "goals_api",
            "projects_api",
            "review_api",
            "recurring_api",
            "digest_api",
            "scan_api",
            "import_api",
            "settings_api",
        ]
        for bp_name in expected:
            assert bp_name in app.blueprints, f"Blueprint '{bp_name}' not registered"


# --- URL rules ---------------------------------------------------------------


class TestAllRoutesExist:
    """Verify all page and API routes are registered."""

    def test_page_routes(self, app):
        rules = [r.rule for r in app.url_map.iter_rules()]
        pages = [
            "/", "/goals", "/review", "/scan",
            "/import", "/settings", "/print",
            "/login", "/logout", "/healthz",
        ]
        for page in pages:
            assert page in rules, f"Route '{page}' not registered"

    def test_api_routes(self, app):
        rules = [r.rule for r in app.url_map.iter_rules()]
        apis = [
            "/api/tasks",
            "/api/goals",
            "/api/projects",
            "/api/review",
            "/api/recurring",
            "/api/digest/preview",
            "/api/digest/send",
            "/api/scan/upload",
            "/api/scan/confirm",
            "/api/import/tasks/parse",
            "/api/import/tasks/confirm",
            "/api/import/goals/parse",
            "/api/import/goals/confirm",
            "/api/settings/status",
            "/api/settings/stats",
            "/api/settings/imports",
        ]
        for api in apis:
            assert api in rules, f"API route '{api}' not registered"


# --- WSGI entry point ---------------------------------------------------------


class TestWsgiEntryPoint:
    """Verify the WSGI entry point that gunicorn uses."""

    def test_app_module_exposes_app(self):
        """gunicorn references app:app — verify the module-level var exists."""
        from app import app

        assert app is not None
        assert hasattr(app, "wsgi_app")

    def test_app_is_flask_instance(self):
        from flask import Flask

        from app import app

        assert isinstance(app, Flask)
