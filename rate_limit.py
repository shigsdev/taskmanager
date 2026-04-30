"""Module-scope Flask-Limiter instance.

PR64 audit fix #124: previously the Limiter was constructed inline
inside `create_app()` and never bound to a module-level name, which made
per-route decoration (`@limiter.limit(...)`) impossible. Per-route
limits matter because the global default of 200 req/min is too generous
for endpoints that fan out to paid third-party APIs (Google Vision,
OpenAI Whisper, Anthropic Claude). A logged-in user — or someone with
a stolen session cookie — could rack up real API costs hitting those
routes 200×/min.

Living in its own module avoids the circular import that would happen
if route blueprints (`scan_api`, `voice_api`) tried to `from app import
limiter` while app.py was still importing those blueprints.

storage_uri='memory://' is intentional — single-user app on Railway,
no need for Redis. Limits are per-worker (Gunicorn N workers = effective
N×limit), which the threat model accepts.
"""
from __future__ import annotations

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute"],
    storage_uri="memory://",
)
