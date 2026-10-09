"""Launch Flask with the LOCAL_DEV_BYPASS_AUTH env file loaded.

Usage:
    python scripts/run_dev_bypass.py [--port 5111]

This script is the only supported way to run the local Flask server with
the auth bypass enabled. It does FOUR things in order:

1. Refuse to run if any RAILWAY_* tripwire env var is set. This is a
   belt-and-suspenders match for the gate inside ``auth.py`` — if
   somehow you're running this script on a Railway shell, the script
   exits before Flask even imports.
2. Refuse to run if ``.env.dev-bypass`` does not exist in the project
   root. The file's existence is the on/off switch — delete the file
   and the bypass cannot start. Create the file (with a single line
   ``LOCAL_DEV_BYPASS_AUTH=1``) when you want to start a session.
3. Load ``.env.dev-bypass`` ON TOP of the normal ``.env``.
4. Switch the app's rate limiter OFF for this local server (#385 — every
   Playwright test shares it from one IP, so prod's per-route limits
   turned into 429s once the suite got faster), then import the app and
   serve it with waitress on 127.0.0.1 (#403 — not ``flask run``: Werkzeug's
   dev server closes every connection, which ran Windows out of loopback
   ports under parallel Playwright lanes; waitress keeps them open).
   Creating the app prints the loud "BYPASS IS ACTIVE" warning to stderr.
   Prod never runs this script (it runs gunicorn).

Tear-down: stop the Flask server (Ctrl+C or preview_stop) and delete
``.env.dev-bypass``. Both halves of the SOP are required — the file
must be gone before any commit.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BYPASS_ENV_FILE = PROJECT_ROOT / ".env.dev-bypass"

DEFAULT_PORT = 5111  # matches the .claude/launch.json convention
SERVER_HOST = "127.0.0.1"  # loopback only, like `flask run`'s default
# waitress serves from a fixed pool (`flask run` spawned a thread per
# request). One gate lane is one Playwright worker driving one page, which
# opens at most ~6 connections, so 8 threads keeps a lane from queueing.
SERVER_THREADS = 8

# Match the tripwire list in auth._RAILWAY_TRIPWIRE_VARS — kept duplicated
# here on purpose so the script can refuse BEFORE importing the app.
_RAILWAY_TRIPWIRE_VARS = (
    "RAILWAY_PROJECT_ID",
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_SERVICE_ID",
)


def _disable_rate_limiting() -> None:
    """#385: switch the app's shared limiter off for this local server.

    The bypass server is a test fixture — every Playwright test hits it from
    one IP — so prod's per-route limits (200/min default) turned into 429s
    once the suite ran ~2x faster. Must run before `flask run` imports the
    app: Flask-Limiter's init_app keeps a pre-set `enabled = False` when the
    app config has no RATELIMIT_ENABLED. Prod never runs this script, so its
    limits stand.

    `python scripts/run_dev_bypass.py` puts scripts/ (not the repo root) on
    sys.path, so add the root before importing the app's module.
    """
    root = str(Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from rate_limit import limiter

    limiter.enabled = False


def _parse_port(argv: list[str]) -> int:
    """`--port N` is the only option any caller passes; refuse the rest
    (exit 2) rather than silently ignore a `flask run` flag like --host."""
    parser = argparse.ArgumentParser(prog="run_dev_bypass.py")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args(argv).port


def _create_server(wsgi_app, port: int):
    """#403: a keep-alive HTTP/1.1 server on loopback. Werkzeug's dev server
    sent `Connection: close` on every response, so each page, static file
    and API call took a new port that then sat in TIME_WAIT for ~2 min — 8
    Playwright lanes exhausted Windows' 16,384-port pool (#402)."""
    from waitress import create_server

    return create_server(
        wsgi_app, host=SERVER_HOST, port=port, threads=SERVER_THREADS,
    )


def _serve(port: int) -> None:
    """Import the app (after the env + limiter set-up above) and serve it
    until the process is stopped."""
    from app import app

    server = _create_server(app, port)
    sys.stderr.write(
        f"[run_dev_bypass] Serving on http://{SERVER_HOST}:{port} (waitress)\n"
    )
    sys.stderr.flush()
    server.run()


def main(argv: list[str] | None = None) -> int:
    # Gate 1: Railway tripwire
    set_markers = [v for v in _RAILWAY_TRIPWIRE_VARS if os.environ.get(v)]
    if set_markers:
        sys.stderr.write(
            "REFUSING to start dev bypass server: Railway tripwire(s) "
            f"are set: {set_markers}. This script is for LOCAL use only.\n"
        )
        return 2

    # Gate 2: bypass file must exist
    if not BYPASS_ENV_FILE.exists():
        sys.stderr.write(
            f"REFUSING to start dev bypass server: {BYPASS_ENV_FILE} "
            "does not exist. Create it (one line: LOCAL_DEV_BYPASS_AUTH=1) "
            "to start a bypass session, then delete it when you're done.\n"
        )
        return 2

    # Gate 3: load .env.dev-bypass on top of the normal .env. python-dotenv
    # is already a project dependency (Flask uses it internally for .env).
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(BYPASS_ENV_FILE, override=True)

    if os.environ.get("LOCAL_DEV_BYPASS_AUTH") != "1":
        sys.stderr.write(
            "REFUSING to start: .env.dev-bypass exists but did not set "
            "LOCAL_DEV_BYPASS_AUTH=1. Check the file contents.\n"
        )
        return 2

    # Force FLASK_ENV=development so the in-process auth gate also passes.
    # This script never runs on Railway (gate 1) so this is safe.
    os.environ["FLASK_ENV"] = "development"

    port = _parse_port(sys.argv[1:] if argv is None else argv)
    _disable_rate_limiting()

    sys.stderr.write(
        "[run_dev_bypass] Loaded .env.dev-bypass. Rate limiting OFF "
        "(local test server). Starting the app...\n"
    )
    sys.stderr.flush()

    _serve(port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
