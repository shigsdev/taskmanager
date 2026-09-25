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


class TestRawSegmentsSurviveATextOnlySave:
    """#330: a text-only autosave must not erase the Whisper audit trail.

    ``save_draft`` used to assign ``draft.raw_segments`` unconditionally,
    so a PUT carrying only ``text`` wiped the per-segment record
    (verbatim Whisper output, duration, cost). Found while fixing the
    client-side ordering half of #330 — and strictly worse than it, since
    it loses every segment rather than the last one.

    The path is real, not theoretical: dictate on the phone, open the
    reflection on the laptop with something already in the textarea, and
    the client's restore deliberately bails rather than clobber what you
    were typing — leaving its segment buffer empty. The next keystroke's
    autosave then sends text alone.
    """

    _SEGS = [
        {"text": "first spoken chunk", "duration_seconds": 12.5,
         "cost_usd": 0.0012, "recorded_at": "2026-09-25T09:00:00Z"},
        {"text": "second spoken chunk", "duration_seconds": 8.0,
         "cost_usd": 0.0008, "recorded_at": "2026-09-25T09:02:00Z"},
    ]

    def _put(self, client, body):
        resp = client.put("/api/reflection/draft", json=body)
        assert resp.status_code == 200
        return resp.get_json()["draft"]

    def test_text_only_autosave_keeps_the_segments(
        self, app, client, monkeypatch,
    ):
        _bypass_auth(monkeypatch)
        self._put(client, {"text": "two chunks so far",
                           "raw_segments": self._SEGS})
        # The wipe: an edit typed after dictating, sending text alone.
        after = self._put(client, {"text": "two chunks so far plus typing"})
        assert [s["text"] for s in after["raw_segments"]] == [
            "first spoken chunk", "second spoken chunk",
        ]
        # The costed telemetry is the whole point of the trail — a
        # surviving list of bare strings would still be a loss.
        assert after["raw_segments"][0]["cost_usd"] == 0.0012
        assert after["raw_segments"][1]["duration_seconds"] == 8.0

    def test_survives_repeated_text_only_saves(
        self, app, client, monkeypatch,
    ):
        """The autosave fires on every keystroke burst, not once."""
        _bypass_auth(monkeypatch)
        self._put(client, {"text": "spoken", "raw_segments": self._SEGS})
        for i in range(5):
            self._put(client, {"text": f"spoken, edit {i}"})
        draft = client.get("/api/reflection/draft").get_json()["draft"]
        assert len(draft["raw_segments"]) == 2

    def test_input_mode_stays_voice_across_a_text_only_save(
        self, app, client, monkeypatch,
    ):
        """Editing dictated text must not re-file the sitting as typed."""
        _bypass_auth(monkeypatch)
        self._put(client, {"text": "spoken", "raw_segments": self._SEGS})
        after = self._put(client, {"text": "spoken, then edited"})
        assert after["input_mode"] == "voice"

    def test_an_explicit_empty_list_still_clears(
        self, app, client, monkeypatch,
    ):
        """UNSET means unchanged; ``[]`` means clear. Keep the escape hatch."""
        _bypass_auth(monkeypatch)
        self._put(client, {"text": "spoken", "raw_segments": self._SEGS})
        after = self._put(client, {"text": "spoken", "raw_segments": []})
        assert after["raw_segments"] == []

    def test_a_later_save_can_still_grow_the_list(
        self, app, client, monkeypatch,
    ):
        """The client-side half of #330: segment 3 lands and is sent."""
        _bypass_auth(monkeypatch)
        self._put(client, {"text": "spoken", "raw_segments": self._SEGS})
        third = {"text": "third spoken chunk", "duration_seconds": 4.0,
                 "cost_usd": 0.0004, "recorded_at": "2026-09-25T09:05:00Z"}
        after = self._put(client, {
            "text": "spoken more", "raw_segments": [*self._SEGS, third],
        })
        assert [s["text"] for s in after["raw_segments"]] == [
            "first spoken chunk", "second spoken chunk", "third spoken chunk",
        ]

    def test_submitting_without_segments_falls_back_to_the_draft(
        self, app, client, monkeypatch,
    ):
        """The end-to-end consequence: what lands in history.

        This is the assertion the user would actually notice — the
        reflection they keep forever either carries its audit trail or
        doesn't. The submit POST here sends NO raw_segments, which is
        exactly what the second device sends when its restore bailed:
        the draft holds the segments, the client's buffer doesn't.
        """
        _bypass_auth(monkeypatch)
        self._put(client, {"text": "spoken", "raw_segments": self._SEGS})
        self._put(client, {"text": "spoken, tidied up on the laptop"})
        with patch(
            "reflection_api.analyze_reflection", return_value=_NO_ANALYSIS,
        ):
            resp = client.post(
                "/api/reflection",
                json={"text": "spoken, tidied up on the laptop"},
            )
        assert resp.status_code == 201
        saved = db.session.scalars(
            select(Reflection).where(Reflection.is_draft.is_(False))
        ).all()
        assert len(saved) == 1
        assert [s["text"] for s in (saved[0].raw_segments or [])] == [
            "first spoken chunk", "second spoken chunk",
        ]
        assert saved[0].transcript == "spoken, tidied up on the laptop"
        # And the sitting is still filed as voice-captured, since it was.
        assert saved[0].input_mode.value == "voice"

    def test_the_clients_live_buffer_wins_over_the_draft(
        self, app, client, monkeypatch,
    ):
        """The fallback must not override a client that IS ahead.

        The normal path: the draft's last flush got 2 segments through, a
        third landed, and Done posts all 3 directly. Preferring the draft
        here would silently drop the newest segment — the very bug #330
        set out to fix, reintroduced from the other side.
        """
        _bypass_auth(monkeypatch)
        self._put(client, {"text": "spoken", "raw_segments": self._SEGS})
        third = {"text": "third spoken chunk", "duration_seconds": 4.0,
                 "cost_usd": 0.0004, "recorded_at": "2026-09-25T09:05:00Z"}
        with patch(
            "reflection_api.analyze_reflection", return_value=_NO_ANALYSIS,
        ):
            resp = client.post("/api/reflection", json={
                "text": "spoken three times",
                "raw_segments": [*self._SEGS, third],
            })
        assert resp.status_code == 201
        saved = db.session.scalars(
            select(Reflection).where(Reflection.is_draft.is_(False))
        ).all()
        assert [s["text"] for s in (saved[0].raw_segments or [])] == [
            "first spoken chunk", "second spoken chunk", "third spoken chunk",
        ]

    def test_a_typed_submit_with_no_draft_segments_stays_typed(
        self, app, client, monkeypatch,
    ):
        """The fallback must not invent a voice sitting out of nothing."""
        _bypass_auth(monkeypatch)
        self._put(client, {"text": "just typing"})
        with patch(
            "reflection_api.analyze_reflection", return_value=_NO_ANALYSIS,
        ):
            resp = client.post("/api/reflection", json={"text": "just typing"})
        assert resp.status_code == 201
        saved = db.session.scalars(
            select(Reflection).where(Reflection.is_draft.is_(False))
        ).all()
        assert (saved[0].raw_segments or []) == []
        assert saved[0].input_mode.value == "typed"

    def test_a_typed_only_draft_is_unaffected(
        self, app, client, monkeypatch,
    ):
        """No segments were ever sent, so there is nothing to preserve."""
        _bypass_auth(monkeypatch)
        self._put(client, {"text": "just typing"})
        after = self._put(client, {"text": "just typing, more"})
        assert after["raw_segments"] == []
        assert after["input_mode"] == "typed"
