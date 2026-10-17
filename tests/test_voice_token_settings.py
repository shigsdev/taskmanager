"""#499: make / list / revoke the Siri voice-action token on /settings.

The load-bearing property (ADR-042, amending ADR-034): minting a mutation
credential needs a REAL Google sign-in. The read-only validator cookie and
the voice-action bearer itself must both be refused on mint and revoke.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest

import rate_limit
import validator_cookie
import voice_action_token
import voice_token_service
from models import AppSetting
from models import db as _db

SECRET = "test-secret"          # matches conftest app fixture
EMAIL = "me@example.com"        # matches conftest AUTHORIZED_EMAIL
URL = "/api/settings/voice-tokens"


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _mint(client, **body):
    return client.post(URL, json=body or {})


def _denylist(app) -> list[str]:
    with app.app_context():
        row = AppSetting.query.filter_by(key=voice_action_token.REVOKED_JTIS_KEY).one_or_none()
        return json.loads(row.value) if row else []


class TestMint:
    def test_oauth_mints_a_working_token(self, app, authed_client):
        r = _mint(authed_client)
        assert r.status_code == 201
        body = r.get_json()
        assert set(body) == {"token", "jti", "expires"}
        assert voice_token_service.is_valid_jti(body["jti"])
        assert r.headers["Cache-Control"] == "no-store"
        # The token is real: the voice-review queue accepts it.
        q = authed_client.application.test_client().get(
            "/api/voice-review/queue", headers=_bearer(body["token"])
        )
        assert q.status_code == 200

    def test_default_lifetime_is_90_days(self, authed_client):
        body = _mint(authed_client).get_json()
        expires = datetime.fromisoformat(body["expires"])
        delta = expires - datetime.now(UTC)
        assert timedelta(days=89, hours=23) < delta <= timedelta(days=90)

    def test_days_is_honoured(self, authed_client):
        body = _mint(authed_client, days=30).get_json()
        delta = datetime.fromisoformat(body["expires"]) - datetime.now(UTC)
        assert timedelta(days=29, hours=23) < delta <= timedelta(days=30)

    @pytest.mark.parametrize("bad", [0, -5, 366, 3650, "x", 1.5, True])
    def test_bad_days_is_422(self, authed_client, bad):
        r = _mint(authed_client, days=bad)
        assert r.status_code == 422
        assert r.get_json()["field"] == "days"

    def test_no_auth_is_401(self, client):
        assert _mint(client).status_code == 401

    def test_validator_cookie_cannot_mint(self, app, client):
        cookie = validator_cookie.mint(secret_key=SECRET, email=EMAIL, days=1)
        client.set_cookie(key=validator_cookie.COOKIE_NAME, value=cookie)
        assert _mint(client).status_code == 401
        with app.app_context():
            assert not AppSetting.query.filter(
                AppSetting.key.startswith(voice_token_service.ROW_PREFIX)
            ).count()

    def test_voice_bearer_cannot_mint(self, client):
        tok = voice_action_token.mint(secret_key=SECRET, email=EMAIL, days=1)
        r = client.post(URL, json={}, headers=_bearer(tok))
        assert r.status_code == 401

    def test_token_is_never_stored(self, app, authed_client):
        body = _mint(authed_client).get_json()
        with app.app_context():
            for row in AppSetting.query.all():
                assert body["token"] not in row.value

    def test_token_is_never_logged(self, authed_client, caplog):
        caplog.set_level(logging.DEBUG)
        body = _mint(authed_client).get_json()
        authed_client.get(URL)
        for rec in caplog.records:
            assert body["token"] not in rec.getMessage()
            assert body["token"] not in str(rec.args)

    def test_sixth_mint_in_an_hour_is_429(self, app, authed_client):
        rate_limit.limiter.enabled = True
        app.config["RATELIMIT_ENABLED"] = True
        rate_limit.limiter.init_app(app)
        rate_limit.limiter.reset()
        try:
            for i in range(5):
                assert _mint(authed_client).status_code == 201, i
            r = _mint(authed_client)
            assert r.status_code == 429
            assert r.get_json()["error"] == rate_limit.VOICE_MINT_LIMIT_MESSAGE
        finally:
            rate_limit.limiter.enabled = False
            rate_limit.limiter.reset()


class TestList:
    def test_lists_made_tokens_without_the_token(self, authed_client):
        made = _mint(authed_client).get_json()
        r = authed_client.get(URL)
        assert r.status_code == 200
        tokens = r.get_json()["tokens"]
        assert [t["jti"] for t in tokens] == [made["jti"]]
        assert set(tokens[0]) == {"jti", "minted", "expires", "revoked"}
        assert made["token"] not in r.get_data(as_text=True)

    def test_newest_first(self, authed_client, app):
        with app.app_context():
            for jti, minted in (("a" * 16, "2026-10-01T00:00:00+00:00"),
                                ("b" * 16, "2026-10-10T00:00:00+00:00")):
                _db.session.add(AppSetting(
                    key=voice_token_service.ROW_PREFIX + jti,
                    value=json.dumps({"minted": minted,
                                      "expires": "2099-01-01T00:00:00+00:00",
                                      "revoked": None}),
                ))
            _db.session.commit()
        jtis = [t["jti"] for t in authed_client.get(URL).get_json()["tokens"]]
        assert jtis == ["b" * 16, "a" * 16]

    def test_validator_cookie_may_read_the_list(self, client):
        cookie = validator_cookie.mint(secret_key=SECRET, email=EMAIL, days=1)
        client.set_cookie(key=validator_cookie.COOKIE_NAME, value=cookie)
        assert client.get(URL).status_code == 200

    def test_voice_bearer_cannot_read_the_list(self, client):
        tok = voice_action_token.mint(secret_key=SECRET, email=EMAIL, days=1)
        assert client.get(URL, headers=_bearer(tok)).status_code == 401

    def test_expired_rows_are_pruned_with_their_denylist_entry(self, app, authed_client):
        old = "c" * 16
        past = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        with app.app_context():
            _db.session.add(AppSetting(
                key=voice_token_service.ROW_PREFIX + old,
                value=json.dumps({"minted": past, "expires": past, "revoked": past}),
            ))
            _db.session.add(AppSetting(
                key=voice_action_token.REVOKED_JTIS_KEY,
                value=json.dumps([old, "cli-made-id"]),
            ))
            _db.session.commit()
        assert authed_client.get(URL).get_json()["tokens"] == []
        # The CLI-made id has no row: it stays revoked.
        assert _denylist(app) == ["cli-made-id"]
        with app.app_context():
            assert AppSetting.query.filter_by(
                key=voice_token_service.ROW_PREFIX + old
            ).one_or_none() is None

    def test_just_expired_row_is_kept_a_day(self, app, authed_client):
        jti = "d" * 16
        recent = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        with app.app_context():
            _db.session.add(AppSetting(
                key=voice_token_service.ROW_PREFIX + jti,
                value=json.dumps({"minted": recent, "expires": recent, "revoked": None}),
            ))
            _db.session.commit()
        assert [t["jti"] for t in authed_client.get(URL).get_json()["tokens"]] == [jti]


class TestRevoke:
    def test_revoke_lands_in_denylist_and_the_token_is_refused(self, app, authed_client):
        made = _mint(authed_client).get_json()
        other = app.test_client()
        assert other.get("/api/voice-review/queue",
                         headers=_bearer(made["token"])).status_code == 200

        r = authed_client.post(f"{URL}/{made['jti']}/revoke")
        assert r.status_code == 200
        assert r.get_json() == {"ok": True, "jti": made["jti"], "listed": True}
        assert made["jti"] in _denylist(app)
        assert other.get("/api/voice-review/queue",
                         headers=_bearer(made["token"])).status_code == 401
        row = authed_client.get(URL).get_json()["tokens"][0]
        assert row["revoked"]

    def test_revoke_by_id_for_a_cli_token(self, app, authed_client):
        jti = voice_action_token.new_jti()
        tok = voice_action_token.mint(secret_key=SECRET, email=EMAIL, days=5, jti=jti)
        r = authed_client.post(f"{URL}/{jti}/revoke")
        assert r.get_json() == {"ok": True, "jti": jti, "listed": False}
        assert app.test_client().get(
            "/api/voice-review/queue", headers=_bearer(tok)
        ).status_code == 401

    def test_revoke_is_idempotent(self, app, authed_client):
        made = _mint(authed_client).get_json()
        authed_client.post(f"{URL}/{made['jti']}/revoke")
        first = authed_client.get(URL).get_json()["tokens"][0]["revoked"]
        assert authed_client.post(f"{URL}/{made['jti']}/revoke").status_code == 200
        assert _denylist(app).count(made["jti"]) == 1
        assert authed_client.get(URL).get_json()["tokens"][0]["revoked"] == first

    @pytest.mark.parametrize("bad", ["short", "G" * 16, "a" * 17, "ABCDEF0123456789"])
    def test_bad_jti_is_422(self, authed_client, bad):
        r = authed_client.post(f"{URL}/{bad}/revoke")
        assert r.status_code == 422
        assert r.get_json()["field"] == "jti"

    def test_validator_cookie_cannot_revoke(self, app, client):
        cookie = validator_cookie.mint(secret_key=SECRET, email=EMAIL, days=1)
        client.set_cookie(key=validator_cookie.COOKIE_NAME, value=cookie)
        assert client.post(f"{URL}/{'e' * 16}/revoke").status_code == 401
        assert _denylist(app) == []

    def test_voice_bearer_cannot_revoke(self, app, client):
        tok = voice_action_token.mint(secret_key=SECRET, email=EMAIL, days=1)
        r = client.post(f"{URL}/{'e' * 16}/revoke", headers=_bearer(tok))
        assert r.status_code == 401
        assert _denylist(app) == []

    def test_full_denylist_refuses_instead_of_truncating(self, app, authed_client):
        full = [f"{i:016x}" for i in range(26)]  # 26 * 20 chars ≈ 520 > 500
        while len(json.dumps(full)) > 500:
            full.pop()
        with app.app_context():
            _db.session.add(AppSetting(
                key=voice_action_token.REVOKED_JTIS_KEY, value=json.dumps(full),
            ))
            _db.session.commit()
        r = authed_client.post(f"{URL}/{'f' * 16}/revoke")
        assert r.status_code == 422
        assert "SECRET_KEY" in r.get_json()["error"]
        assert _denylist(app) == full  # unchanged, still valid JSON


class TestCliRevokeSharesTheWriter:
    def test_cli_refuses_a_full_denylist(self, app):
        full = [f"{i:016x}" for i in range(26)]
        while len(json.dumps(full)) > 500:
            full.pop()
        with app.app_context():
            _db.session.add(AppSetting(
                key=voice_action_token.REVOKED_JTIS_KEY, value=json.dumps(full),
            ))
            _db.session.commit()
        result = app.test_cli_runner().invoke(
            args=["revoke-voice-action-token", "f" * 16]
        )
        assert result.exit_code != 0
        assert "SECRET_KEY" in result.output
        assert _denylist(app) == full


class TestDenylistWritesLockTheRow:
    """A revoke and a prune racing must not lose a revocation: every
    read-modify-write of the denylist reads it FOR UPDATE (Postgres)."""

    def _spy(self, monkeypatch):
        calls = []
        real = voice_token_service._setting

        def spy(key, *, lock=False):
            if key == voice_action_token.REVOKED_JTIS_KEY:
                calls.append(lock)
            return real(key, lock=lock)

        monkeypatch.setattr(voice_token_service, "_setting", spy)
        return calls

    def test_revoke_reads_the_denylist_locked(self, app, authed_client, monkeypatch):
        calls = self._spy(monkeypatch)
        assert authed_client.post(f"{URL}/{'a' * 16}/revoke").status_code == 200
        assert calls and calls[0] is True

    def test_prune_reads_the_denylist_locked(self, app, authed_client, monkeypatch):
        old = "c" * 16
        past = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        with app.app_context():
            _db.session.add(AppSetting(
                key=voice_token_service.ROW_PREFIX + old,
                value=json.dumps({"minted": past, "expires": past, "revoked": past}),
            ))
            _db.session.add(AppSetting(
                key=voice_action_token.REVOKED_JTIS_KEY, value=json.dumps([old]),
            ))
            _db.session.commit()
        calls = self._spy(monkeypatch)
        authed_client.get(URL)
        assert calls and calls[0] is True
        assert _denylist(app) == []
