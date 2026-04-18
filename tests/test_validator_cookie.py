"""Tests for the long-lived validator cookie.

Covers:
- pure mint/parse round-trip in validator_cookie.py
- signature + age enforcement
- email binding (cannot replay a cookie with a different email)
- integration with /api/auth/status (authenticates that endpoint only)
- negative: validator cookie does NOT authenticate other protected routes
"""
from __future__ import annotations

import time

import pytest

import validator_cookie

SECRET = "test-secret"
OTHER_SECRET = "different-secret-key"  # noqa: S105  (test fixture)
EMAIL = "me@example.com"
OTHER_EMAIL = "attacker@example.com"


# --- Pure function tests (validator_cookie.py) -------------------------------


def test_mint_and_parse_round_trip():
    """Happy path: freshly minted cookie parses back to the original email."""
    token = validator_cookie.mint(SECRET, EMAIL, days=90)
    assert validator_cookie.parse(SECRET, token, EMAIL) == EMAIL


def test_mint_rejects_zero_or_negative_days():
    """days must be positive — a 0-day cookie is never valid, would be
    confusing, and hints at a caller bug. Raise instead of silently
    producing garbage."""
    with pytest.raises(ValueError):
        validator_cookie.mint(SECRET, EMAIL, days=0)
    with pytest.raises(ValueError):
        validator_cookie.mint(SECRET, EMAIL, days=-1)


def test_parse_rejects_wrong_secret():
    """A token signed with a different SECRET_KEY must not verify —
    this is what makes rotating SECRET_KEY an emergency 'invalidate
    all validator cookies' lever."""
    token = validator_cookie.mint(SECRET, EMAIL, days=90)
    assert validator_cookie.parse(OTHER_SECRET, token, EMAIL) is None


def test_parse_rejects_wrong_email():
    """Single-user lockdown: a cookie minted for a different email must
    not authenticate even with a valid signature. Prevents a leaked
    SECRET_KEY from being replayed with a crafted email."""
    token = validator_cookie.mint(SECRET, OTHER_EMAIL, days=90)
    assert validator_cookie.parse(SECRET, token, EMAIL) is None


def test_parse_rejects_empty_or_missing_inputs():
    """Defensive: all-falsy inputs must return None, not raise."""
    assert validator_cookie.parse(SECRET, "", EMAIL) is None
    assert validator_cookie.parse(SECRET, "not-a-token", EMAIL) is None
    token = validator_cookie.mint(SECRET, EMAIL, days=90)
    assert validator_cookie.parse(SECRET, token, "") is None


def test_parse_rejects_tampered_token():
    """Flipping a character breaks the signature — the whole point of
    signing the token."""
    token = validator_cookie.mint(SECRET, EMAIL, days=90)
    # Flip the last character to break the signature
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert validator_cookie.parse(SECRET, tampered, EMAIL) is None


def test_parse_respects_max_age():
    """Expired token must be rejected even with a valid signature. We
    mint with a tiny 1-day window, then fabricate a past timestamp
    via itsdangerous's internal mechanism."""
    # Mint a token claiming days=1 but set the signed timestamp to
    # 2 days in the past. We do this by monkey-patching time.time
    # during mint so the signer records an old timestamp.
    original_time = time.time

    # 2 days before "now"
    class _TimeTravel:
        def __enter__(self):
            self.saved = original_time
            time.time = lambda: self.saved() - (2 * 86400)
            return self

        def __exit__(self, *exc):
            time.time = self.saved

    with _TimeTravel():
        old_token = validator_cookie.mint(SECRET, EMAIL, days=1)

    # Now it's "the future" relative to the token's mint time. Parse
    # should reject because the 1-day window is exhausted.
    assert validator_cookie.parse(SECRET, old_token, EMAIL) is None


def test_parse_email_case_insensitive():
    """Like login_required, match emails case-insensitively + trimmed.
    A cookie minted for `ME@Example.COM` must authenticate when
    AUTHORIZED_EMAIL is configured as `me@example.com`."""
    token = validator_cookie.mint(SECRET, "ME@Example.COM", days=90)
    assert validator_cookie.parse(SECRET, token, "me@example.com") == "ME@Example.COM"


# --- Integration tests via /api/auth/status ----------------------------------


def test_auth_status_accepts_valid_validator_cookie(app, client):
    """End-to-end: minted cookie sent as a real HTTP cookie authenticates
    /api/auth/status."""
    token = validator_cookie.mint(
        app.config["SECRET_KEY"], app.config["AUTHORIZED_EMAIL"], days=90
    )
    client.set_cookie(key=validator_cookie.COOKIE_NAME, value=token)
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["authenticated"] is True
    assert data["email"] == app.config["AUTHORIZED_EMAIL"]
    assert data.get("via") == "validator_cookie"


def test_auth_status_rejects_validator_cookie_with_wrong_email(app, client):
    """A validator cookie baked with a different email must not
    authenticate even if its signature is valid."""
    token = validator_cookie.mint(
        app.config["SECRET_KEY"], OTHER_EMAIL, days=90,
    )
    client.set_cookie(key=validator_cookie.COOKIE_NAME, value=token)
    resp = client.get("/api/auth/status")
    assert resp.status_code == 401


def test_auth_status_rejects_tampered_validator_cookie(app, client):
    """Flipping a character in the token must cause 401."""
    token = validator_cookie.mint(
        app.config["SECRET_KEY"], app.config["AUTHORIZED_EMAIL"], days=90
    )
    tampered = token[:-2] + "xx"
    client.set_cookie(key=validator_cookie.COOKIE_NAME, value=tampered)
    resp = client.get("/api/auth/status")
    assert resp.status_code == 401


def test_validator_cookie_does_not_authenticate_other_routes(app, client):
    """Critical security invariant: a valid validator cookie must NOT
    work on /api/tasks or any other protected route. Only
    /api/auth/status has the validator-cookie branch."""
    token = validator_cookie.mint(
        app.config["SECRET_KEY"], app.config["AUTHORIZED_EMAIL"], days=90
    )
    client.set_cookie(key=validator_cookie.COOKIE_NAME, value=token)
    # /api/tasks is protected by login_required which checks the Google
    # OAuth session, not the validator cookie. Without OAuth, it should
    # redirect to /login/google (302).
    resp = client.get("/api/tasks")
    assert resp.status_code == 302, (
        "validator cookie must not bypass login_required on other routes"
    )
    assert "/login/google" in resp.headers.get("Location", "")


# --- CLI command test --------------------------------------------------------


def test_mint_cli_command_prints_valid_token(app):
    """`flask mint-validator-cookie` prints a token to stdout that
    parses back to the configured AUTHORIZED_EMAIL."""
    runner = app.test_cli_runner()
    result = runner.invoke(args=["mint-validator-cookie", "--days", "7"])
    assert result.exit_code == 0, result.output
    # CLI echoes with nl=False so output is the token directly.
    token = result.output.strip()
    assert token, "expected a non-empty token on stdout"
    parsed = validator_cookie.parse(
        app.config["SECRET_KEY"], token, app.config["AUTHORIZED_EMAIL"]
    )
    assert parsed == app.config["AUTHORIZED_EMAIL"]


def test_mint_cli_command_fails_without_secret_key(app):
    """If SECRET_KEY is somehow unset, the mint command should exit
    non-zero with a clear message — not silently produce a token
    signed with empty-string key."""
    runner = app.test_cli_runner()
    app.config["SECRET_KEY"] = ""
    result = runner.invoke(args=["mint-validator-cookie"])
    assert result.exit_code != 0
    assert "SECRET_KEY" in result.output


def test_mint_cli_command_fails_without_email(app):
    """Need an email to bake into the cookie; error out clearly if
    neither --email nor AUTHORIZED_EMAIL is available."""
    runner = app.test_cli_runner()
    app.config["AUTHORIZED_EMAIL"] = ""
    result = runner.invoke(args=["mint-validator-cookie"])
    assert result.exit_code != 0
    assert "AUTHORIZED_EMAIL" in result.output or "email" in result.output.lower()


# --- Standalone script tests (scripts/mint_validator_cookie.py) --------------
#
# The standalone script exists for environments that can't import the
# full Flask app (e.g. missing psycopg). It must work using only env
# vars, with no Flask imports.


def test_standalone_mint_script_round_trips(monkeypatch, capsys, tmp_path):
    """Standalone script reads env vars, mints, and prints a token that
    parses back to the configured email."""
    import importlib.util
    import sys

    monkeypatch.setenv("SECRET_KEY", SECRET)
    monkeypatch.setenv("AUTHORIZED_EMAIL", EMAIL)
    monkeypatch.setattr(sys, "argv", ["mint_validator_cookie.py", "--days", "7"])

    spec = importlib.util.spec_from_file_location(
        "mint_validator_cookie",
        "scripts/mint_validator_cookie.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    exit_code = module.main()
    assert exit_code == 0

    captured = capsys.readouterr()
    token = captured.out
    assert token, "expected a token on stdout"
    assert "\n" not in token, "must not have trailing newline"

    parsed = validator_cookie.parse(SECRET, token, EMAIL)
    assert parsed == EMAIL


def test_standalone_mint_script_errors_without_secret(monkeypatch, capsys):
    """No SECRET_KEY in env → exit 2 with a helpful error message."""
    import importlib.util
    import sys

    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("AUTHORIZED_EMAIL", EMAIL)
    monkeypatch.setattr(sys, "argv", ["mint_validator_cookie.py"])

    spec = importlib.util.spec_from_file_location(
        "mint_validator_cookie",
        "scripts/mint_validator_cookie.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    exit_code = module.main()
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "SECRET_KEY" in captured.err
