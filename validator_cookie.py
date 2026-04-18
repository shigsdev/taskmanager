"""Dedicated long-lived cookie for post-deploy validation.

Why this module exists
----------------------
The post-deploy validator (`scripts/validate_deploy.py --auth-check`) needs
a way to authenticate to the deployed app so it can hit `/api/auth/status`
and verify the auth pipeline is healthy. The naive approach — have the
user copy their real Flask session cookie out of Chrome — has a fatal
rough edge: Flask-Dance auto-refreshes the OAuth token during normal
browser use, which silently re-signs the session cookie and invalidates
the captured copy.

This module introduces a **separate, dedicated cookie** (`validator_token`)
that:

- Is signed with the same ``SECRET_KEY`` as Flask sessions (so rotating
  the key instantly invalidates the validator cookie — good)
- Uses a different ``itsdangerous`` salt so it cannot be confused with
  or replay-attacked against the real session cookie
- Carries only the authorized email as its payload — no OAuth token, no
  user data
- Is minted offline via ``flask mint-validator-cookie`` (or
  ``scripts/mint_validator_cookie.py`` standalone) and lives for 90
  days by default (configurable per-mint via ``--days``)

Scope of what this cookie can do
--------------------------------
The validator cookie authenticates:

1. ``/api/auth/status`` directly (its own branch in ``auth_api.py``)
2. **Any login_required-protected route on safe HTTP methods** (GET,
   HEAD, OPTIONS) via ``auth.login_required``'s read-only branch.
   This was widened from "auth-status only" on 2026-04-17 so the
   prod Playwright suite could verify page renders end-to-end (see
   ``docs/adr/004-validator-cookie-broaden-to-reads.md``).

The cookie does NOT authenticate mutation methods (POST, PATCH,
DELETE, PUT) — those always fall through to OAuth. So a leaked
validator cookie can read your tasks/goals/projects for up to 90
days, but cannot create, modify, or delete anything.

If the cookie ever leaks (committed to git, sent in plaintext, etc.):
rotate ``SECRET_KEY`` on Railway. That instantly invalidates every
validator cookie ever minted with the old key.
"""
from __future__ import annotations

from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

COOKIE_NAME = "validator_token"

# Salt distinct from Flask's built-in ``cookie-session`` salt so a leaked
# SECRET_KEY's session signer cannot be used to forge validator cookies
# (and vice versa). itsdangerous uses the salt as a namespace separator.
_SALT = "taskmanager-validator-v1"


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    """Construct the signer with the app's secret key and our salt."""
    return URLSafeTimedSerializer(secret_key=secret_key, salt=_SALT)


def mint(secret_key: str, email: str, days: int) -> str:
    """Produce a signed token that encodes the email and mint time.

    Args:
        secret_key: Flask's ``SECRET_KEY``. Rotating it invalidates all
            previously-minted validator cookies — intentional.
        email: The email that `/api/auth/status` will report when this
            cookie authenticates. Must match the configured
            ``AUTHORIZED_EMAIL`` — enforced at parse time in
            ``parse_validator_cookie``.
        days: Lifetime in days. ``parse`` rejects tokens older than this
            regardless of what the file header claims.

    Returns:
        An opaque URL-safe token, e.g.
        ``"eyJlbWFpbCI6Im1lQGV4YW1wbGUuY29tIn0.aeKlVA.abc123..."``.
    """
    if days <= 0:
        raise ValueError(f"days must be positive; got {days}")
    payload = {"email": email, "days": days}
    return _serializer(secret_key).dumps(payload)


def parse(
    secret_key: str,
    token: str,
    authorized_email: str,
) -> str | None:
    """Validate a token and return its email, or None if invalid.

    Returns None for:
    - bad signature (wrong SECRET_KEY, tampered token)
    - expired (older than ``days`` from the mint time)
    - email mismatch with the configured ``AUTHORIZED_EMAIL``
    - any unexpected parse error

    Does not raise — callers treat None as "reject, return 401".
    """
    if not token or not authorized_email:
        return None
    serializer = _serializer(secret_key)
    # Peek at the unverified payload to read the mint-time-declared max
    # age. itsdangerous checks max_age against the signed timestamp, so
    # even if the caller tampered with ``days`` it can only SHORTEN the
    # lifetime (larger values past the real age still fail signature).
    try:
        payload: dict[str, Any] = serializer.loads(token, max_age=None)
    except BadSignature:
        return None
    except Exception:
        return None

    declared_days = payload.get("days")
    if not isinstance(declared_days, int) or declared_days <= 0:
        return None

    # Now re-validate with the explicit max_age from the payload so
    # ``days=1`` tokens aren't accepted for a year just because no-one
    # checked the timestamp.
    max_age_sec = declared_days * 86400
    try:
        payload = serializer.loads(token, max_age=max_age_sec)
    except SignatureExpired:
        return None
    except BadSignature:
        return None
    except Exception:
        return None

    email = payload.get("email")
    if not isinstance(email, str):
        return None
    # Single-user lockdown: the cookie must carry the same email that the
    # app is configured to authorize. A cookie minted at a time when
    # AUTHORIZED_EMAIL was different cannot be replayed.
    if email.strip().lower() != authorized_email.strip().lower():
        return None
    return email
