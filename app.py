"""Flask app entry point.

Step 2 scope: Google OAuth sign-in + single-user lockdown. No database yet.
"""
from __future__ import annotations

import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, session, url_for
from flask_dance.contrib.google import make_google_blueprint
from flask_talisman import Talisman

from auth import login_required

load_dotenv()


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)

    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        AUTHORIZED_EMAIL=os.environ.get("AUTHORIZED_EMAIL", ""),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") != "development",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
    )
    if config:
        app.config.update(config)

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
