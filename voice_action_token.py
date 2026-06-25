"""Scoped voice-review action token (ADR-034).

Why this module exists
----------------------
Feature #297 (Voice Task Review) lets an iOS Shortcut — driven by Siri /
CarPlay for fully hands-free task triage while driving — complete, move,
or cancel today's tasks by voice. A Shortcut cannot carry an OAuth
session, and the validator cookie (``validator_cookie.py``, ADR-003/004)
is deliberately READ-ONLY, so neither existing auth path can mutate.

This module mints/parses a **separate, narrowly-scoped** bearer token
that authenticates ONLY the ``/api/voice-review/*`` blueprint (see
``voice_review_api.py``). It is structurally rejected everywhere else —
no ``@login_required`` route checks it — so a leaked token can only
complete / move-to-whitelist / cancel the user's own tasks, never read
unrelated data, delete, or touch settings/exports/auth.

Mirrors ``validator_cookie.py``:
- Signed with the app's ``SECRET_KEY`` (rotating the key instantly
  invalidates every minted token — the nuclear kill-switch).
- A DISTINCT itsdangerous salt so it can never be replayed as a session
  cookie or a validator cookie (or vice versa).
- Carries only the authorized email + a lifetime + a random ``jti``
  (token id) — no OAuth token, no user data.
- Minted offline via ``flask mint-voice-action-token`` /
  ``scripts/mint_voice_action_token.py``; 90-day default lifetime
  (per ADR-034, operator-approved 2026-06-22).

Per-token revocation
--------------------
Each token carries a random ``jti``. ``parse`` rejects any token whose
``jti`` is in the caller-supplied ``revoked_jtis`` set. The web layer
sources that set from the ``AppSetting`` denylist (key
``voice_action_revoked_jtis``); ``flask revoke-voice-action-token <jti>``
appends to it. This revokes a SINGLE token without a full ``SECRET_KEY``
rotation. (Keeping ``parse`` pure — the DB read lives in the caller —
keeps this module trivially unit-testable.)
"""
from __future__ import annotations

import secrets
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

# Distinct from the validator cookie's salt + Flask's session salt so a
# leaked SECRET_KEY signer for one cannot forge the others.
_SALT = "taskmanager-voice-action-v1"

# The AppSetting key holding the JSON list of revoked token ids.
REVOKED_JTIS_KEY = "voice_action_revoked_jtis"


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key=secret_key, salt=_SALT)


def new_jti() -> str:
    """A short random token id, baked into the token + printed at mint so
    the operator can later revoke this specific token."""
    return secrets.token_hex(8)


def mint(secret_key: str, email: str, days: int, jti: str | None = None) -> str:
    """Produce a signed voice-action token.

    Args:
        secret_key: Flask ``SECRET_KEY``. Rotating it invalidates every
            previously-minted voice-action token — intentional.
        email: Must match ``AUTHORIZED_EMAIL`` at parse time (single-user
            lockdown, enforced in ``parse``).
        days: Lifetime in days; ``parse`` rejects older tokens.
        jti: Optional explicit token id (tests). Defaults to a random one.

    Returns:
        An opaque URL-safe bearer token for the ``Authorization`` header.
    """
    if days <= 0:
        raise ValueError(f"days must be positive; got {days}")
    payload = {"email": email, "days": days, "jti": jti or new_jti()}
    return _serializer(secret_key).dumps(payload)


def parse(
    secret_key: str,
    token: str,
    authorized_email: str,
    revoked_jtis: set[str] | frozenset[str] | None = None,
) -> str | None:
    """Validate a token and return its email, or None if invalid.

    Returns None for: bad signature (wrong key / tampered), expiry
    (older than the baked-in ``days``), email mismatch with
    ``AUTHORIZED_EMAIL``, a ``jti`` present in ``revoked_jtis``, or any
    unexpected parse error. Never raises — callers treat None as 401.
    """
    if not token or not authorized_email:
        return None
    serializer = _serializer(secret_key)
    # Peek (no max_age) to read the baked-in lifetime. itsdangerous still
    # checks the signature here, so a tampered ``days`` only ever SHORTENS
    # the lifetime (a larger forged value fails the signature check).
    try:
        payload: dict[str, Any] = serializer.loads(token, max_age=None)
    except BadSignature:
        return None
    except Exception:
        return None

    declared_days = payload.get("days")
    if not isinstance(declared_days, int) or declared_days <= 0:
        return None

    try:
        payload = serializer.loads(token, max_age=declared_days * 86400)
    except SignatureExpired:
        return None
    except BadSignature:
        return None
    except Exception:
        return None

    email = payload.get("email")
    if not isinstance(email, str):
        return None
    if email.strip().lower() != authorized_email.strip().lower():
        return None

    jti = payload.get("jti")
    if revoked_jtis and isinstance(jti, str) and jti in revoked_jtis:
        return None

    return email
