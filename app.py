"""Flask app entry point.

Wires up Google OAuth + single-user lockdown, the database, and migrations.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, session, url_for
from flask_dance.contrib.google import make_google_blueprint
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_talisman import Talisman
from werkzeug.middleware.proxy_fix import ProxyFix

import digest_api
import goals_api
import import_api
import projects_api
import recurring_api
import review_api
import scan_api
import settings_api
import tasks_api
from auth import login_required
from models import TaskStatus, Tier, db
from task_service import list_tasks

load_dotenv()


def _normalize_db_url(url: str) -> str:
    """Normalize a Railway-style DB URL.

    Railway injects ``postgres://...`` which SQLAlchemy 2.x rejects, and the
    default ``postgresql://`` scheme pulls in psycopg2. We use psycopg3, so
    we rewrite to the explicit ``postgresql+psycopg://`` scheme.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)

    # Trust Railway's reverse proxy so Flask generates https:// URLs
    # (needed for OAuth redirect URIs to match)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        AUTHORIZED_EMAIL=os.environ.get("AUTHORIZED_EMAIL", ""),
        SQLALCHEMY_DATABASE_URI=_normalize_db_url(
            os.environ.get("DATABASE_URL", "sqlite:///dev.db")
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") != "development",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
    )
    if config:
        app.config.update(config)

    db.init_app(app)
    Migrate(app, db)

    google_bp = make_google_blueprint(
        client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        scope=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
        ],
    )
    app.register_blueprint(google_bp, url_prefix="/login")
    app.register_blueprint(tasks_api.bp)
    app.register_blueprint(goals_api.bp)
    app.register_blueprint(projects_api.bp)
    app.register_blueprint(review_api.bp)
    app.register_blueprint(recurring_api.bp)
    app.register_blueprint(digest_api.bp)
    app.register_blueprint(scan_api.bp)
    app.register_blueprint(import_api.bp)
    app.register_blueprint(settings_api.bp)

    # --- Security: Talisman (HTTPS + headers) ---
    if not app.config.get("TESTING") and os.environ.get("FLASK_ENV") != "development":
        csp = {
            "default-src": "'self'",
            "script-src": "'self' 'unsafe-inline'",
            "style-src": "'self' 'unsafe-inline'",
            "img-src": "'self' data:",
            "font-src": "'self'",
            "connect-src": "'self'",
            "worker-src": "'self'",
            "frame-ancestors": "'none'",
        }
        Talisman(
            app,
            content_security_policy=csp,
            force_https=False,
            session_cookie_secure=True,
            strict_transport_security=True,
            strict_transport_security_max_age=31536000,
            referrer_policy="strict-origin-when-cross-origin",
        )

        @app.before_request
        def _force_https_except_healthz():
            """Redirect HTTP to HTTPS, except for /healthz.

            Railway's internal health checker hits /healthz over plain
            HTTP. Talisman's built-in force_https can't exempt paths,
            so we handle the redirect manually.
            """
            from flask import request
            if request.path == "/healthz":
                return None
            if not request.is_secure and request.headers.get("X-Forwarded-Proto") != "https":
                url = request.url.replace("http://", "https://", 1)
                return redirect(url, code=301)

    # --- Security: rate limiting ---
    # NOTE: memory:// storage is per-worker — with N Gunicorn workers the
    # effective limit is N × 200 req/min. Acceptable for a single-user app.
    # Switch to Redis-backed storage if multi-user support is ever added.
    if not app.config.get("TESTING"):
        Limiter(
            get_remote_address,
            app=app,
            default_limits=["200 per minute"],
            storage_uri="memory://",
        )

    @app.before_request
    def _refresh_session_lifetime():
        session.permanent = True

    @app.route("/")
    @login_required
    def index(email: str):
        return render_template("index.html", email=email)

    @app.route("/goals")
    @login_required
    def goals_page(email: str):  # noqa: ARG001
        return render_template("goals.html")

    @app.route("/review")
    @login_required
    def review_page(email: str):  # noqa: ARG001
        return render_template("review.html")

    @app.route("/scan")
    @login_required
    def scan_page(email: str):  # noqa: ARG001
        return render_template("scan.html")

    @app.route("/import")
    @login_required
    def import_page(email: str):  # noqa: ARG001
        return render_template("import.html")

    @app.route("/settings")
    @login_required
    def settings_page(email: str):  # noqa: ARG001
        return render_template("settings.html")

    @app.route("/print")
    @login_required
    def print_page(email: str):  # noqa: ARG001
        today_tasks = list_tasks(tier=Tier.TODAY, status=TaskStatus.ACTIVE)
        week_tasks = list_tasks(tier=Tier.THIS_WEEK, status=TaskStatus.ACTIVE)
        overdue = [
            t for t in list_tasks(status=TaskStatus.ACTIVE)
            if t.due_date and t.due_date < date.today() and t.tier != Tier.TODAY
        ]
        return render_template(
            "print.html",
            today_tasks=today_tasks,
            week_tasks=week_tasks,
            overdue_tasks=overdue,
            print_date=date.today(),
        )

    @app.route("/logout", methods=["POST", "GET"])
    def logout():
        session.clear()
        return redirect(url_for("login_page"))

    @app.route("/login")
    def login_page():
        return render_template("login.html")

    @app.route("/healthz")
    def healthz():
        """Post-deploy health check — verifies critical systems are working."""
        checks = {}

        # 1. Database connectivity
        try:
            db.session.execute(db.text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as e:
            checks["database"] = f"fail: {e}"

        # 2. Required env vars
        required_vars = ["SECRET_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]
        missing = [v for v in required_vars if not os.environ.get(v)]
        checks["env_vars"] = "ok" if not missing else f"missing: {', '.join(missing)}"

        # 3. Digest scheduler (if configured)
        if os.environ.get("DIGEST_TO_EMAIL"):
            try:
                import importlib.util

                if importlib.util.find_spec("apscheduler"):
                    if os.environ.get("SENDGRID_API_KEY"):
                        checks["digest"] = "ok"
                    else:
                        checks["digest"] = "warn: SENDGRID_API_KEY not set"
                else:
                    checks["digest"] = "fail: apscheduler not installed"
            except Exception:
                checks["digest"] = "fail: apscheduler not installed"
        else:
            checks["digest"] = "skipped: DIGEST_TO_EMAIL not set"

        # Overall status
        failed = [k for k, v in checks.items() if v.startswith("fail")]
        status_code = 503 if failed else 200
        return {"status": "fail" if failed else "ok", "checks": checks}, status_code

    # --- Scheduled digest email ---
    # NOTE: The scheduler is started via gunicorn.conf.py post_worker_init
    # hook, NOT here. Starting it in create_app() would run it in the
    # Gunicorn master process where the background thread dies after fork.
    # For local dev (flask run), call _start_digest_scheduler() manually.

    return app


def _start_digest_scheduler(app: Flask) -> None:
    """Start APScheduler to send the daily digest email."""
    from apscheduler.schedulers.background import BackgroundScheduler

    digest_time = os.environ.get("DIGEST_TIME", "07:00")
    hour, minute = (int(x) for x in digest_time.split(":"))
    tz = os.environ.get("DIGEST_TZ", "America/New_York")

    def _send_scheduled_digest():
        with app.app_context():
            from digest_service import send_digest

            to_email = os.environ.get("DIGEST_TO_EMAIL")
            if to_email:
                send_digest(to_email=to_email)

    scheduler = BackgroundScheduler(timezone=tz)
    scheduler.add_job(
        _send_scheduled_digest,
        "cron",
        hour=hour,
        minute=minute,
        id="daily_digest",
        replace_existing=True,
    )
    scheduler.start()


app = create_app()
