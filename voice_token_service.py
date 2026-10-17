"""Make, list and revoke the Siri voice-action token from /settings (#499).

ADR-034 made the token; ADR-042 adds this second way to mint it: the
signed-in web session (real Google OAuth), so the iPhone that runs the
Shortcut can make its own token and paste it, with no laptop involved.

Storage (``AppSetting``, whose ``value`` is ``String(500)``):
- one row per token made here, key ``voice_action_minted:<jti>``, value
  JSON ``{"minted", "expires", "revoked"}`` (ISO UTC; ``revoked`` null
  until revoked). **The token itself is never stored**: the row holds no
  signature, so a token can't be rebuilt from it.
- the shared denylist ``voice_action_token.REVOKED_JTIS_KEY`` (a JSON list
  of jtis) that ``auth.voice_action_or_login`` reads. ``add_revoked_jti``
  is its only writer; the CLI ``revoke-voice-action-token`` uses it too.

The listing prunes a row once its token has expired (by more than a day,
so a clock edge can't drop a live one) and drops that jti from the
denylist: an expired token already fails ``voice_action_token.parse`` on
age, so the entry has stopped doing anything. That keeps the 500-char
denylist bounded by tokens that are revoked AND still live.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

from flask import current_app
from sqlalchemy import select

import voice_action_token
from models import AppSetting, db
from utils import ValidationError, parse_int

ROW_PREFIX = "voice_action_minted:"
DEFAULT_DAYS = 90
MAX_DAYS = 365
# What ``voice_action_token.new_jti()`` makes: ``secrets.token_hex(8)``.
_JTI_RE = re.compile(r"[0-9a-f]{16}")
_VALUE_MAX = 500  # AppSetting.value is String(500)
_PRUNE_GRACE = timedelta(days=1)


def is_valid_jti(value: object) -> bool:
    return isinstance(value, str) and _JTI_RE.fullmatch(value) is not None


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _setting(key: str, *, lock: bool = False) -> AppSetting | None:
    stmt = select(AppSetting).where(AppSetting.key == key)
    if lock:
        stmt = stmt.with_for_update()
    return db.session.scalar(stmt)


def _read_denylist(*, lock: bool = False) -> list[str]:
    """``lock=True`` for a read that will be written back: Postgres holds
    the row (SELECT … FOR UPDATE) until commit, so a revoke and a prune
    racing can't each write a list missing the other's change — a lost
    revoke would silently un-revoke a token. (SQLite ignores the hint; it
    serializes writers anyway.)"""
    row = _setting(voice_action_token.REVOKED_JTIS_KEY, lock=lock)
    if row is None or not row.value:
        return []
    try:
        data = json.loads(row.value)
    except (TypeError, ValueError):
        return []
    return [str(x) for x in data] if isinstance(data, list) else []


def _write_denylist(jtis: list[str]) -> None:
    value = json.dumps(jtis)
    if len(value) > _VALUE_MAX:
        # Never truncate: a cut JSON list fails to parse and silently
        # un-revokes every token on it (the old CLI did `[:500]`).
        raise ValidationError(
            "Too many revoked tokens are still live to list another — rotate "
            "SECRET_KEY on the server to cut off every token at once.",
            "jti",
        )
    row = _setting(voice_action_token.REVOKED_JTIS_KEY)
    if row is None:
        db.session.add(AppSetting(key=voice_action_token.REVOKED_JTIS_KEY, value=value))
    else:
        row.value = value


def add_revoked_jti(jti: str) -> bool:
    """Append ``jti`` to the denylist. Returns False if it was already on
    it. Raises ``ValidationError`` rather than overflow the column. The
    caller commits."""
    current = _read_denylist(lock=True)
    if jti in current:
        return False
    _write_denylist([*current, jti])
    return True


def _rows() -> list[AppSetting]:
    return list(
        db.session.scalars(
            select(AppSetting).where(AppSetting.key.startswith(ROW_PREFIX))
        )
    )


def _row_info(row: AppSetting) -> dict | None:
    try:
        data = json.loads(row.value)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {
        "jti": row.key[len(ROW_PREFIX):],
        "minted": data.get("minted"),
        "expires": data.get("expires"),
        "revoked": data.get("revoked"),
    }


def list_tokens() -> list[dict]:
    """Tokens made here that haven't expired, newest first. Prunes the
    expired ones (and their denylist entries) and commits if it did."""
    now = _now()
    keep: list[dict] = []
    gone: list[str] = []
    for row in _rows():
        info = _row_info(row)
        expires = _parse_iso(info["expires"]) if info else None
        if info is None or expires is None or expires + _PRUNE_GRACE < now:
            gone.append(row.key[len(ROW_PREFIX):])
            db.session.delete(row)
            continue
        keep.append(info)
    if gone:
        denylist = _read_denylist(lock=True)
        trimmed = [j for j in denylist if j not in gone]
        if trimmed != denylist:
            _write_denylist(trimmed)
        db.session.commit()
    keep.sort(key=lambda t: t["minted"] or "", reverse=True)
    return keep


def mint_token(days_raw: object = None) -> dict:
    """Mint a token for ``AUTHORIZED_EMAIL`` and record its id + dates.

    Returns ``{token, jti, expires}`` — the ONLY time the token exists
    outside the Shortcut. Never log the return value.
    """
    days = DEFAULT_DAYS if days_raw is None else parse_int(days_raw, "days")
    if days < 1 or days > MAX_DAYS:
        raise ValidationError(f"days must be between 1 and {MAX_DAYS}", "days")
    secret = current_app.config.get("SECRET_KEY")
    email = current_app.config.get("AUTHORIZED_EMAIL")
    if not secret or not email:
        raise ValidationError("The server has no SECRET_KEY / AUTHORIZED_EMAIL set.")
    jti = voice_action_token.new_jti()
    token = voice_action_token.mint(secret_key=secret, email=email, days=days, jti=jti)
    now = _now()
    expires = _iso(now + timedelta(days=days))
    db.session.add(
        AppSetting(
            key=ROW_PREFIX + jti,
            value=json.dumps({"minted": _iso(now), "expires": expires, "revoked": None}),
        )
    )
    db.session.commit()
    return {"token": token, "jti": jti, "expires": expires}


def revoke_jti(jti: str) -> tuple[bool, bool]:
    """Onto the denylist, and stamped on its row if it was made here.
    Commits. Returns ``(newly_revoked, listed)``. No shape check — the CLI
    calls this with whatever id it was given; the web goes through
    ``revoke_token``."""
    added = add_revoked_jti(jti)
    row = _setting(ROW_PREFIX + jti)
    if row is not None:
        info = _row_info(row)
        if info is not None and not info["revoked"]:
            row.value = json.dumps(
                {"minted": info["minted"], "expires": info["expires"], "revoked": _iso(_now())}
            )
    db.session.commit()
    return added, row is not None


def revoked_count() -> int:
    return len(_read_denylist())


def revoke_token(jti: object) -> dict:
    """Revoke one token by id. A jti with no row (made with the CLI) is
    still revoked. Idempotent."""
    if not is_valid_jti(jti):
        raise ValidationError(
            "That isn't a token id — it is 16 letters and digits (0-9, a-f).",
            "jti",
        )
    _, listed = revoke_jti(jti)
    return {"ok": True, "jti": jti, "listed": listed}
