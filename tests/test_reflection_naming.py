"""#339 — naming a reflection sitting.

History rows were labelled `iso_week - date - input_mode`, identical for
two reflections written on the same day in the same mode. The user could
not tell a throwaway test apart from a real multi-hour session.

A title is also continuity signal: it is the user's own words for what a
sitting was about, so it rides into the prompt alongside the transcript.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import auth


def _fake_claude():
    return {
        "content": [{"text": json.dumps({"explicit": [], "suggested": []})}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def _saved(client, monkeypatch, text="A week of prep."):
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    with patch("reflection_service._call_claude", return_value=_fake_claude()):
        resp = client.post("/api/reflection", json={"text": text})
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


class TestTitleColumn:
    def test_a_new_reflection_starts_unnamed(self, client, monkeypatch):
        """NULL, not "" — so "unnamed" is a single state and the client's
        fallback label rule has exactly one thing to test for."""
        rid = _saved(client, monkeypatch)
        assert client.get(f"/api/reflection/{rid}").get_json()["title"] is None


class TestRenameRoute:
    def test_names_a_reflection(self, client, monkeypatch):
        rid = _saved(client, monkeypatch)
        resp = client.patch(f"/api/reflection/{rid}",
                            json={"title": "DTCC week 1 plan"})
        assert resp.status_code == 200
        assert resp.get_json()["title"] == "DTCC week 1 plan"
        assert client.get(f"/api/reflection/{rid}").get_json()["title"] \
            == "DTCC week 1 plan"

    def test_whitespace_is_trimmed(self, client, monkeypatch):
        rid = _saved(client, monkeypatch)
        resp = client.patch(f"/api/reflection/{rid}",
                            json={"title": "   Handover notes   "})
        assert resp.get_json()["title"] == "Handover notes"

    def test_a_blank_title_clears_the_name(self, client, monkeypatch):
        """Storing "" would render as a blank row label — indistinguishable
        from a bug. Blank must mean "go back to the generated label"."""
        rid = _saved(client, monkeypatch)
        client.patch(f"/api/reflection/{rid}", json={"title": "temp"})
        resp = client.patch(f"/api/reflection/{rid}", json={"title": "   "})
        assert resp.status_code == 200
        assert resp.get_json()["title"] is None

    def test_an_overlong_title_is_capped_not_rejected(self, client, monkeypatch):
        """The column is String(200). Truncating beats a 500 from the DB
        or an error on a harmless paste."""
        rid = _saved(client, monkeypatch)
        resp = client.patch(f"/api/reflection/{rid}", json={"title": "x" * 500})
        assert resp.status_code == 200
        assert len(resp.get_json()["title"]) == 200

    def test_a_non_string_title_is_422(self, client, monkeypatch):
        rid = _saved(client, monkeypatch)
        resp = client.patch(f"/api/reflection/{rid}", json={"title": 42})
        assert resp.status_code == 422

    def test_unknown_id_is_404(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        resp = client.patch(
            "/api/reflection/00000000-0000-0000-0000-000000000339",
            json={"title": "nope"},
        )
        assert resp.status_code == 404

    def test_body_is_required(self, client, monkeypatch):
        rid = _saved(client, monkeypatch)
        assert client.patch(f"/api/reflection/{rid}").status_code == 400

    def test_requires_auth(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.patch(
            "/api/reflection/00000000-0000-0000-0000-000000000339",
            json={"title": "nope"},
        )
        assert resp.status_code in (302, 401, 403)

    def test_rename_is_not_reachable_by_GET(self, client, monkeypatch):
        """#190: a state-mutating GET is a CSRF surface — SameSite=Lax
        does not block a top-level cross-origin GET."""
        rid = _saved(client, monkeypatch)
        assert client.get(f"/api/reflection/{rid}?title=pwned").get_json()[
            "title"
        ] is None


class TestTitleReachesThePrompt:
    def test_a_named_sitting_is_named_in_the_continuity_block(
        self, client, monkeypatch
    ):
        """A date alone says when; the user's own name says what it was
        about. If the title never reached the prompt, naming would be
        cosmetic."""
        rid = _saved(client, monkeypatch, text="Mapped the DTCC onboarding.")
        client.patch(f"/api/reflection/{rid}", json={"title": "Onboarding map"})

        seen = {}

        def _capture(api_key, prompt):
            seen["prompt"] = prompt
            return _fake_claude()

        with patch("reflection_service._call_claude", side_effect=_capture):
            client.post("/api/reflection", json={"text": "Following up today."})

        assert "Onboarding map" in seen["prompt"]

    def test_an_unnamed_sitting_still_appears_by_date(self, client, monkeypatch):
        _saved(client, monkeypatch, text="Unnamed but still context.")
        seen = {}

        def _capture(api_key, prompt):
            seen["prompt"] = prompt
            return _fake_claude()

        with patch("reflection_service._call_claude", side_effect=_capture):
            client.post("/api/reflection", json={"text": "Following up."})

        assert "Unnamed but still context." in seen["prompt"]
