"""Scoped MCP connector token (#522, ADR-044).

Why this module exists
----------------------
#522 lets Claude in claude.ai (desktop and phone) create, list, complete,
edit and move tasks through a **custom connector**: a remote MCP server
that Anthropic's servers call. The connector uses "No sign-in" plus a
Request header, so it sends this token as ``Authorization: Bearer
<token>`` on every request. Google OAuth is built for a person in a
browser, the validator cookie is read-only, and the Siri voice token is
scoped to ``/api/voice-review/*``, so none of them fits.

The token authenticates ONLY ``POST /mcp`` (``auth.mcp_token_required``).
No other route reads it, so a leaked token can create tasks, read every
task's title and notes, and complete / edit / move open tasks — never
delete, and never reach goals, projects, settings, exports or auth.

A copy of ``voice_action_token.py``'s design:
- Signed with the app's ``SECRET_KEY`` (rotating the key invalidates
  every token at once).
- A DISTINCT itsdangerous salt, so it can never be replayed as a session,
  validator or voice token (or the other way round).
- Carries only the authorized email, a lifetime and a random ``jti``.
- Minted offline with ``scripts/mint_mcp_token.py``; 365 days by default,
  because replacing it means re-entering the header in claude.ai.

Per-token revocation: ``parse`` rejects a ``jti`` in ``revoked_jtis``. The
web layer reads that set from the ``AppSetting`` denylist
``REVOKED_JTIS_KEY``, which ``flask revoke-mcp-token <jti>`` writes.
"""

from __future__ import annotations

import secrets
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

# Distinct from the session, validator-cookie and voice-token salts.
_SALT = "taskmanager-mcp-v1"

# The AppSetting key holding the JSON list of revoked token ids.
REVOKED_JTIS_KEY = "mcp_revoked_jtis"

DEFAULT_DAYS = 365


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key=secret_key, salt=_SALT)


def new_jti() -> str:
    """A short random token id, printed at mint so this one token can be
    revoked later."""
    return secrets.token_hex(8)


def mint(secret_key: str, email: str, days: int = DEFAULT_DAYS, jti: str | None = None) -> str:
    """Produce a signed MCP token for ``email`` that lives ``days`` days."""
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

    None for: bad signature (wrong key / tampered / another salt), expiry,
    email mismatch with ``AUTHORIZED_EMAIL``, a revoked ``jti``, or any
    parse error. Never raises — callers treat None as 401.
    """
    if not token or not authorized_email:
        return None
    serializer = _serializer(secret_key)
    # Peek (no max_age) to read the baked-in lifetime. The signature is
    # still checked, so a forged ``days`` fails here.
    try:
        payload: dict[str, Any] = serializer.loads(token, max_age=None)
    except Exception:
        return None

    declared_days = payload.get("days")
    if not isinstance(declared_days, int) or declared_days <= 0:
        return None

    try:
        payload = serializer.loads(token, max_age=declared_days * 86400)
    except (SignatureExpired, BadSignature):
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
