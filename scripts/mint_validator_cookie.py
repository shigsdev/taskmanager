"""Standalone validator-cookie mint script.

Same effect as ``flask mint-validator-cookie``, but does NOT import the
Flask app — only depends on ``itsdangerous``. Useful when you want to
mint a cookie from a machine that doesn't have the app's full Python
environment installed (e.g. just running ``railway run`` to inject env
vars), or when boot-time imports like the SQLAlchemy/psycopg driver are
unavailable.

Reads SECRET_KEY and AUTHORIZED_EMAIL from environment variables, mints
a token via ``validator_cookie.mint``, and prints it to stdout with no
trailing newline so the output can be piped directly into the cookie
file.

Usage:
    railway run python scripts/mint_validator_cookie.py [--days N] [--email EMAIL]

Pipe to file (PowerShell)::

    railway run python scripts/mint_validator_cookie.py |
        Set-Content -NoNewline -Path "$HOME\\.taskmanager-session-cookie"
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make the repo root importable so ``import validator_cookie`` works
# regardless of where this script is invoked from.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import validator_cookie  # noqa: E402  (path mutation must precede)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mint a long-lived validator cookie for /api/auth/status.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Lifetime of the minted cookie in days (default: 90).",
    )
    parser.add_argument(
        "--email",
        default=None,
        help=(
            "Email to bake into the cookie. Defaults to AUTHORIZED_EMAIL "
            "from environment. Must match the deployed app's "
            "AUTHORIZED_EMAIL or the cookie will be rejected at parse time."
        ),
    )
    args = parser.parse_args()

    secret = os.environ.get("SECRET_KEY")
    if not secret:
        print(
            "ERROR: SECRET_KEY is not set in environment.\n"
            "  - Locally: set it before running, e.g.\n"
            "      $env:SECRET_KEY='...'  (PowerShell)\n"
            "      export SECRET_KEY='...' (bash)\n"
            "  - Via Railway CLI: prefix with `railway run` to inject "
            "the deployed env.",
            file=sys.stderr,
        )
        return 2

    email = args.email or os.environ.get("AUTHORIZED_EMAIL")
    if not email:
        print(
            "ERROR: AUTHORIZED_EMAIL is not set and no --email was provided.",
            file=sys.stderr,
        )
        return 2

    if args.days <= 0:
        print(f"ERROR: --days must be positive (got {args.days})", file=sys.stderr)
        return 2

    token = validator_cookie.mint(
        secret_key=secret,
        email=email,
        days=args.days,
    )
    # Plain stdout, no trailing newline — caller pipes this directly
    # into ~/.taskmanager-session-cookie.
    sys.stdout.write(token)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
