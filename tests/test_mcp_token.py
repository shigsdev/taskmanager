"""Tests for the scoped MCP connector token (#522 / ADR-044).

``mcp_token`` is the credential claude.ai's custom connector sends as
``Authorization: Bearer <token>``. These cover the pure sign/parse layer,
the revoke CLI, and the standalone mint script. The endpoint-level scope
checks (the token opens ``/mcp`` and nothing else) live in
``test_mcp_api.py``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time

import pytest
from itsdangerous import URLSafeTimedSerializer

import mcp_token
import voice_action_token
from models import AppSetting

SECRET = "test-secret"  # matches conftest app fixture
EMAIL = "me@example.com"  # matches conftest AUTHORIZED_EMAIL


class _TimeTravel:
    """Mint in the past: shift ``time.time`` back by ``days``."""

    def __init__(self, days: int):
        self.shift = days * 86400

    def __enter__(self):
        self.saved = time.time
        time.time = lambda: self.saved() - self.shift
        return self

    def __exit__(self, *exc):
        time.time = self.saved


class TestParse:
    def test_round_trip(self):
        assert mcp_token.parse(SECRET, mcp_token.mint(SECRET, EMAIL), EMAIL) == EMAIL

    def test_default_lifetime_is_365_days(self):
        tok = mcp_token.mint(SECRET, EMAIL)
        payload = URLSafeTimedSerializer(SECRET, salt="taskmanager-mcp-v1").loads(tok)
        assert payload["days"] == 365

    def test_rejects_wrong_secret(self):
        assert mcp_token.parse("nope", mcp_token.mint(SECRET, EMAIL), EMAIL) is None

    def test_rejects_wrong_email(self):
        tok = mcp_token.mint(SECRET, "intruder@example.com")
        assert mcp_token.parse(SECRET, tok, EMAIL) is None

    def test_rejects_empty_and_garbage(self):
        assert mcp_token.parse(SECRET, "", EMAIL) is None
        assert mcp_token.parse(SECRET, "not-a-token", EMAIL) is None
        assert mcp_token.parse(SECRET, mcp_token.mint(SECRET, EMAIL), "") is None

    def test_mint_rejects_nonpositive_days(self):
        with pytest.raises(ValueError):
            mcp_token.mint(SECRET, EMAIL, days=0)

    def test_rejects_expired(self):
        with _TimeTravel(days=2):
            old = mcp_token.mint(SECRET, EMAIL, days=1)
        assert mcp_token.parse(SECRET, old, EMAIL) is None

    def test_revoked_jti_rejected(self):
        tok = mcp_token.mint(SECRET, EMAIL, jti="deadbeef00")
        assert mcp_token.parse(SECRET, tok, EMAIL, revoked_jtis={"deadbeef00"}) is None
        assert mcp_token.parse(SECRET, tok, EMAIL, revoked_jtis={"other"}) == EMAIL

    def test_rejects_tampered(self):
        tok = mcp_token.mint(SECRET, EMAIL)
        flipped = tok[:-1] + ("A" if tok[-1] != "A" else "B")
        assert mcp_token.parse(SECRET, flipped, EMAIL) is None

    def test_voice_token_is_not_an_mcp_token(self):
        voice = voice_action_token.mint(SECRET, EMAIL, days=90)
        assert mcp_token.parse(SECRET, voice, EMAIL) is None
        assert voice_action_token.parse(SECRET, mcp_token.mint(SECRET, EMAIL), EMAIL) is None


def _denylist(key: str) -> list[str]:
    row = AppSetting.query.filter_by(key=key).one_or_none()
    return json.loads(row.value) if row else []


def test_revoke_cli_adds_jti(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["revoke-mcp-token", "abcd1234abcd1234"])
    assert result.exit_code == 0, result.output
    assert "Revoked jti abcd1234abcd1234" in result.output
    assert _denylist(mcp_token.REVOKED_JTIS_KEY) == ["abcd1234abcd1234"]

    again = runner.invoke(args=["revoke-mcp-token", "abcd1234abcd1234"])
    assert again.exit_code == 0, again.output
    assert "already revoked" in again.output
    # The Siri token's denylist is a different row and stays empty.
    assert _denylist(voice_action_token.REVOKED_JTIS_KEY) == []


def _load_mint_script():
    spec = importlib.util.spec_from_file_location("mint_mcp_token", "scripts/mint_mcp_token.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mint_script_prints_a_valid_token(monkeypatch, capsys):
    monkeypatch.setenv("SECRET_KEY", SECRET)
    monkeypatch.setenv("AUTHORIZED_EMAIL", EMAIL)
    monkeypatch.setattr(sys, "argv", ["mint_mcp_token.py"])

    assert _load_mint_script().main() == 0

    captured = capsys.readouterr()
    assert captured.out and "\n" not in captured.out
    assert mcp_token.parse(SECRET, captured.out, EMAIL) == EMAIL
    assert "jti=" in captured.err


def test_mint_script_errors_without_secret(monkeypatch, capsys):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("AUTHORIZED_EMAIL", EMAIL)
    monkeypatch.setattr(sys, "argv", ["mint_mcp_token.py"])

    assert _load_mint_script().main() == 2
    assert "SECRET_KEY" in capsys.readouterr().err
