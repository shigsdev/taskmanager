"""#324: resumable reflection drafts — reflecting across several sittings.

The user reflects in pieces: a thought on the phone in the morning, more
at the laptop that night. Before this, in-progress text lived only in the
browser textarea and was destroyed silently by a reload, a closed tab, or
iOS evicting the PWA — and nothing followed the user between devices.

The draft is deliberately SERVER state (a `reflections` row with
`is_draft=True`) rather than localStorage, because localStorage cannot
cross devices. These tests pin the properties that make that trustworthy:
it persists, it upserts rather than accretes, it never counts as history,
and submitting leaves exactly one copy of the text.
"""
from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import func, select

import auth
from models import Reflection, db


def _bypass_auth(monkeypatch):
    monkeypatch.setattr(
        auth, "get_current_user_email", lambda: "me@example.com"
    )


_NO_ANALYSIS = {
    "explicit": [], "suggested": [], "ai_cost_usd": 0.0, "snapshot": {},
}


class TestDraftLifecycle:
    def test_get_draft_is_null_when_none_open(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        resp = client.get("/api/reflection/draft")
        assert resp.status_code == 200
        assert resp.get_json()["draft"] is None

    def test_put_creates_then_updates_a_single_draft(
        self, app, client, monkeypatch,
    ):
        _bypass_auth(monkeypatch)
        r1 = client.put("/api/reflection/draft", json={"text": "first thought"})
        assert r1.status_code == 200
        assert r1.get_json()["draft"]["transcript"] == "first thought"

        r2 = client.put(
            "/api/reflection/draft",
            json={"text": "first thought. and a second one"},
        )
        assert r2.status_code == 200
        assert r2.get_json()["draft"]["transcript"] == (
            "first thought. and a second one"
        )
        # Upsert, not append — autosave must not accrete a row per
        # keystroke-burst.
        with app.app_context():
            assert db.session.scalar(
                select(func.count(Reflection.id)).where(
                    Reflection.is_draft.is_(True)
                )
            ) == 1

    def test_draft_survives_a_fresh_client_ie_another_device(
        self, app, client, monkeypatch,
    ):
        """The load-bearing property. A brand-new client shares no browser
        storage with the first — if the draft comes back, it is genuinely
        server-side and will follow the user phone -> laptop."""
        _bypass_auth(monkeypatch)
        client.put("/api/reflection/draft", json={"text": "written on my phone"})

        fresh = app.test_client()
        resp = fresh.get("/api/reflection/draft")
        assert resp.status_code == 200
        assert resp.get_json()["draft"]["transcript"] == "written on my phone"

    def test_draft_accumulates_across_several_sittings(
        self, app, client, monkeypatch,
    ):
        """The actual use case: add to the same reflection over days."""
        _bypass_auth(monkeypatch)
        client.put("/api/reflection/draft", json={"text": "Mon: shipped X."})
        client.put(
            "/api/reflection/draft",
            json={"text": "Mon: shipped X. Wed: stuck on Y."},
        )
        body = client.put(
            "/api/reflection/draft",
            json={"text": "Mon: shipped X. Wed: stuck on Y. Fri: unblocked."},
        ).get_json()["draft"]
        assert body["transcript"] == (
            "Mon: shipped X. Wed: stuck on Y. Fri: unblocked."
        )
        with app.app_context():
            assert db.session.scalar(
                select(func.count(Reflection.id))
            ) == 1

    def test_empty_text_is_accepted(self, app, client, monkeypatch):
        """Clearing the box is a real state. Rejecting it would strand the
        client's autosave loop mid-edit."""
        _bypass_auth(monkeypatch)
        client.put("/api/reflection/draft", json={"text": "something"})
        resp = client.put("/api/reflection/draft", json={"text": ""})
        assert resp.status_code == 200
        assert resp.get_json()["draft"]["transcript"] == ""

    def test_delete_discards_and_is_idempotent(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        client.put("/api/reflection/draft", json={"text": "scrap this"})
        assert client.delete("/api/reflection/draft").status_code == 204
        assert client.get("/api/reflection/draft").get_json()["draft"] is None
        # The client may fire DELETE twice; that must not 404.
        assert client.delete("/api/reflection/draft").status_code == 204


class TestDraftIsolationFromHistory:
    def test_draft_is_flagged_and_excluded_from_history(
        self, app, client, monkeypatch,
    ):
        _bypass_auth(monkeypatch)
        body = client.put(
            "/api/reflection/draft", json={"text": "half a thought"},
        ).get_json()
        assert body["draft"]["is_draft"] is True

        listing = client.get("/api/reflection").get_json()["reflections"]
        assert listing == [], "an unsubmitted draft is not history"

    def test_discarded_draft_does_not_linger_as_soft_deleted(
        self, app, client, monkeypatch,
    ):
        """An abandoned draft was never a reflection, so it must not clutter
        the Recently-deleted list. The keep-every-transcript-forever promise
        (#165) is about SUBMITTED reflections."""
        _bypass_auth(monkeypatch)
        client.put("/api/reflection/draft", json={"text": "scrap this"})
        client.delete("/api/reflection/draft")

        deleted = client.get(
            "/api/reflection?include_deleted=true",
        ).get_json()["reflections"]
        assert deleted == []
        with app.app_context():
            assert db.session.scalar(select(func.count(Reflection.id))) == 0

    def test_draft_does_not_hide_real_reflections_from_history(
        self, app, client, monkeypatch,
    ):
        """Excluding drafts must not accidentally exclude everything."""
        _bypass_auth(monkeypatch)
        with patch(
            "reflection_api.analyze_reflection", return_value=_NO_ANALYSIS,
        ):
            client.post("/api/reflection", json={"text": "a real reflection"})
        client.put("/api/reflection/draft", json={"text": "and a new draft"})

        listing = client.get("/api/reflection").get_json()["reflections"]
        assert len(listing) == 1
        assert listing[0]["transcript"] == "a real reflection"


class TestDraftRetirementOnSubmit:
    def test_submitting_retires_the_draft(self, app, client, monkeypatch):
        """After submit there must be exactly ONE copy of the text. A
        surviving draft would reappear on the next page load and invite a
        duplicate submit."""
        _bypass_auth(monkeypatch)
        client.put("/api/reflection/draft", json={"text": "a week of work"})
        with patch(
            "reflection_api.analyze_reflection", return_value=_NO_ANALYSIS,
        ):
            resp = client.post(
                "/api/reflection", json={"text": "a week of work"},
            )
        assert resp.status_code == 201
        assert client.get("/api/reflection/draft").get_json()["draft"] is None

        listing = client.get("/api/reflection").get_json()["reflections"]
        assert len(listing) == 1
        assert listing[0]["is_draft"] is False

    def test_draft_retired_even_when_claude_analysis_fails(
        self, app, client, monkeypatch,
    ):
        """The transcript is persisted BEFORE the Claude call, so a failed
        analysis still means the reflection exists. The draft must go too,
        or the same text ends up in two places."""
        _bypass_auth(monkeypatch)
        client.put("/api/reflection/draft", json={"text": "a week of work"})
        with patch(
            "reflection_api.analyze_reflection",
            side_effect=RuntimeError("claude down"),
        ):
            resp = client.post(
                "/api/reflection", json={"text": "a week of work"},
            )
        assert resp.status_code == 422
        assert resp.get_json()["saved"] is True
        assert client.get("/api/reflection/draft").get_json()["draft"] is None
        with app.app_context():
            assert db.session.scalar(
                select(func.count(Reflection.id)).where(
                    Reflection.is_draft.is_(False)
                )
            ) == 1


class TestDraftValidationAndAuth:
    def test_non_string_text_rejected(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        assert client.put(
            "/api/reflection/draft", json={"text": 42},
        ).status_code == 422

    def test_non_list_raw_segments_rejected(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        assert client.put(
            "/api/reflection/draft",
            json={"text": "ok", "raw_segments": "nope"},
        ).status_code == 422

    def test_raw_segments_round_trip_and_mark_voice(
        self, app, client, monkeypatch,
    ):
        _bypass_auth(monkeypatch)
        seg = {"text": "spoken words", "duration_seconds": 3.0,
               "cost_usd": 0.001, "recorded_at": "2026-09-22T10:00:00Z"}
        resp = client.put(
            "/api/reflection/draft",
            json={"text": "spoken words", "raw_segments": [seg]},
        )
        assert resp.status_code == 200
        body = resp.get_json()["draft"]
        assert len(body["raw_segments"]) == 1
        assert body["raw_segments"][0]["text"] == "spoken words"
        # A draft assembled from voice segments is VOICE, not TYPED —
        # otherwise the submitted reflection would misreport how it was
        # captured.
        assert body["input_mode"] == "voice"

    def test_draft_endpoints_require_auth(self, app, client):
        """No _bypass_auth here — these must not be open."""
        for call in (
            lambda: client.get("/api/reflection/draft"),
            lambda: client.put("/api/reflection/draft", json={"text": "x"}),
            lambda: client.delete("/api/reflection/draft"),
        ):
            assert call().status_code in (302, 401, 403)
