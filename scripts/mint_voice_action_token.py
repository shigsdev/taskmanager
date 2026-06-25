"""Standalone voice-action token mint script (#297 / ADR-034).

Same effect as ``flask mint-voice-action-token``, but does NOT import the
Flask app — only depends on ``itsdangerous``. Useful when minting from a
machine without the app's full Python environment (e.g. just
``railway run`` to inject env vars).

Reads SECRET_KEY and AUTHORIZED_EMAIL from environment variables, mints a
scoped voice-review action token via ``voice_action_token.mint``, prints
the token to stdout (no trailing newline, pipe-friendly) and ``jti=<id>``
to stderr so you can later ``flask revoke-voice-action-token <id>``.

The token authenticates ONLY ``/api/voice-review/*`` (read the queue +
complete/move/cancel) — never tasks CRUD, settings, or exports. Paste it
into the iOS Shortcut's Authorization header.

Usage:
    railway run python scripts/mint_voice_action_token.py [--days N] [--email EMAIL]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import voice_action_token  # noqa: E402  (path mutation must precede)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mint a scoped voice-review action token (#297 / ADR-034).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Lifetime of the minted token in days (ADR-034 default: 90).",
    )
    parser.add_argument(
        "--email",
        default=None,
        help=(
            "Email to bake into the token. Defaults to AUTHORIZED_EMAIL "
            "from environment. Must match the deployed app's "
            "AUTHORIZED_EMAIL or the token is rejected at parse time."
        ),
    )
    args = parser.parse_args()

    secret = os.environ.get("SECRET_KEY")
    if not secret:
        print(
            "ERROR: SECRET_KEY is not set in environment "
            "(prefix with `railway run` to inject the deployed env).",
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

    jti = voice_action_token.new_jti()
    token = voice_action_token.mint(
        secret_key=secret, email=email, days=args.days, jti=jti
    )
    sys.stdout.write(token)
    sys.stdout.flush()
    print(f"\njti={jti}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
