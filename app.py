"""Flask app entry point.

Wires up Google OAuth + single-user lockdown, the database, and migrations.
"""
from __future__ import annotations

import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, session, url_for
from flask_dance.contrib.google import make_google_blueprint
from flask_migrate import Migrate
from flask_talisman import Talisman

import tasks_api
from auth import login_required
from models import db

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

    if not app.config.get("TESTING") and os.environ.get("FLASK_ENV") != "development":
        Talisman(app, content_security_policy=None, force_https=True)

    @app.before_request
    def _refresh_session_lifetime():
        session.permanent = True

    @app.route("/")
    @login_required
    def index(email: str):
        return render_template("index.html", email=email)

    @app.route("/logout", methods=["POST", "GET"])
    def logout():
        session.clear()
        return redirect(url_for("login_page"))

    @app.route("/login")
    def login_page():
        return render_template("login.html")

    @app.route("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


app = create_app()
