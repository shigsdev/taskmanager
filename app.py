"""Flask app entry point.

Wires up Google OAuth + single-user lockdown, the database, and migrations.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, session, url_for
from flask import jsonify as _jsonify
from flask_dance.contrib.google import make_google_blueprint
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_talisman import Talisman
from werkzeug.middleware.proxy_fix import ProxyFix

import auth_api
import debug_api
import digest_api
import goals_api
import import_api
import projects_api
import recurring_api
import recycle_api
import review_api
import scan_api
import settings_api
import tasks_api
import voice_api
from auth import log_bypass_startup_banner, login_required
from logging_service import configure_logging
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


def _ensure_postgres_enum_values() -> None:
    """Idempotently add late-introduced enum values on Postgres.

    Two bugs combined to break this in production:

    1. Alembic wraps each migration in a transaction; Postgres does not
       allow ``ALTER TYPE … ADD VALUE`` inside a transaction block and
       silently rolled it back without re-raising — so alembic_version
       still bumped but the value was never added.
    2. SQLAlchemy's ``Enum(PythonEnum)`` defaults to using the Python
       enum **member names** (UPPERCASE: ``TODAY``, ``THIS_WEEK``) for
       PG storage, not the ``.value`` string. Our first repair attempt
       added the lowercase ``.value`` strings (``next_week``,
       ``cancelled``) which SQLAlchemy never queries with — so the
       endpoints stayed broken even after the ALTER appeared to succeed.

    Belt-and-braces: open a raw connection in AUTOCOMMIT mode and
    add the **UPPERCASE** member names. ``IF NOT EXISTS`` keeps this
    safe to run on every startup forever.
    """
    import logging
    log = logging.getLogger(__name__)
    try:
        from sqlalchemy import text
        engine = db.engine
        if engine.dialect.name != "postgresql":
            return
        with engine.connect() as conn:
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            for sql in (
                "ALTER TYPE tier ADD VALUE IF NOT EXISTS 'NEXT_WEEK'",
                "ALTER TYPE tier ADD VALUE IF NOT EXISTS 'TOMORROW'",
                "ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'CANCELLED'",
            ):
                try:
                    conn.execute(text(sql))
                except Exception as e:  # noqa: BLE001
                    log.warning(
                        "enum repair skipped (%s): %s: %s",
                        sql, type(e).__name__, e,
                    )
    except Exception as e:  # noqa: BLE001
        # Don't crash startup if DB isn't reachable; health check covers
        # genuine connectivity issues. This is a repair gate, not critical.
        log.warning("enum repair gate failed: %s: %s", type(e).__name__, e)


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
        # Backlog #31: Railway's managed Postgres occasionally drops
        # connection-pool SSL handshakes ("SSL SYSCALL error: EOF
        # detected", "decryption failed or bad record mac"). pool_pre_ping
        # issues a cheap SELECT 1 on every checkout and transparently
        # reconnects on failure — the user never sees the 500. The cost
        # is one round-trip per checkout, negligible for a single-user
        # app. Observed recurring in prod and caused intermittent
        # Playwright failures until fixed.
        SQLALCHEMY_ENGINE_OPTIONS={
            "pool_pre_ping": True,
        },
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") != "development",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
        # Hard cap on every incoming request body. 30 MB covers our
        # largest legitimate upload (25 MB Whisper limit + multipart
        # overhead). Werkzeug rejects bigger requests with 413 BEFORE
        # they reach view code, preventing memory-exhaustion DoS via
        # huge audio/image uploads even from authenticated clients.
        MAX_CONTENT_LENGTH=30 * 1024 * 1024,
    )
    if config:
        app.config.update(config)

    db.init_app(app)
    Migrate(app, db)

    # Repair gate: alembic's `ALTER TYPE ... ADD VALUE` migrations for the
    # tier and taskstatus enums silently failed in prod (PG rejects the
    # statement inside any transaction block; alembic still bumped
    # alembic_version because nothing re-raised). Both `next_week` (#23)
    # and `cancelled` (#25) were missing in production despite migrations
    # reporting success. We belt-and-braces the recovery here by running
    # both ALTERs idempotently on every Postgres startup, OUTSIDE any
    # transaction. SQLite is skipped entirely (enums stored as strings).
    # Safe to re-run forever — IF NOT EXISTS makes it a no-op once added.
    with app.app_context():
        _ensure_postgres_enum_values()

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
    app.register_blueprint(recycle_api.bp)
    app.register_blueprint(settings_api.bp)
    app.register_blueprint(debug_api.bp)
    app.register_blueprint(auth_api.bp)
    app.register_blueprint(voice_api.bp)

    # --- Persistent application logging (see logging_service.py) ---
    # Installs DBLogHandler on the root logger so WARNING+ events land
    # in the app_logs table, plus Flask before/after_request hooks that
    # stamp request_id/route/method on every LogRecord. Disabled in
    # tests via APP_LOG_DISABLE to keep test output clean — individual
    # logging tests re-enable via a fixture.
    if not app.config.get("TESTING"):
        configure_logging(app)
        # Print the loud bypass banner AFTER logging is configured so the
        # WARNING row from the banner lands in app_logs alongside future
        # bypass-served requests. No-op if the bypass is not active.
        log_bypass_startup_banner()

    # --- Security: Talisman (HTTPS + headers) ---
    if not app.config.get("TESTING") and os.environ.get("FLASK_ENV") != "development":
        csp = {
            "default-src": "'self'",
            # cdn.jsdelivr.net: Mermaid v10 ESM module loaded only on
            # the /architecture page (#42). Pinned-version URL hashed
            # via SRI in the template, so CDN tampering can't substitute
            # arbitrary code. ADR-028.
            "script-src": "'self' 'unsafe-inline' https://cdn.jsdelivr.net",
            "style-src": "'self' 'unsafe-inline'",
            "img-src": "'self' data:",
            "font-src": "'self' https://fonts.gstatic.com",
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

    @app.route("/tier/<name>")
    @login_required
    def tier_detail_page(email: str, name: str):  # noqa: ARG001
        """Dedicated full-page view of a single tier — see ADR-009.

        Click-through from the board's tier headings. Validates the
        slug against the Tier enum so unknown tiers 404 cleanly.
        """
        from flask import abort
        try:
            tier = Tier(name)
        except ValueError:
            abort(404)
        # Map enum value to the human-readable label used in the page
        # title and back-link. Avoids a separate helper since this is
        # the only place the mapping is needed.
        labels = {
            Tier.INBOX: "Inbox",
            Tier.TODAY: "Today",
            Tier.TOMORROW: "Tomorrow",
            Tier.THIS_WEEK: "This Week",
            Tier.NEXT_WEEK: "Next Week",
            Tier.BACKLOG: "Backlog",
            Tier.FREEZER: "Freezer",
        }
        return render_template(
            "tier.html",
            tier_value=tier.value,
            tier_label=labels.get(tier, tier.value),
        )

    @app.route("/completed")
    @login_required
    def completed_page(email: str):  # noqa: ARG001
        """Dedicated full-page view of completed tasks (#29).

        Parallel to ``/tier/<name>`` (#22) but filters by
        ``status=archived`` rather than ``tier=X``. "Completed" isn't
        a Tier enum value, so it gets its own route + template rather
        than overloading /tier/completed with an enum special-case.
        """
        return render_template("completed.html")

    @app.route("/docs")
    @login_required
    def docs_page(email: str):  # noqa: ARG001
        """In-app documentation hub (#33).

        Houses user-facing formatting rules, shortcuts, and behavior
        notes. First content: the OneNote text import format so the
        user can clean source data before pasting. Structured with a
        sidebar TOC so future topics slot in cleanly.
        """
        return render_template("docs.html")

    @app.route("/architecture")
    @login_required
    def architecture_page(email: str):  # noqa: ARG001
        """In-app system architecture documentation (#42).

        Renders ARCHITECTURE.md inline + auto-generated route catalog
        + auto-generated SQLAlchemy ER diagram + 3 hand-written Mermaid
        sequence flows (recurring spawn, voice memo, auth). The
        rendered content is the source of truth, not a hand-edited
        copy — see ADR-028 for the drift-prevention rationale.
        """
        from pathlib import Path

        from markupsafe import Markup

        from architecture_service import (
            build_er_diagram,
            build_route_catalog,
            render_architecture_md,
        )
        repo_root = Path(__file__).resolve().parent
        try:
            arch_html = render_architecture_md(repo_root / "ARCHITECTURE.md")
        except FileNotFoundError:
            # Static fallback string, no user data — wrapped in Markup
            # so Jinja renders the <em> tag instead of escaping it.
            arch_html = Markup(
                "<p><em>ARCHITECTURE.md is missing from this deploy.</em></p>",
            )
        return render_template(
            "architecture.html",
            architecture_md_html=arch_html,
            route_catalog=build_route_catalog(app),
            er_diagram=build_er_diagram(),
        )

    @app.route("/goals")
    @login_required
    def goals_page(email: str):  # noqa: ARG001
        return render_template("goals.html")

    @app.route("/projects")
    @login_required
    def projects_page(email: str):  # noqa: ARG001
        return render_template("projects.html")

    @app.route("/review")
    @login_required
    def review_page(email: str):  # noqa: ARG001
        return render_template("review.html")

    @app.route("/scan")
    @login_required
    def scan_page(email: str):  # noqa: ARG001
        return render_template("scan.html")

    @app.route("/voice-memo")
    @login_required
    def voice_memo_page(email: str):  # noqa: ARG001
        return render_template("voice_memo.html")

    @app.route("/import")
    @login_required
    def import_page(email: str):  # noqa: ARG001
        return render_template("import.html")

    @app.route("/settings")
    @login_required
    def settings_page(email: str):  # noqa: ARG001
        return render_template("settings.html")

    @app.route("/recycle-bin")
    @login_required
    def recycle_bin_page(email: str):  # noqa: ARG001
        return render_template("recycle_bin.html")

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

    @app.route("/api/export")
    @login_required
    def export_data(email: str):  # noqa: ARG001
        """Download a full JSON backup of all tasks, goals, and projects."""
        from goal_service import list_goals
        from project_service import list_projects

        all_tasks = list_tasks(status=None)  # all statuses
        all_goals = list_goals()
        all_projects = list_projects()

        def serialize_task(t):
            return {
                "id": str(t.id), "title": t.title, "tier": t.tier.value,
                "type": t.type.value, "status": t.status.value,
                "project_id": str(t.project_id) if t.project_id else None,
                "goal_id": str(t.goal_id) if t.goal_id else None,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "url": t.url, "notes": t.notes, "checklist": t.checklist,
                "sort_order": t.sort_order,
                "created_at": t.created_at.isoformat(),
                "updated_at": t.updated_at.isoformat(),
            }

        def serialize_goal(g):
            return {
                "id": str(g.id), "title": g.title,
                "category": g.category.value, "priority": g.priority.value,
                "priority_rank": g.priority_rank, "actions": g.actions,
                "target_quarter": g.target_quarter,
                "status": g.status.value, "notes": g.notes,
                "created_at": g.created_at.isoformat(),
                "updated_at": g.updated_at.isoformat(),
            }

        def serialize_project(p):
            return {
                "id": str(p.id), "name": p.name, "color": p.color,
                "type": p.type.value, "is_active": p.is_active,
                "created_at": p.created_at.isoformat(),
            }

        backup = {
            "exported_at": date.today().isoformat(),
            "tasks": [serialize_task(t) for t in all_tasks],
            "goals": [serialize_goal(g) for g in all_goals],
            "projects": [serialize_project(p) for p in all_projects],
        }
        resp = _jsonify(backup)
        resp.headers["Content-Disposition"] = (
            f"attachment; filename=taskmanager-backup-{date.today()}.json"
        )
        return resp

    @app.route("/sw.js")
    def service_worker():
        """Serve SW from root so it can control scope '/'."""
        return app.send_static_file("sw.js"), 200, {
            "Content-Type": "application/javascript",
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache",
        }

    @app.route("/healthz")
    def healthz():
        """Post-deploy health check — verifies critical systems are working.

        See ``health.py`` for the full list of checks. The response
        always includes a ``git_sha`` field so deploy-validation scripts
        can confirm they are hitting the newly-deployed container
        (Railway does rolling deploys, so an HTTP 200 alone doesn't
        prove the new code is live).
        """
        import health as _health

        report = _health.run_health_checks(app, db)
        # HTTP 503 only fires if a CRITICAL check failed. Non-critical
        # failures (bad migration state, missing table, scheduler not
        # running, etc.) are reported in the body but don't block
        # Railway from promoting the container — otherwise a bug in a
        # new check could brick every deploy.
        status_code = 503 if report["critical_failed"] else 200
        return report, status_code

    # --- Scheduled digest email ---
    # NOTE: The scheduler is started via gunicorn.conf.py post_worker_init
    # hook, NOT here. Starting it in create_app() would run it in the
    # Gunicorn master process where the background thread dies after fork.
    # For local dev (flask run), call _start_digest_scheduler() manually.

    # --- CLI commands ---
    _register_cli_commands(app)

    return app


def _register_cli_commands(app: Flask) -> None:
    """Register ``flask <command>`` CLI commands on the app.

    Commands here are operator tools, not user-facing features. They run
    in the Flask CLI context so they have full access to ``app.config``
    without needing to spin up a real HTTP server.
    """
    import click

    import validator_cookie

    @app.cli.command("mint-validator-cookie")
    @click.option(
        "--days",
        default=90,
        show_default=True,
        type=click.IntRange(min=1, max=3650),
        help="Lifetime of the minted cookie in days.",
    )
    @click.option(
        "--email",
        default=None,
        help=(
            "Email to bake into the cookie. Defaults to AUTHORIZED_EMAIL "
            "from config. Must match AUTHORIZED_EMAIL at parse time or "
            "the cookie is rejected."
        ),
    )
    def mint_validator_cookie(days: int, email: str | None) -> None:
        """Mint a long-lived validator cookie and print the value.

        Typical use::

            flask mint-validator-cookie > ~/.taskmanager-session-cookie

        Then ``python scripts/validate_deploy.py --auth-check`` reads
        the file and sends the token to ``/api/auth/status``. The cookie
        authenticates ONLY that one endpoint — it cannot access tasks,
        goals, or any user data.
        """
        secret = app.config.get("SECRET_KEY")
        if not secret:
            raise click.ClickException("SECRET_KEY is not configured.")
        target_email = email or app.config.get("AUTHORIZED_EMAIL")
        if not target_email:
            raise click.ClickException(
                "AUTHORIZED_EMAIL is not set and no --email was provided."
            )
        token = validator_cookie.mint(
            secret_key=secret,
            email=target_email,
            days=days,
        )
        # Plain print, no trailing metadata — the user pipes this
        # directly into ~/.taskmanager-session-cookie.
        click.echo(token, nl=False)


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

    # Backlog #27: auto-roll Tomorrow → Today at the user's local
    # midnight. The user put the task in Tomorrow with the intent of
    # working on it tomorrow-now-today; rolling at 00:00 makes the
    # Today panel reflect that intent without a manual move. Uses the
    # same timezone as the digest so behaviour is predictable from
    # the user's POV.
    def _roll_tomorrow_to_today():
        with app.app_context():
            from task_service import roll_tomorrow_to_today
            roll_tomorrow_to_today()

    scheduler.add_job(
        _roll_tomorrow_to_today,
        "cron",
        hour=0,
        minute=1,  # 1 past midnight so we're clearly past the boundary
        id="tomorrow_roll",
        replace_existing=True,
    )

    # Backlog #35: auto-spawn recurring task instances on their fire
    # day. Paired with #32's preview cards — previews show "this is
    # coming Friday," and this cron materialises them on Friday
    # morning so the user sees a real, checkable card in Today
    # instead of still-a-preview in This Week.
    #
    # Runs at 00:05 local so it's well past the 00:01 tomorrow_roll
    # and any DST-edge jitter. spawn_today_tasks() is idempotent
    # (title-match suppression), so re-running manually via
    # /api/recurring/spawn later the same day is a safe no-op.
    #
    # Paired collision safety: the spawned Task's created_at.date()
    # == today (DIGEST_TZ via the #33 TZ fix in compute_previews_in_range),
    # so the This Week preview for the same fire_date gets suppressed
    # via the #34 filter — no double-render.
    def _spawn_recurring_for_today():
        with app.app_context():
            from recurring_service import spawn_today_tasks
            spawn_today_tasks()

    scheduler.add_job(
        _spawn_recurring_for_today,
        "cron",
        hour=0,
        minute=5,
        id="recurring_spawn",
        replace_existing=True,
    )

    # Heartbeat job. Gunicorn runs multiple workers but post_worker_init
    # only starts the scheduler in worker 1 (to avoid duplicate emails),
    # so health._scheduler is None in the other workers and /healthz
    # would randomly return "warn: scheduler not registered" depending
    # on which worker the probe hit. The heartbeat job writes a small
    # JSON file every minute with the next run time; check_digest in
    # any worker can read that file to prove the scheduler is alive.
    import health as _health

    def _write_heartbeat():
        _health.write_scheduler_heartbeat(scheduler)

    # NOTE: do NOT pass next_run_time here. Passing a naive datetime to
    # an interval job whose scheduler has a timezone confuses APScheduler
    # and the interval silently stops firing after the first run — the
    # exact bug we hit on Railway where age=0 at boot then frozen at 414s.
    # Letting APScheduler compute its own next fire time (= now + interval)
    # works correctly.
    scheduler.add_job(
        _write_heartbeat,
        "interval",
        seconds=45,
        id="scheduler_heartbeat",
        replace_existing=True,
    )
    scheduler.start()

    # Fire once immediately so a freshly-booted container reports ok
    # without waiting for the first interval tick.
    _write_heartbeat()

    # Expose the live scheduler to /healthz so it can verify the job is
    # actually registered and has a future-dated next run, not just
    # that apscheduler is importable.
    _health.register_scheduler(scheduler)


app = create_app()
