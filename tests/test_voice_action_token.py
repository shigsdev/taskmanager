"""Tests for the scoped voice-review action token (#297 / ADR-034).

Two layers:
  1. Unit tests on ``voice_action_token.parse`` (signature / expiry /
     email / revocation).
  2. The **scope-rejection matrix** — the load-bearing security property
     from ADR-034: a valid voice token authenticates ONLY the four
     ``/api/voice-review/*`` routes and is rejected (401) on every other
     route. If any "rejected" row ever returns 2xx, the central security
     guarantee is broken.
"""
from __future__ import annotations

import json
import time
import uuid

import pytest

import voice_action_token
from models import AppSetting, Task, TaskStatus, TaskType, Tier
from models import db as _db

SECRET = "test-secret"          # matches conftest app fixture
EMAIL = "me@example.com"        # matches conftest AUTHORIZED_EMAIL


def _token(days: int = 90, jti: str | None = None, email: str = EMAIL) -> str:
    return voice_action_token.mint(secret_key=SECRET, email=email, days=days, jti=jti)


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_task(app, *, tier=Tier.TODAY, due_date=None) -> str:
    with app.app_context():
        t = Task(title="Drive-review task", type=TaskType.WORK, tier=tier)
        if due_date is not None:
            t.due_date = due_date
        _db.session.add(t)
        _db.session.commit()
        return str(t.id)


# --------------------------------------------------------------------------
# 1. Token module unit tests
# --------------------------------------------------------------------------
class TestParse:
    def test_round_trip(self):
        assert voice_action_token.parse(SECRET, _token(), EMAIL) == EMAIL

    def test_rejects_wrong_secret(self):
        assert voice_action_token.parse("nope", _token(), EMAIL) is None

    def test_rejects_wrong_email(self):
        tok = _token(email="intruder@example.com")
        assert voice_action_token.parse(SECRET, tok, EMAIL) is None

    def test_email_case_insensitive(self):
        tok = _token(email="ME@Example.COM")
        assert voice_action_token.parse(SECRET, tok, EMAIL) == "ME@Example.COM"

    def test_rejects_empty_and_garbage(self):
        assert voice_action_token.parse(SECRET, "", EMAIL) is None
        assert voice_action_token.parse(SECRET, "not-a-token", EMAIL) is None
        assert voice_action_token.parse(SECRET, _token(), "") is None

    def test_mint_rejects_nonpositive_days(self):
        with pytest.raises(ValueError):
            voice_action_token.mint(SECRET, EMAIL, days=0)

    def test_rejects_expired(self):
        original_time = time.time

        class _TimeTravel:
            def __enter__(self):
                self.saved = original_time
                time.time = lambda: self.saved() - (2 * 86400)
                return self

            def __exit__(self, *exc):
                time.time = self.saved

        with _TimeTravel():
            old = voice_action_token.mint(SECRET, EMAIL, days=1)
        assert voice_action_token.parse(SECRET, old, EMAIL) is None

    def test_revoked_jti_rejected(self):
        tok = _token(jti="deadbeef00")
        assert voice_action_token.parse(SECRET, tok, EMAIL, revoked_jtis={"deadbeef00"}) is None
        # a different revoked id doesn't affect this token
        assert voice_action_token.parse(SECRET, tok, EMAIL, revoked_jtis={"other"}) == EMAIL

    def test_distinct_salt_from_validator_cookie(self):
        """A validator-cookie token must NOT parse as a voice token (and
        vice versa) even under the same SECRET_KEY — distinct salts."""
        import validator_cookie

        vtok = validator_cookie.mint(SECRET, EMAIL, days=90)
        assert voice_action_token.parse(SECRET, vtok, EMAIL) is None


# --------------------------------------------------------------------------
# 2. Endpoint behaviour — the token authenticates the voice-review routes
# --------------------------------------------------------------------------
class TestVoiceReviewRoutes:
    def test_queue_buckets_overdue_today_tomorrow(self, app, client):
        from datetime import timedelta

        from utils import local_today_date

        yesterday = local_today_date() - timedelta(days=1)
        _make_task(app, tier=Tier.BACKLOG, due_date=yesterday)  # overdue
        _make_task(app, tier=Tier.TODAY)                        # today
        _make_task(app, tier=Tier.TOMORROW)                     # tomorrow
        _make_task(app, tier=Tier.FREEZER)                      # excluded

        r = client.get("/api/voice-review/queue", headers=_hdr(_token()))
        assert r.status_code == 200
        body = r.get_json()
        assert body["counts"] == {"overdue": 1, "today": 1, "tomorrow": 1}
        # overdue first
        assert body["items"][0]["bucket"] == "overdue"
        assert [i["bucket"] for i in body["items"]] == ["overdue", "today", "tomorrow"]

    def test_complete(self, app, client):
        tid = _make_task(app, tier=Tier.TODAY)
        r = client.post(f"/api/voice-review/{tid}/complete", headers=_hdr(_token()))
        assert r.status_code == 200
        with app.app_context():
            assert _db.session.get(Task, uuid.UUID(tid)).status == TaskStatus.ARCHIVED

    def test_move_whitelisted_tier(self, app, client):
        tid = _make_task(app, tier=Tier.TODAY)
        r = client.post(
            f"/api/voice-review/{tid}/move",
            json={"tier": "backlog"},
            headers=_hdr(_token()),
        )
        assert r.status_code == 200
        with app.app_context():
            assert _db.session.get(Task, uuid.UUID(tid)).tier == Tier.BACKLOG

    @pytest.mark.parametrize("bad_tier", ["this_week", "freezer", "inbox", "bogus", None])
    def test_move_rejects_non_whitelisted_tier(self, app, client, bad_tier):
        tid = _make_task(app, tier=Tier.TODAY)
        r = client.post(
            f"/api/voice-review/{tid}/move",
            json={"tier": bad_tier},
            headers=_hdr(_token()),
        )
        assert r.status_code == 422
        with app.app_context():  # unchanged
            assert _db.session.get(Task, uuid.UUID(tid)).tier == Tier.TODAY

    def test_cancel(self, app, client):
        tid = _make_task(app, tier=Tier.TODAY)
        r = client.post(f"/api/voice-review/{tid}/cancel", headers=_hdr(_token()))
        assert r.status_code == 200
        with app.app_context():
            assert _db.session.get(Task, uuid.UUID(tid)).status == TaskStatus.CANCELLED

    def test_invalid_token_rejected_401(self, app, client):
        r = client.get("/api/voice-review/queue", headers=_hdr("garbage.token"))
        assert r.status_code == 401

    def test_no_token_rejected(self, client):
        r = client.get("/api/voice-review/queue")
        # no bearer, no session → falls through to login_required → 401
        assert r.status_code == 401

    def test_revoked_token_rejected_at_endpoint(self, app, client):
        tok = _token(jti="revoke-me-01")
        with app.app_context():
            _db.session.add(
                AppSetting(
                    key=voice_action_token.REVOKED_JTIS_KEY,
                    value=json.dumps(["revoke-me-01"]),
                )
            )
            _db.session.commit()
        r = client.get("/api/voice-review/queue", headers=_hdr(tok))
        assert r.status_code == 401


# --------------------------------------------------------------------------
# 3. Scope-rejection matrix — THE load-bearing security property
# --------------------------------------------------------------------------
class TestScopeRejectionMatrix:
    """A valid voice token must be REJECTED (not 2xx) on every route
    outside /api/voice-review/*. These routes use @login_required, which
    never inspects the bearer token, so a token-only request has no
    session → 401."""

    def _assert_rejected(self, resp):
        assert resp.status_code in (401, 403), (
            f"voice token must NOT authenticate this route; got {resp.status_code}"
        )

    def test_cannot_list_tasks(self, app, client):
        self._assert_rejected(client.get("/api/tasks", headers=_hdr(_token())))

    def test_cannot_create_task(self, app, client):
        self._assert_rejected(
            client.post("/api/tasks", json={"title": "x"}, headers=_hdr(_token()))
        )

    def test_cannot_patch_task_directly(self, app, client):
        tid = _make_task(app)
        self._assert_rejected(
            client.patch(
                f"/api/tasks/{tid}", json={"title": "hacked"}, headers=_hdr(_token())
            )
        )

    def test_cannot_delete_task(self, app, client):
        tid = _make_task(app)
        self._assert_rejected(
            client.delete(f"/api/tasks/{tid}", headers=_hdr(_token()))
        )

    def test_cannot_use_general_complete_route(self, app, client):
        tid = _make_task(app)
        self._assert_rejected(
            client.post(f"/api/tasks/{tid}/complete", headers=_hdr(_token()))
        )

    def test_cannot_bulk_edit(self, app, client):
        self._assert_rejected(
            client.patch("/api/tasks/bulk", json={}, headers=_hdr(_token()))
        )

    def test_cannot_read_goals(self, app, client):
        # other read-state: a bearer token isn't a validator cookie, so
        # even GET must be rejected.
        self._assert_rejected(client.get("/api/goals", headers=_hdr(_token())))

    def test_cannot_read_projects(self, app, client):
        self._assert_rejected(client.get("/api/projects", headers=_hdr(_token())))

    def test_cannot_export(self, app, client):
        self._assert_rejected(client.get("/api/export", headers=_hdr(_token())))


# --- CLI commands: mint / revoke (ADR-034) ----------------------------------
# Covers the operator tooling in app.py (mint-/revoke-voice-action-token) —
# shipped in #297 without tests, which dropped app.py coverage below baseline.


class TestVoiceActionTokenCLI:
    def test_mint_prints_token(self, app):
        runner = app.test_cli_runner()
        result = runner.invoke(args=["mint-voice-action-token", "--days", "30"])
        assert result.exit_code == 0, result.output
        # Token is echoed to stdout (jti goes to stderr); grab the first
        # non-empty line and confirm it parses back to the authorized email.
        token = result.output.strip().splitlines()[0].strip()
        assert token
        assert voice_action_token.parse(
            app.config["SECRET_KEY"], token, app.config["AUTHORIZED_EMAIL"]
        ) == app.config["AUTHORIZED_EMAIL"]

    def test_mint_fails_without_secret_key(self, app):
        runner = app.test_cli_runner()
        app.config["SECRET_KEY"] = ""
        result = runner.invoke(args=["mint-voice-action-token"])
        assert result.exit_code != 0
        assert "SECRET_KEY" in result.output

    def test_mint_fails_without_email(self, app):
        runner = app.test_cli_runner()
        app.config["AUTHORIZED_EMAIL"] = ""
        result = runner.invoke(args=["mint-voice-action-token"])
        assert result.exit_code != 0
        assert "AUTHORIZED_EMAIL" in result.output

    def test_revoke_new_jti_adds_to_denylist(self, app):
        runner = app.test_cli_runner()
        result = runner.invoke(args=["revoke-voice-action-token", "jti-new-1"])
        assert result.exit_code == 0, result.output
        assert "Revoked jti jti-new-1" in result.output
        with app.app_context():
            row = AppSetting.query.filter_by(
                key=voice_action_token.REVOKED_JTIS_KEY
            ).one_or_none()
            assert row is not None
            assert "jti-new-1" in json.loads(row.value)

    def test_revoke_appends_to_existing_denylist(self, app):
        runner = app.test_cli_runner()
        runner.invoke(args=["revoke-voice-action-token", "jti-A"])
        result = runner.invoke(args=["revoke-voice-action-token", "jti-B"])
        assert result.exit_code == 0, result.output
        assert "Revoked jti jti-B" in result.output
        assert "2 total revoked" in result.output

    def test_revoke_is_idempotent(self, app):
        runner = app.test_cli_runner()
        runner.invoke(args=["revoke-voice-action-token", "dup-jti"])
        result = runner.invoke(args=["revoke-voice-action-token", "dup-jti"])
        assert result.exit_code == 0, result.output
        assert "already revoked" in result.output
