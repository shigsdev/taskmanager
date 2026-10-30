"""Mint an MCP connector token (#522 / ADR-044).

Does NOT import the Flask app — only ``mcp_token`` (itsdangerous), so it
runs anywhere ``railway run`` can inject the deployed env vars.

Reads SECRET_KEY and AUTHORIZED_EMAIL from the environment and prints the
token to stdout with no trailing newline, then ``jti=<id>`` on stderr so
the token can be piped straight to the clipboard and the id kept for
``flask revoke-mcp-token <id>``.

Usage:
    railway run python scripts/mint_mcp_token.py [--days N] [--email EMAIL]

Save it to a file only you can read, then copy the whole header value at
the moment you paste it into claude.ai's connector (Request header
``authorization``) — copying anything in between replaces it (#522)::

    umask 077; railway run .venv/bin/python scripts/mint_mcp_token.py > ~/.taskmanager-mcp-token
    printf 'Bearer %s' "$(cat ~/.taskmanager-mcp-token)" | pbcopy
    rm ~/.taskmanager-mcp-token
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make the repo root importable so ``import mcp_token`` works regardless
# of where this script is invoked from.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import mcp_token  # noqa: E402  (path mutation must precede)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mint a token for the claude.ai MCP connector (/mcp).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=mcp_token.DEFAULT_DAYS,
        help=f"Lifetime in days (default: {mcp_token.DEFAULT_DAYS}).",
    )
    parser.add_argument(
        "--email",
        default=None,
        help=(
            "Email to bake into the token. Defaults to AUTHORIZED_EMAIL from "
            "the environment; it must match the deployed app's."
        ),
    )
    args = parser.parse_args()

    secret = os.environ.get("SECRET_KEY")
    if not secret:
        print(
            "ERROR: SECRET_KEY is not set in environment.\n"
            "  Prefix with `railway run` to inject the deployed env.",
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

    jti = mcp_token.new_jti()
    token = mcp_token.mint(secret_key=secret, email=email, days=args.days, jti=jti)
    sys.stdout.write(token)
    sys.stdout.flush()
    # The id on stderr, so piping the token to the clipboard stays clean.
    print(f"\njti={jti}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
