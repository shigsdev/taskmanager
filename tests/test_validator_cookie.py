"""Tests for the long-lived validator cookie.

Covers (ADR-004 widened the scope 2026-04-17; #509 refreshed this file):
- pure mint/parse round-trip in validator_cookie.py
- signature + age enforcement, and the 90-day ceiling (#509)
- email binding (cannot replay a cookie with a different email)
- /api/auth/status, and READS (GET / HEAD) on every login_required route,
  the Siri voice-review queue included
- negative: no mutation anywhere — POST / PATCH / PUT / DELETE on routes
  that exist, the voice-review actions included — and no key rotation
  survival, no confusion with the voice-action token
- the audit log line, the CLI and the standalone mint script
"""
from __future__ import annotations

import time
import uuid

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
    """Flipping a character in the signature breaks verification —
    the whole point of signing the token. Tamper the signature
    portion specifically (after the last `.`) so we know we're
    affecting bytes the signature actually depends on."""
    token = validator_cookie.mint(SECRET, EMAIL, days=90)
    # Flip a char in the middle of the signature segment — guaranteed
    # to alter the HMAC bytes regardless of mint randomness.
    head, _, sig = token.rpartition(".")
    assert sig, "minted token should have a signature segment"
    mid = len(sig) // 2
    flipped_char = "X" if sig[mid] != "X" else "Y"
    tampered = f"{head}.{sig[:mid]}{flipped_char}{sig[mid + 1:]}"
    assert tampered != token, "tamper should produce a different string"
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


def test_validator_cookie_authenticates_get_routes(app, client):
    """The validator cookie authenticates safe HTTP methods on
    login_required routes — that's how the prod Playwright smoke
    suite drives page-rendering tests without OAuth."""
    token = validator_cookie.mint(
        app.config["SECRET_KEY"], app.config["AUTHORIZED_EMAIL"], days=90
    )
    client.set_cookie(key=validator_cookie.COOKIE_NAME, value=token)

    # GET /api/tasks: returns 200 with a JSON list
    resp = client.get("/api/tasks")
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.data!r}"
    assert isinstance(resp.get_json(), list)


def test_validator_cookie_authenticates_get_pages(app, client):
    """Page renders also work — that's the whole point of broadening
    the cookie scope (so prod Playwright can verify HTML renders)."""
    token = validator_cookie.mint(
        app.config["SECRET_KEY"], app.config["AUTHORIZED_EMAIL"], days=90
    )
    client.set_cookie(key=validator_cookie.COOKIE_NAME, value=token)
    for path in ("/", "/goals", "/settings"):
        resp = client.get(path)
        assert resp.status_code == 200, (
            f"GET {path} returned {resp.status_code}; expected 200"
        )


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/tasks"),
    ("PATCH", "/api/tasks/{id}"),
    ("DELETE", "/api/tasks/{id}"),
    ("PUT", "/api/reflection/draft"),
    ("POST", "/api/voice-review/{id}/complete"),
    ("POST", "/api/voice-review/{id}/move"),
    ("POST", "/api/voice-review/{id}/cancel"),
    ("POST", "/api/voice-review/{id}/answer"),
    ("POST", "/api/voice-review/tasks"),
])
def test_validator_cookie_does_not_authenticate_mutations(app, client, method, path):
    """CRITICAL SECURITY INVARIANT: validator cookie must NOT
    authenticate mutation methods. A leaked cookie can only read,
    never modify. login_required falls through to OAuth on these
    methods and OAuth fails (no session) → 401 JSON for /api/* paths
    (changed from 302 redirect on 2026-05-07; see TestAuthLockdown).
    """
    token = validator_cookie.mint(
        app.config["SECRET_KEY"], app.config["AUTHORIZED_EMAIL"], days=90
    )
    client.set_cookie(key=validator_cookie.COOKIE_NAME, value=token)
    # #509: every path here exists for its method, so a 405 can't stand
    # in for a refusal (PATCH/DELETE/PUT on /api/tasks used to 405
    # before auth ran, proving nothing).
    url = path.format(id=uuid.uuid4())
    resp = client.open(url, method=method, json={"title": "x", "text": "done"})
    assert resp.status_code == 401, (
        f"{method} {url} returned {resp.status_code}; "
        "validator cookie must not authenticate mutations"
    )


# --- CLI command test --------------------------------------------------------


def test_mint_cli_command_prints_valid_token(app):
    """`flask mint-validator-cookie` prints a token to stdout that
    parses back to the configured AUTHORIZED_EMAIL."""
    runner = app.test_cli_runner()
    result = runner.invoke(args=["mint-validator-cookie", "--days", "7"])
    assert result.exit_code == 0, result.output
    # CLI echoes with nl=False so output is the token directly — it is
    # piped into ~/.taskmanager-session-cookie, so no newline (#509: this
    # used to .strip() and couldn't have noticed one).
    token = result.output
    assert "\n" not in token
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


# --- #509: what the 2026-10-19 refresh found untested --------------------------


def _cookie(app, client, *, secret=None, days=90):
    token = validator_cookie.mint(
        secret or app.config["SECRET_KEY"], app.config["AUTHORIZED_EMAIL"], days=days,
    )
    client.set_cookie(key=validator_cookie.COOKIE_NAME, value=token)
    return token


def _declared_days(token: str) -> int:
    return validator_cookie._serializer(SECRET).loads(token)["days"]


def _load_mint_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "mint_validator_cookie", "scripts/mint_validator_cookie.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cookie_reads_the_voice_review_queue(app, client):
    """/api/voice-review/* falls back to login_required, so the read-only
    cookie can read the Siri queue (GET) — and nothing else there."""
    _cookie(app, client)
    assert client.get("/api/voice-review/queue").status_code == 200


def test_head_is_a_read(app, client):
    assert client.head("/api/tasks").status_code == 401
    _cookie(app, client)
    assert client.head("/api/tasks").status_code == 200


def test_rotating_secret_key_locks_the_cookie_out_end_to_end(app, client):
    _cookie(app, client, secret="the-key-before-rotation")
    assert client.get("/api/tasks").status_code == 401
    assert client.get("/api/auth/status").status_code == 401


def test_voice_action_token_is_not_a_validator_cookie(app, client):
    """Distinct salts: the Siri bearer token set as the cookie reads nothing."""
    import voice_action_token

    token = voice_action_token.mint(
        app.config["SECRET_KEY"], app.config["AUTHORIZED_EMAIL"], days=90,
    )
    assert validator_cookie.parse(
        app.config["SECRET_KEY"], token, app.config["AUTHORIZED_EMAIL"]) is None
    client.set_cookie(key=validator_cookie.COOKIE_NAME, value=token)
    assert client.get("/api/tasks").status_code == 401


def test_validator_cookie_is_not_a_voice_bearer(app, client):
    token = validator_cookie.mint(
        app.config["SECRET_KEY"], app.config["AUTHORIZED_EMAIL"], days=90,
    )
    resp = client.post(
        f"/api/voice-review/{uuid.uuid4()}/complete",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


def test_audit_line_names_the_request_but_not_the_email(app, client, caplog):
    """Every cookie-served read leaves a trace; CLAUDE.md: never log an
    email address (#509 — the line used to end "as <email>")."""
    import logging

    _cookie(app, client)
    with caplog.at_level(logging.INFO, logger="taskmanager.auth"):
        client.get("/api/tasks")
    lines = [r.getMessage() for r in caplog.records if r.name == "taskmanager.auth"]
    assert "validator_cookie served GET /api/tasks" in lines
    assert not any("@" in ln for ln in lines)


# --- The 90-day ceiling (CLAUDE.md threat model: "90-day expiry") -------------


def test_default_lifetime_is_ninety_days(app, monkeypatch, capsys):
    import sys

    result = app.test_cli_runner().invoke(args=["mint-validator-cookie"])
    assert result.exit_code == 0
    app_token = result.output
    monkeypatch.setenv("SECRET_KEY", app.config["SECRET_KEY"])
    monkeypatch.setenv("AUTHORIZED_EMAIL", EMAIL)
    monkeypatch.setattr(sys, "argv", ["mint_validator_cookie.py"])
    assert _load_mint_script().main() == 0
    script_token = capsys.readouterr().out
    assert _declared_days(app_token) == _declared_days(script_token) == 90


def test_ninety_is_the_most_mint_will_make():
    assert validator_cookie.MAX_DAYS == 90
    validator_cookie.mint(SECRET, EMAIL, days=90)
    with pytest.raises(ValueError, match="90"):
        validator_cookie.mint(SECRET, EMAIL, days=91)


def test_a_longer_cookie_minted_before_the_cap_is_refused():
    """A token that claims more than 90 days (an old 3650-day mint, or
    one signed by hand) is refused at parse time too."""
    long_lived = validator_cookie._serializer(SECRET).dumps(
        {"email": EMAIL, "days": 3650})
    assert validator_cookie.parse(SECRET, long_lived, EMAIL) is None


def test_eighty_nine_days_old_parses_and_ninety_one_does_not():
    original = time.time
    try:
        time.time = lambda: original() - 89 * 86400
        young = validator_cookie.mint(SECRET, EMAIL, days=90)
        time.time = lambda: original() - 91 * 86400
        old = validator_cookie.mint(SECRET, EMAIL, days=90)
    finally:
        time.time = original
    assert validator_cookie.parse(SECRET, young, EMAIL) == EMAIL
    assert validator_cookie.parse(SECRET, old, EMAIL) is None


def test_cli_refuses_more_than_ninety_days(app):
    result = app.test_cli_runner().invoke(
        args=["mint-validator-cookie", "--days", "91"])
    assert result.exit_code != 0
    assert "90" in result.output


@pytest.mark.parametrize("days", ["0", "91"])
def test_script_refuses_days_outside_one_to_ninety(monkeypatch, capsys, days):
    import sys

    monkeypatch.setenv("SECRET_KEY", SECRET)
    monkeypatch.setenv("AUTHORIZED_EMAIL", EMAIL)
    monkeypatch.setattr(sys, "argv", ["mint_validator_cookie.py", "--days", days])
    assert _load_mint_script().main() == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert "--days" in out.err


def test_script_needs_an_email(monkeypatch, capsys):
    import sys

    monkeypatch.setenv("SECRET_KEY", SECRET)
    monkeypatch.delenv("AUTHORIZED_EMAIL", raising=False)
    monkeypatch.setattr(sys, "argv", ["mint_validator_cookie.py"])
    assert _load_mint_script().main() == 2
    assert "AUTHORIZED_EMAIL" in capsys.readouterr().err
